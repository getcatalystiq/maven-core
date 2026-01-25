/**
 * Tenant Agent Durable Object
 *
 * Routes chat requests to the agent sandbox via HTTP.
 * Each tenant gets an isolated sandbox environment with dynamically injected skills.
 *
 * Uses Cloudflare Sandbox SDK for:
 * - Dynamic skill injection via writeFile()
 * - Environment configuration via startProcess()
 * - Config hash tracking for change detection
 *
 * For local development: Uses AGENT_URL to proxy to local agent
 * For production: Uses Cloudflare Sandbox SDK via Sandbox binding
 */

import { DurableObject } from 'cloudflare:workers';
import { getSandbox, type Sandbox } from '@cloudflare/sandbox';
import type { Env } from '../index';

interface SandboxConfig {
  tenantId: string;
  userId: string;
  skills: Array<{ name: string; content?: string }>;
  connectors: Array<{ name: string; type: string; config: unknown }>;
}

interface ProcessInfo {
  pid: number;
  running: boolean;
}

export class TenantAgent extends DurableObject<Env> {
  private sandbox: Sandbox | null = null;
  private configHash: string | null = null;
  private agentProcess: ProcessInfo | null = null;

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

    // Update last activity and set alarm for idle cleanup (30 minutes)
    await this.ctx.storage.put('lastActivity', Date.now());
    await this.ctx.storage.setAlarm(Date.now() + 30 * 60 * 1000);

    // Route requests
    if (url.pathname.endsWith('/chat/stream')) {
      return this.handleStreamChat(request, tenantId, userId);
    } else if (url.pathname.endsWith('/chat') || url.pathname.endsWith('/chat/invocations')) {
      return this.handleChat(request, tenantId, userId);
    } else if (url.pathname.includes('/sessions')) {
      return this.handleSessions(request, tenantId, userId);
    }

    return this.jsonResponse({ error: 'Not found' }, 404);
  }

  /**
   * Ensure sandbox is ready with current configuration
   */
  private async ensureSandboxReady(tenantId: string, userId: string): Promise<void> {
    // Get or create sandbox instance
    if (!this.sandbox) {
      this.sandbox = getSandbox(this.env.Sandbox, `tenant-${tenantId}`);
    }

    // Fetch configuration from Control Plane
    const config = await this.fetchSandboxConfig(tenantId, userId);
    const newHash = this.computeConfigHash(config);

    // Only re-inject if configuration changed
    if (this.configHash !== newHash) {
      console.log(`Configuration changed for tenant ${tenantId}, re-injecting...`);
      await this.injectConfiguration(config);
      this.configHash = newHash;
    }

    // Ensure agent is running
    await this.ensureAgentRunning(config);
  }

  /**
   * Inject skills and configuration into the sandbox
   */
  private async injectConfiguration(config: SandboxConfig): Promise<void> {
    if (!this.sandbox) return;

    // Create skills directory if needed
    await this.sandbox.mkdir('/app/skills', { recursive: true });

    // Write each skill to the sandbox filesystem
    for (const skill of config.skills) {
      if (skill.content) {
        const skillPath = `/app/skills/${skill.name}/SKILL.md`;
        await this.sandbox.mkdir(`/app/skills/${skill.name}`, { recursive: true });
        await this.sandbox.writeFile(skillPath, skill.content);
        console.log(`Injected skill: ${skill.name}`);
      }
    }

    // Write connectors configuration
    await this.sandbox.mkdir('/app/config', { recursive: true });
    await this.sandbox.writeFile(
      '/app/config/connectors.json',
      JSON.stringify(config.connectors, null, 2)
    );
    console.log(`Injected ${config.connectors.length} connectors`);
  }


  /**
   * Ensure the agent HTTP server is running in the sandbox
   */
  private async ensureAgentRunning(config: SandboxConfig): Promise<void> {
    if (!this.sandbox) return;

    // Claude CLI tests are no longer needed - the issue was running as root
    // The container now runs as the 'maven' user which allows --dangerously-skip-permissions

    // Check if agent process is already running
    if (this.agentProcess?.running) {
      // Verify the process is actually still running by checking the port
      const portInUse = await this.sandbox.exec('curl -s http://localhost:8080/health');
      if (portInUse.success && portInUse.stdout.includes('ok')) {
        console.log('Agent process already running, verified via health check');
        return;
      }
      // Process flag says running but health check failed - reset
      console.log('Agent process flag was set but health check failed, resetting');
      this.agentProcess = null;
    }

    // Check if something else is using port 8080
    const existingPort = await this.sandbox.exec('curl -s http://localhost:8080/health');
    if (existingPort.success && existingPort.stdout.includes('ok')) {
      console.log('Port 8080 already has a healthy server, reusing');
      this.agentProcess = { pid: 0, running: true };
      return;
    }

    // Build environment variables for the agent
    const env: Record<string, string> = {
      NODE_ENV: 'production', // Required: bind to 0.0.0.0 for container access
      TENANT_ID: config.tenantId,
      USER_ID: config.userId,
      SKILLS_PATH: '/app/skills',
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

    // Start the agent server as a background process
    // Path matches Docker image: WORKDIR /app/packages/agent with build output in dist/
    console.log('Starting agent HTTP server...');

    // Check if the dist file exists before starting
    const checkFile = await this.sandbox.exec('ls -la /app/packages/agent/dist/index.js');
    console.log(`Agent file check: ${checkFile.success ? checkFile.stdout : 'FILE NOT FOUND: ' + checkFile.stderr}`);

    // Check Claude CLI installation
    const claudeCheck = await this.sandbox.exec('which claude && claude --version 2>&1');
    console.log(`Claude CLI check: ${claudeCheck.success ? claudeCheck.stdout : 'NOT FOUND: ' + claudeCheck.stderr}`);


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
    const process = await this.sandbox.startProcess(
      'bash -c "node /app/packages/agent/dist/index.js > /tmp/agent.log 2>&1"',
      {
        cwd: '/app/packages/agent',
        env,
      }
    );

    this.agentProcess = {
      pid: process.pid ?? 0,
      running: true,
    };

    // Wait a moment for process to start writing logs
    await new Promise((resolve) => setTimeout(resolve, 3000));

    // Check agent log for startup errors
    const logCheck = await this.sandbox.exec('cat /tmp/agent.log 2>&1 | head -50');
    console.log(`Agent startup log (first 50 lines): ${JSON.stringify(logCheck.stdout || logCheck.stderr || 'empty')}`);

    // Check what ports are listening
    const portCheck = await this.sandbox.exec('ss -tulpn 2>&1 || netstat -tulpn 2>&1 || echo "no network tools"');
    console.log(`Listening ports: ${JSON.stringify(portCheck.stdout || portCheck.stderr || 'none')}`);

    // Check if localhost resolves
    const localhostCheck = await this.sandbox.exec('curl -v http://127.0.0.1:8080/health 2>&1');
    console.log(`Curl to 127.0.0.1: ${JSON.stringify(localhostCheck.stdout || localhostCheck.stderr || 'none')}`);

    // Wait for the server to be ready
    await this.waitForServer();
    console.log('Agent HTTP server is ready');
  }

  /**
   * Wait for the agent HTTP server to be ready
   */
  private async waitForServer(maxAttempts = 15, delayMs = 1000): Promise<void> {
    if (!this.sandbox) return;

    const diagnostics: string[] = [];

    for (let attempt = 0; attempt < maxAttempts; attempt++) {
      try {
        // Then check health endpoint
        const result = await this.sandbox.exec('curl -s http://localhost:8080/health');

        if (result.success && result.stdout.includes('ok')) {
          return;
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
   * Proxy HTTP request to sandbox agent
   */
  private async proxyToSandbox(
    path: string,
    tenantId: string,
    userId: string,
    body: unknown
  ): Promise<Response> {
    if (!this.sandbox) {
      throw new Error('Sandbox not initialized');
    }

    // Use exec with curl to make HTTP request to the agent
    // This is reliable across all sandbox environments
    const bodyJson = JSON.stringify(body);
    const escapedBody = bodyJson.replace(/'/g, "'\\''");

    const result = await this.sandbox.exec(
      `curl -s -X POST http://localhost:8080${path} ` +
        `-H 'Content-Type: application/json' ` +
        `-H 'X-Tenant-Id: ${tenantId}' ` +
        `-H 'X-User-Id: ${userId}' ` +
        `-d '${escapedBody}'`
    );

    if (!result.success) {
      // Collect diagnostics when request fails
      const agentLog = await this.sandbox.exec('cat /tmp/agent.log 2>&1 | tail -50');
      const psCheck = await this.sandbox.exec('ps aux 2>&1');
      const portCheck = await this.sandbox.exec('ss -tulpn 2>&1 || netstat -tulpn 2>&1');

      const diagnostics = [
        `Curl stderr: ${result.stderr || 'empty'}`,
        `Curl stdout: ${result.stdout || 'empty'}`,
        `Agent log: ${agentLog.stdout || agentLog.stderr || 'empty'}`,
        `Processes: ${psCheck.stdout || psCheck.stderr || 'none'}`,
        `Ports: ${portCheck.stdout || portCheck.stderr || 'none'}`,
      ].join('\n---\n');

      console.error('Proxy request diagnostics:', diagnostics);
      throw new Error(`Agent request failed. Diagnostics:\n${diagnostics}`);
    }

    return new Response(result.stdout, {
      headers: { 'Content-Type': 'application/json' },
    });
  }

  /**
   * Handle non-streaming chat request
   */
  private async handleChat(
    request: Request,
    tenantId: string,
    userId: string
  ): Promise<Response> {
    try {
      // Local dev mode: proxy to local agent
      if (this.env.AGENT_URL) {
        return this.proxyToAgent(request, '/chat');
      }

      const body = (await request.json()) as { message: string; sessionId?: string };
      const sessionId = body.sessionId || crypto.randomUUID();

      // Ensure sandbox is ready with current config
      await this.ensureSandboxReady(tenantId, userId);

      // Proxy request to agent in sandbox
      const agentResponse = await this.proxyToSandbox(
        '/chat',
        tenantId,
        userId,
        {
          message: body.message,
          sessionId,
        }
      );

      if (!agentResponse.ok) {
        const errorText = await agentResponse.text();
        console.error('Agent request failed:', errorText);
        return this.jsonResponse(
          {
            error: 'Agent execution failed',
            details: errorText,
            sessionId,
          },
          500
        );
      }

      const response = (await agentResponse.json()) as {
        text?: string;
        response?: string;
        error?: string;
        usage?: { inputTokens: number; outputTokens: number };
      };

      // If agent returned an error, include diagnostics for debugging
      if (response.error) {
        const agentLog = await this.sandbox!.exec('cat /tmp/agent.log 2>&1 | tail -50');
        return this.jsonResponse({
          response: response,
          sessionId,
          usage: response.usage || { inputTokens: 0, outputTokens: 0 },
          diagnostics: {
            agentLog: agentLog.stdout || agentLog.stderr || 'empty',
          },
        });
      }

      // Store session
      await this.ctx.storage.put(`session:${userId}:${sessionId}`, {
        id: sessionId,
        lastMessage: body.message,
        lastResponse: response,
        updatedAt: Date.now(),
      });

      return this.jsonResponse({
        response: response.text || response.response || response,
        sessionId,
        usage: response.usage || { inputTokens: 0, outputTokens: 0 },
      });
    } catch (error) {
      console.error('Chat error:', error);
      return this.jsonResponse(
        { error: 'Chat processing failed', message: (error as Error).message },
        500
      );
    }
  }

  /**
   * Handle streaming chat request
   * Uses Streamable HTTP (NDJSON) per MCP 2025 spec
   */
  private async handleStreamChat(
    request: Request,
    tenantId: string,
    userId: string
  ): Promise<Response> {
    try {
      // Local dev mode: proxy to local agent
      if (this.env.AGENT_URL) {
        return this.proxyToAgent(request, '/chat/stream');
      }

      const body = (await request.json()) as { message: string; sessionId?: string };
      const sessionId = body.sessionId || crypto.randomUUID();

      // Ensure sandbox is ready
      await this.ensureSandboxReady(tenantId, userId);

      // For streaming, we need to use a different approach
      // Start a streaming exec command that pipes output
      if (!this.sandbox) {
        throw new Error('Sandbox not initialized');
      }

      const bodyJson = JSON.stringify({
        message: body.message,
        sessionId,
      });
      const escapedBody = bodyJson.replace(/'/g, "'\\''");

      // Create a readable stream that pipes the curl output
      const { readable, writable } = new TransformStream();
      const writer = writable.getWriter();

      // Execute streaming request in background
      (async () => {
        try {
          const result = await this.sandbox!.exec(
            `curl -s -N -X POST http://localhost:8080/chat/stream ` +
              `-H 'Content-Type: application/json' ` +
              `-H 'X-Tenant-Id: ${tenantId}' ` +
              `-H 'X-User-Id: ${userId}' ` +
              `-d '${escapedBody}'`,
            { stream: true, onOutput: (chunk) => writer.write(new TextEncoder().encode(chunk)) }
          );

          if (!result.success) {
            console.error('Stream request failed:', result.stderr);
          }
        } catch (error) {
          console.error('Stream error:', error);
        } finally {
          await writer.close();
        }
      })();

      return new Response(readable, {
        headers: {
          'Content-Type': 'application/x-ndjson',
          'Cache-Control': 'no-cache',
          'Transfer-Encoding': 'chunked',
        },
      });
    } catch (error) {
      console.error('Stream chat error:', error);
      return this.jsonResponse(
        { error: 'Stream processing failed', message: (error as Error).message },
        500
      );
    }
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
        response.body.pipeTo(writable);

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
        // Fetch basic config
        const configResponse = await fetch(
          `${this.env.CONTROL_PLANE_URL}/internal/sandbox-config?tenantId=${tenantId}&userId=${userId}`,
          {
            headers: {
              'X-Internal-Key': this.env.INTERNAL_API_KEY,
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
      const response = await fetch(
        `${this.env.CONTROL_PLANE_URL}/internal/skills/${skillName}/content?tenantId=${tenantId}`,
        {
          headers: {
            'X-Internal-Key': this.env.INTERNAL_API_KEY,
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
   * Cleanup idle sandbox
   */
  async alarm(): Promise<void> {
    const lastActivity = (await this.ctx.storage.get<number>('lastActivity')) || 0;
    const idleTime = Date.now() - lastActivity;
    const idleThreshold = 30 * 60 * 1000; // 30 minutes

    if (idleTime > idleThreshold && this.sandbox) {
      console.log(`Cleaning up idle sandbox for tenant DO: ${this.ctx.id.toString()}`);
      // Destroy the sandbox to free resources
      await this.sandbox.destroy();
      this.sandbox = null;
      this.configHash = null;
      this.agentProcess = null;
    } else {
      // Schedule next check
      await this.ctx.storage.setAlarm(Date.now() + idleThreshold);
    }
  }

  private jsonResponse(data: unknown, status = 200): Response {
    return new Response(JSON.stringify(data), {
      status,
      headers: { 'Content-Type': 'application/json' },
    });
  }
}
