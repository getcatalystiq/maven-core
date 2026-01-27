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

import { getSecret, getSecrets } from '@maven/shared';
import type { Env } from '../index';

// Cloudflare API base URL
const CF_API_BASE = 'https://api.cloudflare.com/client/v4';

/**
 * Resolved Cloudflare credentials for API calls
 */
interface CloudflareCredentials {
  accountId: string;
  apiToken: string;
}

/**
 * Resolve Cloudflare credentials from Secrets Store or plain strings
 * Returns null if credentials are not configured
 */
async function resolveCloudflareCredentials(env: Env): Promise<CloudflareCredentials | null> {
  if (!env.CF_ACCOUNT_ID || !env.CF_API_TOKEN) {
    return null;
  }

  const [accountId, apiToken] = await Promise.all([
    getSecret(env.CF_ACCOUNT_ID),
    getSecret(env.CF_API_TOKEN),
  ]);

  if (!accountId || !apiToken) {
    return null;
  }

  return { accountId, apiToken };
}

// Container image for tenant sandboxes - configurable via AGENT_IMAGE_TAG env var
// Default: v1.0.0 - override by setting AGENT_IMAGE_TAG env var in wrangler.toml or secrets
const DEFAULT_SANDBOX_IMAGE_TAG = 'v1.0.0';

/**
 * Get the sandbox image tag, allowing override via environment variable
 */
function getSandboxImageTag(env: Env): string {
  // Support configurable image tag via env var or secret
  return env.AGENT_IMAGE_TAG || DEFAULT_SANDBOX_IMAGE_TAG;
}

/**
 * Get the full container image URL for sandboxes
 */
function getSandboxImageUrl(accountId: string, imageTag: string): string {
  return `registry.cloudflare.com/${accountId}/maven-agent:${imageTag}`;
}

/**
 * Validate that the container image exists in Cloudflare's registry
 *
 * Note: The Containers API may not be accessible via standard API tokens.
 * This validation is best-effort - if it fails, we log a warning and continue.
 * The deployment will fail with a clear error if the image doesn't exist.
 *
 * @param creds Cloudflare credentials
 * @param imageTag The image tag to validate (e.g., "v1.0.0")
 * @returns true if validated, false if validation was skipped
 */
export async function validateContainerImage(
  creds: CloudflareCredentials,
  imageTag: string
): Promise<boolean> {
  try {
    const response = await fetch(
      `${CF_API_BASE}/accounts/${creds.accountId}/containers/images`,
      {
        headers: { Authorization: `Bearer ${creds.apiToken}` },
      }
    );

    const result = (await response.json()) as CloudflareApiResponse<Array<{ repository: string; tag: string }>>;

    if (!result.success) {
      // API not accessible - skip validation, deployment will fail if image missing
      console.log(`Container image validation skipped: API returned ${JSON.stringify(result.errors)}`);
      return false;
    }

    const requiredImage = `maven-agent:${imageTag}`;
    const imageExists = result.result.some(
      (img) => img.repository === 'maven-agent' && img.tag === imageTag
    );

    if (!imageExists) {
      const availableTags = result.result
        .filter((img) => img.repository === 'maven-agent')
        .map((img) => img.tag)
        .join(', ');

      const hint = availableTags
        ? `Available tags: ${availableTags}. Set AGENT_IMAGE_TAG env var or push the required version.`
        : `No maven-agent images found. Run: ./scripts/push-agent.sh ${imageTag}`;

      throw new Error(
        `Container image "${requiredImage}" not found in registry. ${hint}`
      );
    }

    return true;
  } catch (err) {
    // If it's our own error about missing image, rethrow
    if (err instanceof Error && err.message.includes('not found in registry')) {
      throw err;
    }
    // Otherwise skip validation
    console.log(`Container image validation skipped: ${err}`);
    return false;
  }
}

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
  const creds = await resolveCloudflareCredentials(env);
  if (!creds) {
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

  // Get image tag (configurable via AGENT_IMAGE_TAG env var)
  const imageTag = getSandboxImageTag(env);

  // Validate container image exists before proceeding
  await validateContainerImage(creds, imageTag);

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
        image: getSandboxImageUrl(creds.accountId, imageTag),
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
    `${CF_API_BASE}/accounts/${creds.accountId}/workers/scripts/${workerName}`,
    {
      method: 'PUT',
      headers: {
        Authorization: `Bearer ${creds.apiToken}`,
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
  await enableWorkerSubdomainWithCreds(workerName, creds);

  // Set secrets
  await setWorkerSecretsWithCreds(workerName, creds, env);

  // Get the account's workers.dev subdomain
  const subdomain = await getWorkersSubdomainWithCreds(creds);

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
 * Set worker secrets with pre-resolved credentials
 */
async function setWorkerSecretsWithCreds(
  workerName: string,
  creds: CloudflareCredentials,
  env: Env
): Promise<void> {
  // Resolve secrets from Secrets Store (production) or plain strings (local dev)
  const [jwtPublicKey, internalApiKey] = await getSecrets([
    env.JWT_PUBLIC_KEY,
    env.INTERNAL_API_KEY,
  ]);

  const secrets: Record<string, string> = {};

  if (jwtPublicKey) {
    secrets['JWT_PUBLIC_KEY'] = jwtPublicKey;
  }
  if (internalApiKey) {
    secrets['INTERNAL_API_KEY'] = internalApiKey;
  }

  for (const [name, value] of Object.entries(secrets)) {
    await fetch(
      `${CF_API_BASE}/accounts/${creds.accountId}/workers/scripts/${workerName}/secrets`,
      {
        method: 'PUT',
        headers: {
          Authorization: `Bearer ${creds.apiToken}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ name, text: value, type: 'secret_text' }),
      }
    );
  }
}

/**
 * Get the account's workers.dev subdomain with pre-resolved credentials
 */
async function getWorkersSubdomainWithCreds(creds: CloudflareCredentials): Promise<string> {
  try {
    const response = await fetch(
      `${CF_API_BASE}/accounts/${creds.accountId}/workers/subdomain`,
      {
        headers: { Authorization: `Bearer ${creds.apiToken}` },
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
 * Enable workers.dev subdomain for a worker with pre-resolved credentials
 */
async function enableWorkerSubdomainWithCreds(
  workerName: string,
  creds: CloudflareCredentials
): Promise<void> {
  await fetch(
    `${CF_API_BASE}/accounts/${creds.accountId}/workers/scripts/${workerName}/subdomain`,
    {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${creds.apiToken}`,
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
  const creds = await resolveCloudflareCredentials(env);
  if (!creds) {
    throw new Error('Cloudflare credentials not configured');
  }

  const workerName = `maven-tenant-${tenantSlug}`;

  await fetch(`${CF_API_BASE}/accounts/${creds.accountId}/workers/scripts/${workerName}`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${creds.apiToken}` },
  });
}

/**
 * Check if a tenant worker exists
 */
export async function tenantWorkerExists(tenantSlug: string, env: Env): Promise<boolean> {
  const creds = await resolveCloudflareCredentials(env);
  if (!creds) return false;

  const workerName = `maven-tenant-${tenantSlug}`;
  const response = await fetch(
    `${CF_API_BASE}/accounts/${creds.accountId}/workers/scripts/${workerName}`,
    {
      headers: { Authorization: `Bearer ${creds.apiToken}` },
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
  const creds = await resolveCloudflareCredentials(env);
  if (!creds) {
    throw new Error('Cloudflare credentials not configured');
  }

  for (const [name, value] of Object.entries(secrets)) {
    await fetch(
      `${CF_API_BASE}/accounts/${creds.accountId}/workers/scripts/${workerName}/secrets`,
      {
        method: 'PUT',
        headers: {
          Authorization: `Bearer ${creds.apiToken}`,
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
  const creds = await resolveCloudflareCredentials(env);
  if (!creds) return { exists: false };

  const workerName = `maven-tenant-${tenantSlug}`;
  const response = await fetch(
    `${CF_API_BASE}/accounts/${creds.accountId}/workers/scripts/${workerName}`,
    {
      headers: { Authorization: `Bearer ${creds.apiToken}` },
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
