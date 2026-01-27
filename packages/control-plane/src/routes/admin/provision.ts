/**
 * Tenant provisioning routes
 *
 * Handles async provisioning flow with progress streaming.
 * Supports deploying dedicated workers and containers for enterprise tenants.
 *
 * @see https://developers.cloudflare.com/workers/configuration/
 * @see https://developers.cloudflare.com/containers/
 */

import { Hono } from 'hono';
import { HTTPException } from 'hono/http-exception';
import { zValidator } from '@hono/zod-validator';
import { z } from 'zod';
import { TIER_LIMITS, getSecret, getSecrets } from '@maven/shared';
import { createTenant, getTenantById, getTenantBySlug, updateTenant } from '../../services/database';
import {
  deployTenantWorker,
  configureTenantSandbox,
  stopAgentContainer,
  deleteTenantWorker,
  updateWorkerSecrets,
  validateContainerImage,
} from '../../services/worker-deploy';
import type { Env, Variables } from '../../index';

const app = new Hono<{ Bindings: Env; Variables: Variables }>();

// Provision request schema
const provisionRequestSchema = z.object({
  name: z.string().min(1).max(100),
  slug: z.string().min(1).max(50).regex(/^[a-z0-9-]+$/, 'Slug must be lowercase alphanumeric with hyphens'),
  tier: z.enum(['starter', 'pro', 'enterprise']),
});

// Map UI tier names to internal tier names
const tierMap: Record<string, string> = {
  starter: 'starter',
  pro: 'professional',
  enterprise: 'enterprise',
};

// Provisioning steps by tier
const PROVISIONING_STEPS = {
  starter: [
    { id: 'create_tenant', name: 'Create Tenant Record' },
    { id: 'setup_storage', name: 'Setup Shared Storage' },
    { id: 'configure_limits', name: 'Configure Rate Limits' },
  ],
  pro: [
    { id: 'validate_prerequisites', name: 'Validate Prerequisites' },
    { id: 'create_tenant', name: 'Create Tenant Record' },
    { id: 'provision_storage', name: 'Provision Dedicated Storage' },
    { id: 'provision_kv', name: 'Provision KV Store' },
    { id: 'deploy_worker', name: 'Deploy Dedicated Worker' },
    { id: 'configure_worker_secrets', name: 'Configure Worker Secrets' },
    { id: 'configure_sandbox', name: 'Configure Sandbox Access' },
    { id: 'configure_limits', name: 'Configure Rate Limits' },
  ],
  enterprise: [
    { id: 'validate_prerequisites', name: 'Validate Prerequisites' },
    { id: 'create_tenant', name: 'Create Tenant Record' },
    { id: 'provision_storage', name: 'Provision Dedicated Storage' },
    { id: 'provision_kv', name: 'Provision KV Store' },
    { id: 'deploy_worker', name: 'Deploy Dedicated Worker' },
    { id: 'configure_worker_secrets', name: 'Configure Worker Secrets' },
    { id: 'configure_sandbox', name: 'Configure Sandbox Access' },
    { id: 'configure_limits', name: 'Configure Rate Limits' },
  ],
};

interface ProvisioningJob {
  id: string;
  tenant_id: string;
  tenant_name: string;
  tenant_slug: string;
  tier: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  current_step: number;
  total_steps: number;
  steps_completed: string[];
  steps_skipped: string[];
  current_step_name: string | null;
  error: string | null;
  created_at: number;
  updated_at: number;
  completed_at: number | null;
  // Results from provisioning steps
  worker_url?: string;
  container_id?: string;
  steps: Array<{
    id: string;
    name: string;
    status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped';
    skipped_reason?: string;
    result?: unknown;
  }>;
}

// Generate tenant ID as UUID
function generateTenantId(): string {
  return crypto.randomUUID();
}

// Start provisioning
app.post('/', zValidator('json', provisionRequestSchema), async (c) => {
  const { name, slug, tier } = c.req.valid('json');

  // Generate IDs
  const tenantId = generateTenantId();
  const jobId = crypto.randomUUID();

  // Check if tenant already exists by slug
  const existingTenant = await getTenantBySlug(c.env.DB, slug);
  if (existingTenant) {
    throw new HTTPException(409, { message: 'Tenant with this slug already exists' });
  }

  // Validate Cloudflare credentials are available for pro/enterprise tiers
  if ((tier === 'pro' || tier === 'enterprise') && (!c.env.CF_ACCOUNT_ID || !c.env.CF_API_TOKEN)) {
    console.warn(`${tier} tier provisioning without Cloudflare credentials - dedicated worker deployment will be skipped`);
  }

  // Get steps for this tier
  const steps = PROVISIONING_STEPS[tier as keyof typeof PROVISIONING_STEPS] || PROVISIONING_STEPS.starter;

  // Create initial job state
  const job: ProvisioningJob = {
    id: jobId,
    tenant_id: tenantId,
    tenant_name: name,
    tenant_slug: slug,
    tier,
    status: 'running',
    current_step: 0,
    total_steps: steps.length,
    steps_completed: [],
    steps_skipped: [],
    current_step_name: steps[0]?.name || null,
    error: null,
    created_at: Date.now(),
    updated_at: Date.now(),
    completed_at: null,
    steps: steps.map(s => ({ ...s, status: 'pending' as const })),
  };

  // Store job in KV
  await c.env.KV.put(`provision:${jobId}`, JSON.stringify(job), { expirationTtl: 3600 });

  // Start async provisioning (non-blocking)
  c.executionCtx.waitUntil(executeProvisioning(c.env, job));

  return c.json({
    job_id: jobId,
    tenant_id: tenantId,
    slug,
    tier,
    status: 'running',
  }, 202);
});

// Get job status
app.get('/:jobId', async (c) => {
  const jobId = c.req.param('jobId');

  const jobData = await c.env.KV.get(`provision:${jobId}`);
  if (!jobData) {
    throw new HTTPException(404, { message: 'Provisioning job not found' });
  }

  const job = JSON.parse(jobData) as ProvisioningJob;
  return c.json(job);
});

// Stream provisioning progress (NDJSON format)
app.get('/:jobId/stream', async (c) => {
  const jobId = c.req.param('jobId');

  const jobData = await c.env.KV.get(`provision:${jobId}`);
  if (!jobData) {
    throw new HTTPException(404, { message: 'Provisioning job not found' });
  }

  /**
   * Write NDJSON line to stream
   */
  const ndjsonLine = (data: unknown): string => JSON.stringify(data) + '\n';

  // Create a readable stream that polls for updates
  const stream = new ReadableStream({
    async start(controller) {
      const encoder = new TextEncoder();
      let lastStatus = '';
      let attempts = 0;
      const maxAttempts = 60; // 30 seconds max

      const poll = async () => {
        const data = await c.env.KV.get(`provision:${jobId}`);
        if (!data) {
          controller.enqueue(encoder.encode(ndjsonLine({ type: 'failed', error: 'Job not found' })));
          controller.close();
          return;
        }

        const job = JSON.parse(data) as ProvisioningJob;

        // Send step updates
        if (job.status !== lastStatus || job.current_step_name) {
          if (job.status === 'running' && job.current_step_name) {
            controller.enqueue(encoder.encode(ndjsonLine({
              type: 'step_started',
              step_id: job.steps[job.current_step]?.id,
              step_name: job.current_step_name,
              step_number: job.current_step + 1,
            })));
          }

          if (job.status === 'completed') {
            controller.enqueue(encoder.encode(ndjsonLine({
              type: 'completed',
              tenant_id: job.tenant_id,
            })));
            controller.close();
            return;
          }

          if (job.status === 'failed') {
            controller.enqueue(encoder.encode(ndjsonLine({
              type: 'failed',
              error: job.error || 'Unknown error',
            })));
            controller.close();
            return;
          }

          lastStatus = job.status;
        }

        attempts++;
        if (attempts < maxAttempts && job.status === 'running') {
          setTimeout(poll, 500);
        } else if (attempts >= maxAttempts) {
          controller.enqueue(encoder.encode(ndjsonLine({
            type: 'failed',
            error: 'Provisioning timeout',
          })));
          controller.close();
        }
      };

      poll();
    },
  });

  return new Response(stream, {
    headers: {
      'Content-Type': 'application/x-ndjson',
      'Cache-Control': 'no-cache, no-transform',
      'Connection': 'keep-alive',
      'X-Accel-Buffering': 'no',
    },
  });
});

// Execute provisioning steps
async function executeProvisioning(env: Env, job: ProvisioningJob) {
  try {
    const steps = job.steps;

    for (let i = 0; i < steps.length; i++) {
      const step = steps[i];

      // Update job status
      job.current_step = i;
      job.current_step_name = step.name;
      job.steps[i].status = 'running';
      job.updated_at = Date.now();
      await env.KV.put(`provision:${job.id}`, JSON.stringify(job), { expirationTtl: 3600 });

      // Execute step
      try {
        switch (step.id) {
          case 'validate_prerequisites': {
            // Validate all prerequisites before creating any resources
            // This ensures we fail fast with helpful errors

            // 1. Check Cloudflare credentials
            if (!env.CF_ACCOUNT_ID || !env.CF_API_TOKEN) {
              throw new Error(
                'Cloudflare credentials not configured. Set CF_ACCOUNT_ID and CF_API_TOKEN in Secrets Store.'
              );
            }

            const [accountId, apiToken] = await Promise.all([
              getSecret(env.CF_ACCOUNT_ID),
              getSecret(env.CF_API_TOKEN),
            ]);

            if (!accountId || !apiToken) {
              throw new Error('Failed to resolve Cloudflare credentials from Secrets Store.');
            }

            // 2. Check container image exists (best-effort, API may not be accessible)
            // Image tag is configurable via AGENT_IMAGE_TAG env var, defaults to v1.0.0
            const imageTag = env.AGENT_IMAGE_TAG || 'v1.0.0';
            const imageValidated = await validateContainerImage({ accountId, apiToken }, imageTag);

            // 3. Check tenant-worker bundle exists in R2
            if (env.FILES) {
              const bundle = await env.FILES.get('bundles/tenant-worker.js');
              if (!bundle) {
                throw new Error(
                  'Tenant worker bundle not found in R2. Run: cd packages/tenant-worker && npm run build && npx wrangler r2 object put maven-files/bundles/tenant-worker.js --file dist/index.js --remote'
                );
              }
            }

            job.steps[i].result = {
              validated: true,
              imageTag,
              imageValidated, // false if Containers API wasn't accessible
            };
            break;
          }

          case 'create_tenant': {
            // Map tier for database
            const dbTier = job.tier === 'pro' ? 'professional' : job.tier;
            const tierLimits = TIER_LIMITS[dbTier as keyof typeof TIER_LIMITS] || TIER_LIMITS.starter;

            await createTenant(env.DB, {
              id: job.tenant_id,
              name: job.tenant_name,
              slug: job.tenant_slug,
              tier: dbTier as 'free' | 'starter' | 'professional' | 'enterprise',
              enabled: true,
              settings: {
                ...tierLimits,
                worker_url: undefined, // Will be set after deployment
                container_id: undefined,
              },
            });
            break;
          }

          case 'provision_storage':
          case 'setup_storage':
            // For now, using shared storage (R2)
            // In the future, could create dedicated R2 buckets per tenant
            if (job.tier === 'starter') {
              job.steps[i].status = 'skipped';
              job.steps[i].skipped_reason = 'Using shared storage';
              job.steps_skipped.push(step.id);
              continue;
            }
            // Pro/Enterprise: placeholder for dedicated storage
            break;

          case 'provision_kv':
            // For now, using shared KV with tenant-prefixed keys
            // In the future, could create dedicated KV namespaces
            break;

          case 'deploy_worker': {
            // Deploy dedicated worker for pro and enterprise tenants
            if (job.tier === 'starter') {
              job.steps[i].status = 'skipped';
              job.steps[i].skipped_reason = 'Using shared worker';
              job.steps_skipped.push(step.id);
              continue;
            }

            // Check if Cloudflare credentials are available
            if (!env.CF_ACCOUNT_ID || !env.CF_API_TOKEN) {
              job.steps[i].status = 'skipped';
              job.steps[i].skipped_reason = 'Cloudflare credentials not configured';
              job.steps_skipped.push(step.id);
              continue;
            }

            const workerResult = await deployTenantWorker(
              job.tenant_id,
              job.tenant_slug,
              job.tier,
              env
            );

            job.worker_url = workerResult.workerUrl;
            job.steps[i].result = workerResult;
            break;
          }

          case 'configure_worker_secrets': {
            // Configure secrets on the dedicated worker
            if (job.tier === 'starter' || !job.worker_url) {
              job.steps[i].status = 'skipped';
              job.steps[i].skipped_reason = 'No dedicated worker';
              job.steps_skipped.push(step.id);
              continue;
            }

            // Resolve secrets from Secrets Store
            const [jwtPublicKey, internalApiKey] = await getSecrets([
              env.JWT_PUBLIC_KEY,
              env.INTERNAL_API_KEY,
            ]);

            await updateWorkerSecrets(
              `maven-tenant-${job.tenant_slug}`,
              {
                JWT_PUBLIC_KEY: jwtPublicKey,
                INTERNAL_API_KEY: internalApiKey,
              },
              env
            );
            break;
          }

          case 'configure_sandbox': {
            // Configure sandbox access for pro/enterprise
            // Sandboxes use Cloudflare Sandbox SDK via Durable Object bindings
            if (job.tier === 'starter') {
              job.steps[i].status = 'skipped';
              job.steps[i].skipped_reason = 'Using shared sandbox';
              job.steps_skipped.push(step.id);
              continue;
            }

            const sandboxResult = await configureTenantSandbox(
              job.tenant_id,
              job.tenant_slug,
              env
            );

            job.container_id = sandboxResult.containerId;
            job.steps[i].result = sandboxResult;
            break;
          }

          case 'configure_limits':
            // Rate limits already set during tenant creation
            // This step confirms the configuration
            break;

          default:
            // Unknown step - skip
            job.steps[i].status = 'skipped';
            job.steps[i].skipped_reason = 'Unknown step';
            job.steps_skipped.push(step.id);
            continue;
        }

        // Mark step completed
        job.steps[i].status = 'completed';
        job.steps_completed.push(step.id);
      } catch (stepError) {
        // Step failed - mark and continue or abort based on step criticality
        const errorMessage = stepError instanceof Error ? stepError.message : 'Unknown error';
        console.error(`Step ${step.id} failed:`, errorMessage);

        // Critical steps that should abort provisioning
        const criticalSteps = ['validate_prerequisites', 'create_tenant', 'deploy_worker'];
        if (criticalSteps.includes(step.id)) {
          throw stepError;
        }

        // Non-critical steps can be skipped
        job.steps[i].status = 'skipped';
        job.steps[i].skipped_reason = `Failed: ${errorMessage}`;
        job.steps_skipped.push(step.id);
      }

      job.updated_at = Date.now();
      await env.KV.put(`provision:${job.id}`, JSON.stringify(job), { expirationTtl: 3600 });
    }

    // Update tenant with deployment info
    if (job.worker_url || job.container_id) {
      // Get current tenant to preserve existing settings
      const currentTenant = await getTenantById(env.DB, job.tenant_id);
      if (currentTenant) {
        await updateTenant(env.DB, job.tenant_id, {
          settings: {
            ...currentTenant.settings,
            worker_url: job.worker_url,
            container_id: job.container_id,
          },
        });
      }
    }

    // Mark job completed
    job.status = 'completed';
    job.current_step_name = null;
    job.completed_at = Date.now();
    job.updated_at = Date.now();
    await env.KV.put(`provision:${job.id}`, JSON.stringify(job), { expirationTtl: 3600 });

  } catch (error) {
    // Mark job failed
    job.status = 'failed';
    job.error = error instanceof Error ? error.message : 'Unknown error';
    job.updated_at = Date.now();

    // Attempt cleanup if tenant was created
    if (job.steps_completed.includes('create_tenant')) {
      try {
        // Cleanup deployed resources
        if (job.container_id) {
          await stopAgentContainer(job.tenant_slug, env).catch(() => {});
        }
        if (job.worker_url && (job.tier === 'pro' || job.tier === 'enterprise')) {
          await deleteTenantWorker(job.tenant_slug, env).catch(() => {});
        }
      } catch (cleanupError) {
        console.error('Cleanup failed:', cleanupError);
      }
    }

    await env.KV.put(`provision:${job.id}`, JSON.stringify(job), { expirationTtl: 3600 });
  }
}

export { app as provisionRoute };
