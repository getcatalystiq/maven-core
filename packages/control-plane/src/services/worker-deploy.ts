/**
 * Worker Deployment Service
 *
 * Handles deploying dedicated Cloudflare Workers for tenants.
 * Pro and Enterprise tiers get dedicated workers with full functionality
 * including Durable Objects and Sandbox containers.
 *
 * @see https://developers.cloudflare.com/api/resources/workers/subresources/scripts/
 * @see https://developers.cloudflare.com/durable-objects/
 */

import type { Env } from '../index';

// Cloudflare API base URL
const CF_API_BASE = 'https://api.cloudflare.com/client/v4';

// Container image for tenant sandboxes
// v1.5.0: Non-root user fix (Claude CLI requires non-root for --dangerously-skip-permissions)
const SANDBOX_IMAGE = 'registry.cloudflare.com/7b7fb01e095cae40c829f948caa48f54/maven-agent:v1.5.0';

// Types for Cloudflare API responses
interface CloudflareApiResponse<T = unknown> {
  success: boolean;
  errors: Array<{ code: number; message: string }>;
  messages: string[];
  result: T;
}

interface WorkerScript {
  id: string;
  tag: string;
  etag: string;
  modified_on: string;
}

interface WorkerDeploymentResult {
  workerName: string;
  workerUrl: string;
  deployedAt: string;
}

interface ContainerStartResult {
  containerId: string;
  status: string;
  startedAt: string;
}

/**
 * Deploy a dedicated tenant worker
 *
 * For Pro and Enterprise tiers, deploys the full tenant-worker with:
 * - TenantAgent Durable Object for session management
 * - Sandbox container binding for code execution
 * - Tenant-specific configuration
 */
export async function deployTenantWorker(
  tenantId: string,
  tenantSlug: string,
  tier: string,
  env: Env
): Promise<WorkerDeploymentResult> {
  if (!env.CF_ACCOUNT_ID || !env.CF_API_TOKEN) {
    throw new Error('Cloudflare credentials not configured (CF_ACCOUNT_ID, CF_API_TOKEN)');
  }

  const workerName = `maven-tenant-${tenantSlug}`;

  // Starter tier uses the shared worker
  if (tier === 'starter' || tier === 'free') {
    return {
      workerName: 'maven-tenant',
      workerUrl: 'https://maven-tenant.tools-7b7.workers.dev',
      deployedAt: new Date().toISOString(),
    };
  }

  // Pro and Enterprise get dedicated workers with full tenant-worker functionality
  // Fetch the pre-built tenant-worker bundle from R2
  const workerBundle = await fetchTenantWorkerBundle(env);
  if (!workerBundle) {
    throw new Error('Tenant worker bundle not found. Run `npm run build:tenant-worker` first.');
  }

  // Build metadata with Durable Objects bindings
  const metadata = {
    main_module: 'index.js',
    compatibility_date: '2025-01-23',
    compatibility_flags: ['nodejs_compat'],
    bindings: [
      // Durable Object bindings
      {
        type: 'durable_object_namespace',
        name: 'TENANT_AGENT',
        class_name: 'TenantAgent',
      },
      {
        type: 'durable_object_namespace',
        name: 'Sandbox',
        class_name: 'Sandbox',
      },
      // Environment variables
      {
        type: 'plain_text',
        name: 'JWT_ISSUER',
        text: 'https://maven.example.com',
      },
      {
        type: 'plain_text',
        name: 'CONTROL_PLANE_URL',
        text: 'https://maven-control-plane.tools-7b7.workers.dev',
      },
      {
        type: 'plain_text',
        name: 'TENANT_ID',
        text: tenantId,
      },
      {
        type: 'plain_text',
        name: 'TENANT_SLUG',
        text: tenantSlug,
      },
      {
        type: 'plain_text',
        name: 'AWS_REGION',
        text: 'us-east-1',
      },
    ],
    // Durable Objects migrations
    migrations: {
      new_sqlite_classes: ['TenantAgent', 'Sandbox'],
      tag: 'v1',
    },
    // Container configuration for Sandbox
    containers: [
      {
        class_name: 'Sandbox',
        image: SANDBOX_IMAGE,
        instance_type: 'basic',
      },
    ],
  };

  // Build multipart form data
  const formData = new FormData();
  formData.append('metadata', JSON.stringify(metadata));

  // Add the worker bundle
  const scriptBlob = new Blob([workerBundle], { type: 'application/javascript+module' });
  formData.append('index.js', scriptBlob, 'index.js');

  // Deploy the worker
  const response = await fetch(
    `${CF_API_BASE}/accounts/${env.CF_ACCOUNT_ID}/workers/scripts/${workerName}`,
    {
      method: 'PUT',
      headers: {
        Authorization: `Bearer ${env.CF_API_TOKEN}`,
      },
      body: formData,
    }
  );

  const result = (await response.json()) as CloudflareApiResponse<WorkerScript>;

  if (!result.success) {
    const errorMessages = result.errors.map((e) => `[${e.code}] ${e.message}`).join(', ');
    throw new Error(`Failed to deploy worker: ${errorMessages}`);
  }

  // Enable workers.dev subdomain
  await enableWorkerSubdomain(workerName, env);

  // Set secrets
  await setWorkerSecrets(workerName, env);

  // Get the account's workers.dev subdomain
  const subdomain = await getWorkersSubdomain(env);

  return {
    workerName,
    workerUrl: `https://${workerName}.${subdomain}.workers.dev`,
    deployedAt: result.result.modified_on,
  };
}

/**
 * Fetch the pre-built tenant-worker bundle from R2
 * This bundle contains the full tenant-worker with TenantAgent DO
 */
async function fetchTenantWorkerBundle(env: Env): Promise<string | null> {
  // Fetch from R2 bucket
  if (env.FILES) {
    try {
      const object = await env.FILES.get('bundles/tenant-worker.js');
      if (object) {
        console.log('Fetched tenant-worker bundle from R2');
        return await object.text();
      }
    } catch (error) {
      console.log('Failed to fetch bundle from R2:', error);
    }
  }

  console.log('Bundle not found in R2, using fallback');
  return null;
}


/**
 * Set worker secrets (JWT keys, API keys)
 */
async function setWorkerSecrets(workerName: string, env: Env): Promise<void> {
  if (!env.CF_ACCOUNT_ID || !env.CF_API_TOKEN) return;

  const secrets: Record<string, string> = {};

  if (env.JWT_PUBLIC_KEY) {
    secrets['JWT_PUBLIC_KEY'] = env.JWT_PUBLIC_KEY;
  }
  if (env.INTERNAL_API_KEY) {
    secrets['INTERNAL_API_KEY'] = env.INTERNAL_API_KEY;
  }

  for (const [name, value] of Object.entries(secrets)) {
    await fetch(
      `${CF_API_BASE}/accounts/${env.CF_ACCOUNT_ID}/workers/scripts/${workerName}/secrets`,
      {
        method: 'PUT',
        headers: {
          Authorization: `Bearer ${env.CF_API_TOKEN}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ name, text: value, type: 'secret_text' }),
      }
    );
  }
}

/**
 * Get the account's workers.dev subdomain
 */
async function getWorkersSubdomain(env: Env): Promise<string> {
  if (!env.CF_ACCOUNT_ID || !env.CF_API_TOKEN) {
    return 'tools-7b7';
  }

  try {
    const response = await fetch(
      `${CF_API_BASE}/accounts/${env.CF_ACCOUNT_ID}/workers/subdomain`,
      {
        headers: { Authorization: `Bearer ${env.CF_API_TOKEN}` },
      }
    );

    const result = (await response.json()) as CloudflareApiResponse<{ subdomain: string }>;
    if (result.success && result.result.subdomain) {
      return result.result.subdomain;
    }
  } catch {
    // ignore
  }

  return 'tools-7b7';
}

/**
 * Enable workers.dev subdomain for a worker
 */
async function enableWorkerSubdomain(workerName: string, env: Env): Promise<void> {
  if (!env.CF_ACCOUNT_ID || !env.CF_API_TOKEN) return;

  await fetch(
    `${CF_API_BASE}/accounts/${env.CF_ACCOUNT_ID}/workers/scripts/${workerName}/subdomain`,
    {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${env.CF_API_TOKEN}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ enabled: true }),
    }
  );
}

/**
 * Configure sandbox access for a tenant
 */
export async function configureTenantSandbox(
  tenantId: string,
  tenantSlug: string,
  _env: Env
): Promise<ContainerStartResult> {
  return {
    containerId: `sandbox-${tenantSlug}`,
    status: 'configured',
    startedAt: new Date().toISOString(),
  };
}

/**
 * @deprecated Use configureTenantSandbox instead
 */
export async function startAgentContainer(
  tenantId: string,
  tenantSlug: string,
  env: Env
): Promise<ContainerStartResult> {
  return configureTenantSandbox(tenantId, tenantSlug, env);
}

/**
 * Cleanup sandbox configuration
 */
export async function stopAgentContainer(_tenantSlug: string, _env: Env): Promise<void> {
  // Sandboxes clean up with the worker
}

/**
 * Delete a tenant's dedicated worker
 */
export async function deleteTenantWorker(tenantSlug: string, env: Env): Promise<void> {
  if (!env.CF_ACCOUNT_ID || !env.CF_API_TOKEN) {
    throw new Error('Cloudflare credentials not configured');
  }

  const workerName = `maven-tenant-${tenantSlug}`;

  await fetch(`${CF_API_BASE}/accounts/${env.CF_ACCOUNT_ID}/workers/scripts/${workerName}`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${env.CF_API_TOKEN}` },
  });
}

/**
 * Check if a tenant worker exists
 */
export async function tenantWorkerExists(tenantSlug: string, env: Env): Promise<boolean> {
  if (!env.CF_ACCOUNT_ID || !env.CF_API_TOKEN) return false;

  const workerName = `maven-tenant-${tenantSlug}`;
  const response = await fetch(
    `${CF_API_BASE}/accounts/${env.CF_ACCOUNT_ID}/workers/scripts/${workerName}`,
    {
      headers: { Authorization: `Bearer ${env.CF_API_TOKEN}` },
    }
  );

  const result = (await response.json()) as CloudflareApiResponse;
  return result.success;
}

/**
 * Update tenant worker secrets
 */
export async function updateWorkerSecrets(
  workerName: string,
  secrets: Record<string, string>,
  env: Env
): Promise<void> {
  if (!env.CF_ACCOUNT_ID || !env.CF_API_TOKEN) {
    throw new Error('Cloudflare credentials not configured');
  }

  for (const [name, value] of Object.entries(secrets)) {
    await fetch(
      `${CF_API_BASE}/accounts/${env.CF_ACCOUNT_ID}/workers/scripts/${workerName}/secrets`,
      {
        method: 'PUT',
        headers: {
          Authorization: `Bearer ${env.CF_API_TOKEN}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ name, text: value, type: 'secret_text' }),
      }
    );
  }
}

/**
 * Get worker deployment status
 */
export async function getWorkerStatus(
  tenantSlug: string,
  env: Env
): Promise<{ exists: boolean; status?: string; modifiedOn?: string }> {
  if (!env.CF_ACCOUNT_ID || !env.CF_API_TOKEN) return { exists: false };

  const workerName = `maven-tenant-${tenantSlug}`;
  const response = await fetch(
    `${CF_API_BASE}/accounts/${env.CF_ACCOUNT_ID}/workers/scripts/${workerName}`,
    {
      headers: { Authorization: `Bearer ${env.CF_API_TOKEN}` },
    }
  );

  const result = (await response.json()) as CloudflareApiResponse<WorkerScript>;

  if (!result.success) return { exists: false };

  return {
    exists: true,
    status: 'deployed',
    modifiedOn: result.result.modified_on,
  };
}
