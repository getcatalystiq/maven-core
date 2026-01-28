/**
 * Tenant Agent Durable Object
 *
 * Routes chat requests to the agent sandbox via HTTP streaming.
 * Each tenant gets an isolated sandbox environment with dynamically injected skills.
 *
 * Uses Cloudflare Sandbox SDK for:
 * - Dynamic skill injection via writeFile()
 * - Environment configuration via startProcess()
 * - Config hash tracking for change detection
 * - HTTP streaming via containerFetch()
 *
 * For local development: Uses AGENT_URL to proxy to local agent
 * For production: Uses Cloudflare Sandbox SDK via Sandbox binding
 */

import { DurableObject } from 'cloudflare:workers';
import { getSandbox, type Sandbox } from '@cloudflare/sandbox';
import { getSecret } from '@maven/shared';
import type { Env } from '../index';

interface SandboxConfig {
  tenantId: string;
  userId: string;
  sessionId?: string;  // Session-scoped operations
  skills: Array<{ name: string; content?: string }>;
  connectors: Array<{ name: string; type: string; config: unknown }>;
}

interface LogEntry {
  ts: string;
  level: 'info' | 'warn' | 'error';
  msg: string;
  tenant?: string;
  session?: string;
  context?: Record<string, unknown>;
}

interface ProcessInfo {
  pid: number;
  running: boolean;
}

/**
 * Session directory metadata for tracking and cleanup
 */
interface SessionDirectoryMeta {
  path: string;
  createdAt: number;
  lastActivity: number;
}

/**
 * Session workspace base path in the sandbox
 */
const SESSIONS_BASE_PATH = '/home/maven/sessions';

/**
 * Compute session workspace path from session ID
 */
function getSessionWorkspacePath(sessionId: string): string {
  return `${SESSIONS_BASE_PATH}/${sessionId}`;
}

/**
 * Compute session skills path from session ID
 */
function getSessionSkillsPath(sessionId: string): string {
  return `${SESSIONS_BASE_PATH}/${sessionId}/.claude/skills`;
}

export class TenantAgent extends DurableObject<Env> {
  private sandbox: Sandbox | null = null;
  private configHash: string | null = null;
  private agentProcess: ProcessInfo | null = null;
  private cachedConfig: SandboxConfig | null = null;
  private configCacheTime: number = 0;
  private static readonly CONFIG_CACHE_TTL_MS = 60000; // 60 seconds

  // Session directory management
  private static readonly MAX_SESSION_DIRS = 50;
  private static readonly SESSION_IDLE_TIMEOUT_MS = 30 * 60 * 1000; // 30 minutes

  // Log buffering
  private logBuffer: LogEntry[] = [];
  private lastLogOffset: number = 0; // Track how many log lines we've already read
  private static readonly LOG_BUFFER_MAX = 100;
  private static readonly LOG_FLUSH_INTERVAL_MS = 10000; // 10 seconds
  private static readonly LOG_RETENTION_DAYS = 7;
  private static readonly AGENT_LOG_FILE = '/tmp/agent.log';

  /**
   * Validate session ID format to prevent path traversal attacks
   * Only allows alphanumeric characters and hyphens, max 64 chars
   */
  private isValidSessionId(sessionId: string): boolean {
    return /^[a-zA-Z0-9-]{1,64}$/.test(sessionId) &&
           !sessionId.includes('..') &&
           !sessionId.includes('/');
  }

  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);
  }

  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);

    // Extract user context from headers
    const userId = request.headers.get('X-User-Id');
    const tenantId = request.headers.get('X-Tenant-Id');

    if (!userId || !tenantId) {
      return this.jsonResponse({ error: 'Missing user context' }, 400);
    }

    // Store tenant ID for alarm access and update last activity
    await this.ctx.storage.put('tenantId', tenantId);
    await this.ctx.storage.put('lastActivity', Date.now());
    const alarmInterval = this.agentProcess?.running
      ? TenantAgent.LOG_FLUSH_INTERVAL_MS
      : 30 * 60 * 1000;
    await this.ctx.storage.setAlarm(Date.now() + alarmInterval);

    // Route requests
    // Debug endpoint to get agent logs
    if (url.pathname.endsWith('/debug/logs')) {
      return this.handleDebugLogs(tenantId);
    }

    if (url.pathname.endsWith('/chat/stream') || url.pathname.endsWith('/chat') || url.pathname.endsWith('/chat/invocations')) {
      // All chat endpoints use streaming - /chat is redirected to /chat/stream for performance
      return this.handleStreamChat(request, tenantId, userId);
    } else if (url.pathname.includes('/sessions')) {
      return this.handleSessions(request, tenantId, userId);
    }

    return this.jsonResponse({ error: 'Not found' }, 404);
  }

  /**
   * Ensure sandbox is ready with current configuration
   */
  private async ensureSandboxReady(tenantId: string, userId: string, sessionId: string, requestStart?: number): Promise<void> {
    const t0 = requestStart || Date.now();
    const t = () => Date.now() - t0;

    console.log(`[TIMING] T+${t()}ms: ensureSandboxReady started (session: ${sessionId})`);

    // Get or create sandbox instance
    if (!this.sandbox) {
      console.log(`[TIMING] T+${t()}ms: Creating new sandbox instance`);
      // Configure sandbox sleep timeout based on tier (TODO: fetch from tenant config)
      // Default: 10 minutes, Pro tier could use longer or keepAlive: true
      const sleepAfter = this.env.SANDBOX_SLEEP_AFTER || '10m';
      this.sandbox = getSandbox(this.env.Sandbox, `tenant-${tenantId}`, {
        sleepAfter,
      });
      console.log(`[TIMING] T+${t()}ms: Sandbox instance created (sleepAfter: ${sleepAfter})`);
    } else {
      console.log(`[TIMING] T+${t()}ms: Reusing existing sandbox instance`);
    }

    // FAST PATH: Use cached config if fresh and agent is running
    const now = Date.now();
    const cacheAge = now - this.configCacheTime;
    const cacheValid = this.cachedConfig && cacheAge < TenantAgent.CONFIG_CACHE_TTL_MS;

    let config: SandboxConfig;
    if (cacheValid) {
      // Trust cache even if agent state unknown - we'll detect stale config via hash
      // This saves 500-800ms on warm path when sandbox wakes from sleep
      console.log(`[TIMING] T+${t()}ms: Using cached config (age: ${cacheAge}ms) - FAST PATH`);
      config = this.cachedConfig!;
    } else {
      // Fetch configuration from Control Plane (cache stale or missing)
      console.log(`[TIMING] T+${t()}ms: Fetching config from Control Plane (cache stale/missing)`);
      config = await this.fetchSandboxConfig(tenantId, userId);
      this.cachedConfig = config;
      this.configCacheTime = now;
      console.log(`[TIMING] T+${t()}ms: Config fetched (${config.skills.length} skills, ${config.connectors.length} connectors)`);
    }

    // Include sessionId in hash since skills are now session-scoped
    const newHash = this.computeConfigHash(config) + `-session:${sessionId}`;

    // Only re-inject if configuration changed or new session
    if (this.configHash !== newHash) {
      console.log(`[TIMING] T+${t()}ms: Config changed or new session, injecting skills to session path`);
      await this.injectConfiguration(config, sessionId);
      this.configHash = newHash;
      console.log(`[TIMING] T+${t()}ms: Skills injected to session path`);
    } else {
      console.log(`[TIMING] T+${t()}ms: Config unchanged, updating session activity`);
      await this.updateSessionActivity(sessionId);
    }

    // Ensure agent is running
    console.log(`[TIMING] T+${t()}ms: Ensuring agent is running`);
    await this.ensureAgentRunning(config, sessionId, t0);
    console.log(`[TIMING] T+${t()}ms: Agent running confirmed`);
  }

  /**
   * Inject skills and configuration into the sandbox
   * Uses parallel writes to save 100-200ms with 3+ skills
   *
   * Skills are injected to per-session directories for isolation:
   * /home/maven/sessions/{sessionId}/.claude/skills/
   *
   * This enables native SDK skill loading via settingSources: ['project']
   * with the session workspace as cwd.
   */
  private async injectConfiguration(config: SandboxConfig, sessionId: string): Promise<void> {
    if (!this.sandbox) return;

    // Validate sessionId to prevent path traversal
    if (!this.isValidSessionId(sessionId)) {
      console.error(`[INJECT] Invalid sessionId format: ${sessionId}`);
      throw new Error('Invalid session ID');
    }

    // Session-scoped paths for skill isolation
    const sessionPath = getSessionWorkspacePath(sessionId);
    const sessionSkillsPath = getSessionSkillsPath(sessionId);
    const sessionConfigPath = `${sessionPath}/config`;

    console.log(`[INJECT] Using session-scoped path: ${sessionPath}`);

    // Create session directories in parallel
    await Promise.all([
      this.sandbox.mkdir(sessionSkillsPath, { recursive: true }),
      this.sandbox.mkdir(sessionConfigPath, { recursive: true }),
    ]);

    // Re-validate skill names before filesystem writes (defense in depth)
    const validSkills = config.skills.filter(skill => {
      if (!skill.content) return false;
      // Prevent path traversal in skill names
      if (skill.name.includes('..') || skill.name.includes('/')) {
        console.error(`[INJECT] Path traversal attempt in skill name: ${skill.name}`);
        return false;
      }
      return true;
    });

    // Write all skills to session-scoped location in parallel
    const skillWrites = validSkills.map(async (skill) => {
      const skillDir = `${sessionSkillsPath}/${skill.name}`;
      const skillPath = `${skillDir}/SKILL.md`;
      await this.sandbox!.mkdir(skillDir, { recursive: true });
      await this.sandbox!.writeFile(skillPath, skill.content!);
      console.log(`[INJECT] Injected skill to session path: ${skill.name}`);
    });

    // Write connectors configuration to session-scoped path
    const connectorWrite = this.sandbox.writeFile(
      `${sessionConfigPath}/connectors.json`,
      JSON.stringify(config.connectors, null, 2)
    ).then(() => {
      console.log(`[INJECT] Injected ${config.connectors.length} connectors to session path`);
    });

    // Create a minimal .claude directory with settings.json for SDK
    const claudeConfigPath = `${sessionPath}/.claude`;
    const settingsWrite = this.sandbox.writeFile(
      `${claudeConfigPath}/settings.json`,
      JSON.stringify({}, null, 2)
    ).then(() => {
      console.log(`[INJECT] Created ${claudeConfigPath}/settings.json`);
    });

    await Promise.all([...skillWrites, connectorWrite, settingsWrite]);

    // Track session directory for cleanup
    await this.trackSessionDirectory(sessionId);
  }

  /**
   * Track session directory in DO storage for cleanup
   */
  private async trackSessionDirectory(sessionId: string): Promise<void> {
    const now = Date.now();
    const meta: SessionDirectoryMeta = {
      path: getSessionWorkspacePath(sessionId),
      createdAt: now,
      lastActivity: now,
    };
    await this.ctx.storage.put(`session-dir:${sessionId}`, meta);

    // Evict oldest if limit reached
    await this.evictOldestSessionIfNeeded();
  }

  /**
   * Update session activity timestamp
   */
  private async updateSessionActivity(sessionId: string): Promise<void> {
    const meta = await this.ctx.storage.get<SessionDirectoryMeta>(`session-dir:${sessionId}`);
    if (meta) {
      meta.lastActivity = Date.now();
      await this.ctx.storage.put(`session-dir:${sessionId}`, meta);
    }
  }

  /**
   * Cleanup session directory with validation
   */
  private async cleanupSessionDirectory(sessionId: string): Promise<void> {
    // Validate sessionId to prevent path traversal
    if (!this.isValidSessionId(sessionId)) {
      console.warn(`[CLEANUP] Invalid sessionId format: ${sessionId}`);
      return;
    }

    if (!this.sandbox) {
      console.warn('[CLEANUP] No sandbox available for cleanup');
      return;
    }

    const sessionPath = getSessionWorkspacePath(sessionId);

    try {
      await this.sandbox.exec(`rm -rf "${sessionPath}"`);
      await this.ctx.storage.delete(`session-dir:${sessionId}`);
      console.log(`[CLEANUP] Removed session directory: ${sessionPath}`);
    } catch (error) {
      // Log but don't throw - cleanup should be best-effort
      console.error(`[CLEANUP] Failed to remove session directory: ${sessionPath}`, error);
    }
  }

  /**
   * LRU eviction when session directory limit reached
   */
  private async evictOldestSessionIfNeeded(): Promise<void> {
    const sessions = await this.ctx.storage.list<SessionDirectoryMeta>({ prefix: 'session-dir:' });

    if (sessions.size >= TenantAgent.MAX_SESSION_DIRS) {
      const sorted = [...sessions.entries()]
        .sort((a, b) => a[1].lastActivity - b[1].lastActivity);

      const oldest = sorted[0];
      if (oldest) {
        const sessionId = oldest[0].replace('session-dir:', '');
        console.log(`[CLEANUP] Evicting oldest session (LRU): ${sessionId}`);
        await this.cleanupSessionDirectory(sessionId);
      }
    }
  }

  /**
   * Cleanup idle sessions that haven't been active within timeout
   */
  private async cleanupIdleSessions(): Promise<void> {
    const sessions = await this.ctx.storage.list<SessionDirectoryMeta>({ prefix: 'session-dir:' });
    const now = Date.now();
    const cleanupPromises: Promise<void>[] = [];

    for (const [key, meta] of sessions) {
      const idleTime = now - meta.lastActivity;
      if (idleTime > TenantAgent.SESSION_IDLE_TIMEOUT_MS) {
        const sessionId = key.replace('session-dir:', '');
        console.log(`[CLEANUP] Session ${sessionId} idle for ${Math.round(idleTime / 1000)}s, cleaning up`);
        cleanupPromises.push(this.cleanupSessionDirectory(sessionId));
      }
    }

    if (cleanupPromises.length > 0) {
      await Promise.all(cleanupPromises);
      console.log(`[CLEANUP] Cleaned up ${cleanupPromises.length} idle sessions`);
    }
  }

  /**
   * Ensure the agent HTTP server is running in the sandbox
   *
   * Optimized: On warm path, skip health check and trust agentProcess flag.
   * If proxy fails later, caller will reset and retry.
   */
  private async ensureAgentRunning(config: SandboxConfig, sessionId: string, requestStart?: number): Promise<void> {
    const t0 = requestStart || Date.now();
    const t = () => Date.now() - t0;

    if (!this.sandbox) return;

    // FAST PATH: If we believe agent is running, skip health check
    // If it's actually dead, proxy will fail and caller will retry
    if (this.agentProcess?.running) {
      console.log(`[TIMING] T+${t()}ms: Agent flagged as running (FAST PATH - no health check)`);
      return;
    }

    // Check if something else is using port 8080 (handles DO state loss but sandbox kept running)
    // Use containerFetch instead of exec(curl) to save 200-400ms
    console.log(`[TIMING] T+${t()}ms: Checking if port 8080 has existing server`);
    try {
      const healthCheck = await this.sandbox.containerFetch(
        new Request('http://localhost:8080/health'),
        8080
      );
      if (healthCheck.ok) {
        const body = await healthCheck.json() as { status?: string };
        if (body.status === 'ok') {
          console.log(`[TIMING] T+${t()}ms: Port 8080 already has healthy server (FAST PATH)`);
          this.agentProcess = { pid: 0, running: true };
          return;
        }
      }
    } catch {
      // Server not running, continue to start
    }
    console.log(`[TIMING] T+${t()}ms: No existing server, need to start agent (COLD START)`);

    // Compute session workspace path for native skill loading
    const sessionPath = getSessionWorkspacePath(sessionId);

    // Build environment variables for the agent
    const env: Record<string, string> = {
      NODE_ENV: 'production', // Required: bind to 0.0.0.0 for container access
      HOME: '/home/maven', // Required: Claude CLI needs ~/.claude for session storage
      // PATH must include bun and node binaries
      PATH: '/home/maven/.bun/bin:/usr/local/bin:/usr/bin:/bin',
      TENANT_ID: config.tenantId,
      USER_ID: config.userId,
      // Session workspace path - SDK uses this as cwd with settingSources: ['project']
      // to discover skills from {SESSION_PATH}/.claude/skills/
      SESSION_PATH: sessionPath,
      // Legacy skills path (deprecated - kept for backward compatibility)
      SKILLS_PATH: getSessionSkillsPath(sessionId),
      CONNECTORS_CONFIG: JSON.stringify(config.connectors),
      PORT: '8080',
    };

    // Add API credentials from worker env
    if (this.env.ANTHROPIC_API_KEY) {
      env.ANTHROPIC_API_KEY = this.env.ANTHROPIC_API_KEY;
    }
    if (this.env.AWS_ACCESS_KEY_ID) {
      env.AWS_ACCESS_KEY_ID = this.env.AWS_ACCESS_KEY_ID;
      env.AWS_SECRET_ACCESS_KEY = this.env.AWS_SECRET_ACCESS_KEY || '';
      env.AWS_REGION = this.env.AWS_REGION || 'us-east-1';
      env.CLAUDE_CODE_USE_BEDROCK = '1';
      // Add session token if present (needed for temporary credentials)
      if (this.env.AWS_SESSION_TOKEN) {
        env.AWS_SESSION_TOKEN = this.env.AWS_SESSION_TOKEN;
      }
    }
    // Pass model override if configured
    if (this.env.ANTHROPIC_MODEL) {
      env.ANTHROPIC_MODEL = this.env.ANTHROPIC_MODEL;
    }

    // Start the agent server as a background process
    // Path matches Docker image: WORKDIR /app/packages/agent with build output in dist/
    console.log(`[TIMING] T+${t()}ms: Starting agent HTTP server (COLD START)`);


    // Log environment being passed (redact sensitive values)
    console.log('Agent environment:', JSON.stringify({
      NODE_ENV: env.NODE_ENV,
      TENANT_ID: env.TENANT_ID,
      PORT: env.PORT,
      AWS_ACCESS_KEY_ID: env.AWS_ACCESS_KEY_ID ? 'set' : 'not set',
      AWS_SECRET_ACCESS_KEY: env.AWS_SECRET_ACCESS_KEY ? 'set' : 'not set',
      AWS_REGION: env.AWS_REGION,
      CLAUDE_CODE_USE_BEDROCK: env.CLAUDE_CODE_USE_BEDROCK,
      ANTHROPIC_API_KEY: env.ANTHROPIC_API_KEY ? 'set' : 'not set',
    }));

    // Start with output redirection to log file for debugging
    // Use bash -c to ensure shell redirection works
    // Fall back to node if bun not available for debugging
    console.log(`[TIMING] T+${t()}ms: Calling startProcess`);
    const process = await this.sandbox.startProcess(
      'bash -c "which bun > /tmp/agent.log 2>&1 && bun /app/packages/agent/dist/index.js >> /tmp/agent.log 2>&1 || node /app/packages/agent/dist/index.js >> /tmp/agent.log 2>&1"',
      {
        cwd: '/app/packages/agent',
        env,
      }
    );
    console.log(`[TIMING] T+${t()}ms: startProcess returned, pid=${process.pid}`);

    this.agentProcess = {
      pid: process.pid ?? 0,
      running: true,
    };

    // Wait for the server to be ready (polls with short intervals instead of hardcoded wait)
    console.log(`[TIMING] T+${t()}ms: Waiting for agent to be ready`);
    await this.waitForServer();
    console.log(`[TIMING] T+${t()}ms: Agent HTTP server is ready`);

    // Schedule log flush alarm now that agent is running
    await this.ctx.storage.setAlarm(Date.now() + TenantAgent.LOG_FLUSH_INTERVAL_MS);
  }

  /**
   * Wait for the agent HTTP server to be ready
   * Uses containerFetch instead of exec(curl) to save 100-200ms per attempt
   * Uses short poll intervals (200ms) for faster startup detection
   */
  private async waitForServer(maxAttempts = 30, delayMs = 200): Promise<void> {
    if (!this.sandbox) return;

    const diagnostics: string[] = [];

    for (let attempt = 0; attempt < maxAttempts; attempt++) {
      try {
        // Use containerFetch for faster health checks (no process spawn overhead)
        const response = await this.sandbox.containerFetch(
          new Request('http://localhost:8080/health'),
          8080
        );
        if (response.ok) {
          const body = await response.json() as { status?: string };
          if (body.status === 'ok') {
            return;
          }
        }
      } catch (e) {
        diagnostics.push(`Attempt ${attempt + 1} error: ${e}`);
      }
      await new Promise((resolve) => setTimeout(resolve, delayMs));
    }

    // Collect diagnostic information before throwing
    const agentLog = await this.sandbox.exec('cat /tmp/agent.log 2>&1 | tail -30');
    const portCheck = await this.sandbox.exec('ss -tulpn 2>&1 || netstat -tulpn 2>&1');
    const curlVerbose = await this.sandbox.exec('curl -v http://127.0.0.1:8080/health 2>&1');
    const psCheck = await this.sandbox.exec('ps aux');

    const diagInfo = [
      `Agent log: ${agentLog.stdout || agentLog.stderr || 'empty'}`,
      `Ports: ${portCheck.stdout || portCheck.stderr || 'none'}`,
      `Curl verbose: ${curlVerbose.stdout || curlVerbose.stderr || 'none'}`,
      `Processes: ${psCheck.stdout || psCheck.stderr || 'none'}`,
      ...diagnostics,
    ].join('\n\n');

    throw new Error(`Agent server failed to start. Diagnostics:\n${diagInfo}`);
  }

  /**
   * Compute a hash of the configuration for change detection
   */
  private computeConfigHash(config: SandboxConfig): string {
    const content = JSON.stringify({
      skills: config.skills.map((s) => ({ name: s.name, content: s.content })),
      connectors: config.connectors,
    });
    // Simple hash using string operations (crypto.subtle not needed for change detection)
    let hash = 0;
    for (let i = 0; i < content.length; i++) {
      const char = content.charCodeAt(i);
      hash = (hash << 5) - hash + char;
      hash = hash & hash; // Convert to 32-bit integer
    }
    return hash.toString(16);
  }

  /**
   * Handle streaming chat request with retry logic
   *
   * Uses containerFetch with HTTP streaming for real-time NDJSON streaming.
   * The agent's /chat/stream endpoint returns a streaming Response body.
   * Retries up to 3 times with increasing delays to handle sandbox sleep/wake cycles.
   */
  private async handleStreamChat(
    request: Request,
    tenantId: string,
    userId: string
  ): Promise<Response> {
    const requestStart = parseInt(request.headers.get('X-Request-Start') || '0') || Date.now();
    const t = () => Date.now() - requestStart;
    const maxRetries = 3;
    const retryDelays = [1000, 3000, 8000]; // Accommodate cold starts

    console.log(`[TIMING] T+${t()}ms: DO handleStreamChat started`);

    // Local dev mode: proxy to local agent (no retry needed)
    if (this.env.AGENT_URL) {
      return this.proxyToAgent(request, '/chat/stream');
    }

    // Parse body once before retry loop
    let body: { message: string; sessionId?: string };
    try {
      body = (await request.json()) as { message: string; sessionId?: string };
    } catch {
      return this.jsonResponse({ error: 'Invalid request body' }, 400);
    }
    const sessionId = body.sessionId || crypto.randomUUID();
    console.log(`[TIMING] T+${t()}ms: Request body parsed`);

    for (let attempt = 0; attempt < maxRetries; attempt++) {
      try {
        // Ensure sandbox is ready with session-scoped skills
        await this.ensureSandboxReady(tenantId, userId, sessionId, requestStart);
        console.log(`[TIMING] T+${t()}ms: Sandbox ready for streaming (attempt ${attempt + 1}, session: ${sessionId})`);

        if (!this.sandbox) {
          throw new Error('Sandbox not initialized');
        }

        // Build request safely - no shell escaping needed
        // Include sessionPath so agent knows where to find skills
        const sessionPath = getSessionWorkspacePath(sessionId);
        const payload = JSON.stringify({
          message: body.message,
          sessionId,
          sessionPath, // Agent uses this as cwd for native skill loading
        });

        const agentRequest = new Request('http://localhost:8080/chat/stream', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Tenant-Id': tenantId,
            'X-User-Id': userId,
          },
          body: payload,
        });

        console.log(`[TIMING] T+${t()}ms: Making containerFetch request to agent`);

        const response = await this.sandbox.containerFetch(agentRequest, 8080);
        console.log(`[TIMING] T+${t()}ms: containerFetch returned, status: ${response.status}`);

        if (!response.ok) {
          const errorText = await response.text();
          console.error(`[TIMING] T+${t()}ms: Agent returned error:`, errorText);
          throw new Error(`Agent request failed: ${response.status} - ${errorText}`);
        }

        if (!response.body) {
          throw new Error('Agent returned no response body');
        }

        console.log(`[TIMING] T+${t()}ms: Stream started successfully (attempt ${attempt + 1})`);

        // Diagnostic: Wrap body in TransformStream to log chunk arrival times
        let chunkCount = 0;
        let totalBytes = 0;
        const { readable, writable } = new TransformStream({
          transform(chunk, controller) {
            chunkCount++;
            totalBytes += chunk.length;
            console.log(`[DIAG] T+${t()}ms: Chunk #${chunkCount} received: ${chunk.length} bytes (total: ${totalBytes})`);
            controller.enqueue(chunk);
          },
          flush() {
            console.log(`[DIAG] T+${t()}ms: Stream complete. ${chunkCount} chunks, ${totalBytes} bytes total`);
          }
        });

        // Pipe container response to transform stream
        response.body.pipeTo(writable).catch((error) => {
          console.error(`[DIAG] T+${t()}ms: pipeTo error:`, error);
        });

        // Return the transformed readable stream
        return new Response(readable, {
          headers: {
            'Content-Type': 'application/x-ndjson',
            'Cache-Control': 'no-cache, no-transform',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no',
            'Content-Encoding': 'identity',
            'Transfer-Encoding': 'chunked',
          },
        });

      } catch (error) {
        console.error(`[TIMING] T+${t()}ms: Stream attempt ${attempt + 1} failed:`, error);

        // Collect diagnostics on failure
        if (this.sandbox) {
          try {
            const agentLog = await this.sandbox.exec('cat /tmp/agent.log 2>&1 | tail -30');
            const psCheck = await this.sandbox.exec('ps aux 2>&1');
            console.error('Stream request diagnostics:', [
              `Error: ${(error as Error).message}`,
              `Agent log: ${agentLog.stdout || agentLog.stderr || 'empty'}`,
              `Processes: ${psCheck.stdout || psCheck.stderr || 'none'}`,
            ].join('\n---\n'));
          } catch {
            // Diagnostics collection failed, continue
          }
        }

        // Reset agent state so next attempt triggers fresh startup
        this.agentProcess = null;

        if (attempt < maxRetries - 1) {
          console.log(`[TIMING] T+${t()}ms: Retrying in ${retryDelays[attempt]}ms...`);
          await new Promise(r => setTimeout(r, retryDelays[attempt]));
          continue;
        }

        // All retries exhausted
        return this.jsonResponse(
          { error: 'Stream processing failed', message: (error as Error).message },
          500
        );
      }
    }

    // TypeScript unreachable
    throw new Error('Unreachable');
  }

  /**
   * Proxy request to local agent (for development)
   */
  private async proxyToAgent(request: Request, path: string): Promise<Response> {
    const agentUrl = this.env.AGENT_URL;
    if (!agentUrl) {
      throw new Error('AGENT_URL not configured');
    }

    const url = new URL(path, agentUrl);
    const proxyRequest = new Request(url.toString(), {
      method: request.method,
      headers: request.headers,
      body: request.body,
    });

    try {
      const response = await fetch(proxyRequest);

      // For streaming responses, we need to pipe the body through
      // to ensure proper streaming to the client
      if (response.body) {
        const { readable, writable } = new TransformStream();
        response.body.pipeTo(writable).catch((error) => {
          console.error('Stream pipe failed:', error);
          try {
            writable.abort(error);
          } catch {
            // Already closed, ignore
          }
        });

        return new Response(readable, {
          status: response.status,
          statusText: response.statusText,
          headers: response.headers,
        });
      }

      return response;
    } catch (error) {
      console.error('Agent proxy error:', error);
      throw new Error(`Failed to connect to agent at ${agentUrl}: ${(error as Error).message}`);
    }
  }

  /**
   * Handle session listing
   */
  private async handleSessions(
    _request: Request,
    _tenantId: string,
    userId: string
  ): Promise<Response> {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const sessions = await this.ctx.storage.list<any>({ prefix: `session:${userId}:` });

    return this.jsonResponse({
      sessions: Array.from(sessions.entries()).map(([key, value]) => ({
        id: key.replace(`session:${userId}:`, ''),
        ...value,
      })),
    });
  }

  /**
   * Handle debug logs request - returns last 100 lines of agent logs
   */
  private async handleDebugLogs(_tenantId: string): Promise<Response> {
    if (!this.sandbox) {
      return this.jsonResponse({ error: 'No sandbox available', logs: null });
    }

    try {
      const result = await this.sandbox.exec(
        `cat ${TenantAgent.AGENT_LOG_FILE} 2>&1 | tail -100`
      );
      return this.jsonResponse({
        logs: result.stdout || '',
        stderr: result.stderr || '',
        success: result.success,
        logOffset: this.lastLogOffset,
        bufferedLogs: this.logBuffer.length,
      });
    } catch (error) {
      return this.jsonResponse({
        error: error instanceof Error ? error.message : 'Unknown error',
        logs: null,
      });
    }
  }

  /**
   * Pull logs from the agent container's log file (pull model)
   *
   * Reads new lines from /tmp/agent.log since last read.
   * Parses each line and adds to buffer.
   */
  private async pullLogsFromContainer(tenantId: string): Promise<void> {
    if (!this.sandbox) {
      console.log('[PullLogs] No sandbox available');
      return;
    }

    try {
      // First check if the log file exists and get its size
      const fileCheck = await this.sandbox.exec(
        `wc -l ${TenantAgent.AGENT_LOG_FILE} 2>/dev/null || echo "0"`
      );
      const totalLines = parseInt(fileCheck.stdout?.trim().split(' ')[0] || '0', 10);
      console.log(`[PullLogs] Log file has ${totalLines} lines, offset: ${this.lastLogOffset}`);

      if (totalLines <= this.lastLogOffset) {
        console.log('[PullLogs] No new lines to read');
        return;
      }

      // Use tail with line offset to get only new lines
      // The agent writes structured output prefixed with [TIMING], [WS], etc.
      const result = await this.sandbox.exec(
        `tail -n +${this.lastLogOffset + 1} ${TenantAgent.AGENT_LOG_FILE} 2>/dev/null | head -200`
      );

      if (!result.stdout) {
        console.log('[PullLogs] No stdout from tail command');
        return;
      }

      const lines = result.stdout.split('\n').filter((line) => line.trim());
      if (lines.length === 0) {
        console.log('[PullLogs] No non-empty lines found');
        return;
      }

      console.log(`[PullLogs] Read ${lines.length} new log lines`);

      // Update offset
      this.lastLogOffset += lines.length;

      // Parse log lines into structured entries
      // Agent writes JSON lines with timestamps, parse them to preserve timing
      for (const line of lines) {
        try {
          // Try to parse as JSON (agent structured log)
          const parsed = JSON.parse(line) as LogEntry;
          if (parsed.ts && parsed.msg) {
            // Valid structured log entry - preserve its timestamp
            parsed.tenant = parsed.tenant || tenantId;
            this.logBuffer.push(parsed);
            continue;
          }
        } catch {
          // Not JSON, fall through to plain text handling
        }

        // Plain text fallback - detect level from content
        let level: 'info' | 'warn' | 'error' = 'info';
        if (line.toLowerCase().includes('error') || line.toLowerCase().includes('fail')) {
          level = 'error';
        } else if (line.toLowerCase().includes('warn')) {
          level = 'warn';
        }

        const entry: LogEntry = {
          ts: new Date().toISOString(),
          level,
          msg: line,
          tenant: tenantId,
        };

        this.logBuffer.push(entry);
      }

      console.log(`[PullLogs] Buffer now has ${this.logBuffer.length} entries`);

      // Flush if buffer is full
      if (this.logBuffer.length >= TenantAgent.LOG_BUFFER_MAX) {
        console.log('[PullLogs] Buffer full, flushing');
        await this.flushLogs(tenantId);
      }
    } catch (error) {
      // Container may not be running, log error for debugging
      console.log('[PullLogs] Failed to pull logs from container:', error);
    }
  }

  /**
   * Flush buffered logs to R2
   *
   * Writes logs as NDJSON files organized by tenant and date:
   * logs/{tenantId}/{date}/{timestamp}.ndjson
   */
  private async flushLogs(tenantId: string): Promise<void> {
    if (this.logBuffer.length === 0) {
      return;
    }

    // Check if LOGS binding is available
    if (!this.env.LOGS) {
      console.warn('LOGS R2 binding not available, discarding logs');
      this.logBuffer = [];
      return;
    }

    const entries = this.logBuffer;
    this.logBuffer = [];

    // Build NDJSON content
    const ndjson = entries.map((e) => JSON.stringify(e)).join('\n') + '\n';

    // Generate path: logs/{tenantId}/{date}/{timestamp}.ndjson
    const now = new Date();
    const date = now.toISOString().split('T')[0]; // YYYY-MM-DD
    const timestamp = now.getTime();
    const path = `logs/${tenantId}/${date}/${timestamp}.ndjson`;

    try {
      await this.env.LOGS.put(path, ndjson, {
        httpMetadata: {
          contentType: 'application/x-ndjson',
        },
        customMetadata: {
          tenantId,
          entryCount: entries.length.toString(),
        },
      });
      console.log(`Flushed ${entries.length} log entries to ${path}`);
    } catch (error) {
      console.error('Failed to write logs to R2:', error);
      // Logs are lost at this point - we can't buffer indefinitely
    }
  }

  /**
   * Cleanup old logs (7 day retention)
   */
  private async cleanupOldLogs(tenantId: string): Promise<void> {
    if (!this.env.LOGS) {
      return;
    }

    const cutoffDate = new Date();
    cutoffDate.setDate(cutoffDate.getDate() - TenantAgent.LOG_RETENTION_DAYS);

    try {
      // List log files for this tenant
      const prefix = `logs/${tenantId}/`;
      const listed = await this.env.LOGS.list({ prefix, limit: 1000 });

      const deletePromises: Promise<void>[] = [];
      for (const obj of listed.objects) {
        // Extract date from path: logs/{tenantId}/{date}/{timestamp}.ndjson
        const parts = obj.key.split('/');
        if (parts.length >= 3) {
          const dateStr = parts[2];
          const logDate = new Date(dateStr);
          if (logDate < cutoffDate) {
            deletePromises.push(this.env.LOGS.delete(obj.key));
          }
        }
      }

      if (deletePromises.length > 0) {
        await Promise.all(deletePromises);
        console.log(`Deleted ${deletePromises.length} old log files for tenant ${tenantId}`);
      }
    } catch (error) {
      console.error('Failed to cleanup old logs:', error);
    }
  }

  /**
   * Fetch sandbox configuration from Control Plane internal API
   */
  private async fetchSandboxConfig(tenantId: string, userId: string): Promise<SandboxConfig> {
    const defaultConfig: SandboxConfig = {
      tenantId,
      userId,
      skills: [],
      connectors: [],
    };

    // Fetch from Control Plane's internal API
    if (this.env.CONTROL_PLANE_URL && this.env.INTERNAL_API_KEY) {
      try {
        const internalKey = await getSecret(this.env.INTERNAL_API_KEY);

        // Fetch basic config
        const configResponse = await fetch(
          `${this.env.CONTROL_PLANE_URL}/internal/config/${tenantId}/${userId}`,
          {
            headers: {
              'X-Internal-Key': internalKey,
            },
          }
        );

        if (!configResponse.ok) {
          console.error('Failed to fetch sandbox config:', await configResponse.text());
          return defaultConfig;
        }

        const config = (await configResponse.json()) as {
          skills: Array<{ name: string }>;
          connectors: Array<{ name: string; type: string; config: unknown }>;
        };

        // Fetch skill content for each skill
        const skillsWithContent = await Promise.all(
          config.skills.map(async (skill) => {
            const content = await this.fetchSkillContent(tenantId, skill.name);
            return { name: skill.name, content };
          })
        );

        return {
          tenantId,
          userId,
          skills: skillsWithContent,
          connectors: config.connectors || [],
        };
      } catch (error) {
        console.error('Failed to fetch sandbox config from Control Plane:', error);
      }
    }

    return defaultConfig;
  }

  /**
   * Fetch skill content from Control Plane
   */
  private async fetchSkillContent(tenantId: string, skillName: string): Promise<string | undefined> {
    if (!this.env.CONTROL_PLANE_URL || !this.env.INTERNAL_API_KEY) {
      return undefined;
    }

    try {
      const internalKey = await getSecret(this.env.INTERNAL_API_KEY);
      const response = await fetch(
        `${this.env.CONTROL_PLANE_URL}/internal/skills/${tenantId}/${skillName}/SKILL.md`,
        {
          headers: {
            'X-Internal-Key': internalKey,
          },
        }
      );

      if (response.ok) {
        return await response.text();
      }
    } catch (error) {
      console.error(`Failed to fetch skill content for ${skillName}:`, error);
    }

    return undefined;
  }

  /**
   * Cleanup idle sandbox and flush logs
   */
  async alarm(): Promise<void> {
    console.log('[Alarm] Starting alarm handler');

    const lastActivity = (await this.ctx.storage.get<number>('lastActivity')) || 0;
    const idleTime = Date.now() - lastActivity;
    const idleThreshold = 30 * 60 * 1000; // 30 minutes

    // Extract tenant ID from DO name
    // The DO ID is a hex string, but we stored the tenant ID in storage during fetch
    // Fall back to DO ID if not found
    let tenantId = await this.ctx.storage.get<string>('tenantId');
    if (!tenantId) {
      // Try to extract from the DO name pattern
      const doId = this.ctx.id.toString();
      tenantId = doId.startsWith('tenant-') ? doId.substring(7) : doId;
      console.log(`[Alarm] No stored tenantId, extracted from DO ID: ${tenantId}`);
    }

    console.log(`[Alarm] Tenant: ${tenantId}, idleTime: ${idleTime}ms, hasBufferedLogs: ${this.logBuffer.length}`);

    // Reconnect to sandbox if we lost the reference (DO evicted and rehydrated)
    // This is needed because in-memory state doesn't persist across DO evictions
    if (!this.sandbox) {
      const sleepAfter = this.env.SANDBOX_SLEEP_AFTER || '10m';
      this.sandbox = getSandbox(this.env.Sandbox, `tenant-${tenantId}`, {
        sleepAfter,
      });
      console.log('[Alarm] Reconnected to sandbox for log pull');
    }

    // Try to pull logs from container (will silently fail if container not running)
    await this.pullLogsFromContainer(tenantId);

    // Flush any pending logs to R2
    if (this.logBuffer.length > 0) {
      await this.flushLogs(tenantId);
    }

    // Cleanup idle session directories
    await this.cleanupIdleSessions();

    if (idleTime > idleThreshold) {
      console.log(`Cleaning up idle sandbox for tenant DO: ${this.ctx.id.toString()}`);

      // Final log pull before destroying
      await this.pullLogsFromContainer(tenantId);
      if (this.logBuffer.length > 0) {
        await this.flushLogs(tenantId);
      }

      // Destroy the sandbox to free resources
      if (this.sandbox) {
        await this.sandbox.destroy();
      }
      this.sandbox = null;
      this.configHash = null;
      this.agentProcess = null;
      this.lastLogOffset = 0; // Reset log offset for next sandbox

      // Run log cleanup on idle (once per day is sufficient)
      await this.cleanupOldLogs(tenantId);
    } else {
      // Schedule next alarm - always use log flush interval when we have activity
      // since we need to pull logs periodically
      const nextAlarm = idleTime < 5 * 60 * 1000  // Last activity within 5 minutes
        ? TenantAgent.LOG_FLUSH_INTERVAL_MS
        : idleThreshold - idleTime + 1000; // Wake up when idle threshold reached
      await this.ctx.storage.setAlarm(Date.now() + nextAlarm);
      console.log(`[Alarm] Scheduled next alarm in ${nextAlarm}ms (idle: ${idleTime}ms)`);
    }
  }

  private jsonResponse(data: unknown, status = 200): Response {
    return new Response(JSON.stringify(data), {
      status,
      headers: { 'Content-Type': 'application/json' },
    });
  }
}
