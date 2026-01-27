/**
 * Agent - Claude Agent SDK wrapper
 */

// Ensure node and claude CLI are in PATH for the SDK's subprocess spawning
// The SDK spawns the claude CLI which then spawns node
const additionalPaths = [
  '/usr/local/bin', // claude CLI in Docker
  '/opt/homebrew/bin', // node on macOS ARM
  process.env.HOME ? `${process.env.HOME}/.local/bin` : '', // local user bin
].filter(Boolean);

for (const p of additionalPaths) {
  if (p && !process.env.PATH?.includes(p)) {
    process.env.PATH = `${p}:${process.env.PATH}`;
  }
}

// Model defaults based on backend
const DEFAULT_ANTHROPIC_MODEL = 'claude-sonnet-4-20250514';
const DEFAULT_BEDROCK_MODEL = 'us.anthropic.claude-opus-4-5-20251101-v1:0';

/**
 * Check if model ID is a Bedrock inference profile format
 */
function isBedrockModelId(model: string): boolean {
  return /^(us|eu|ap)\.(anthropic\.|amazon\.)/.test(model);
}

/**
 * Auto-detect and configure backend based on available credentials
 * Priority:
 * 1. If CLAUDE_CODE_USE_BEDROCK=1 is set, use Bedrock
 * 2. If AWS credentials are present, use Bedrock
 * 3. If ANTHROPIC_API_KEY is present, use Anthropic API
 * 4. Otherwise, error out with helpful message
 */
function configureBackend(): void {
  const hasAwsCredentials = !!(process.env.AWS_ACCESS_KEY_ID && process.env.AWS_SECRET_ACCESS_KEY);
  const hasAnthropicKey = !!process.env.ANTHROPIC_API_KEY;
  const explicitBedrock = process.env.CLAUDE_CODE_USE_BEDROCK === '1';
  const currentModel = process.env.ANTHROPIC_MODEL || '';

  // Explicit Bedrock mode
  if (explicitBedrock) {
    if (!hasAwsCredentials) {
      console.log('Using Bedrock with AWS CLI credential chain');
    }
    if (!currentModel) {
      process.env.ANTHROPIC_MODEL = DEFAULT_BEDROCK_MODEL;
    }
    return;
  }

  // Auto-detect based on credentials
  if (hasAwsCredentials) {
    process.env.CLAUDE_CODE_USE_BEDROCK = '1';
    if (!currentModel || !isBedrockModelId(currentModel)) {
      process.env.ANTHROPIC_MODEL = DEFAULT_BEDROCK_MODEL;
    }
    console.log('Auto-detected Bedrock mode (AWS credentials found)');
    return;
  }

  if (hasAnthropicKey) {
    // Ensure we're not using a Bedrock model ID with Anthropic API
    if (isBedrockModelId(currentModel)) {
      process.env.ANTHROPIC_MODEL = DEFAULT_ANTHROPIC_MODEL;
      console.log(`Switching to Anthropic model: ${DEFAULT_ANTHROPIC_MODEL}`);
    } else if (!currentModel) {
      process.env.ANTHROPIC_MODEL = DEFAULT_ANTHROPIC_MODEL;
    }
    console.log('Using Anthropic API mode');
    return;
  }

  // No credentials - log helpful error and set default model for Anthropic API
  console.error('ERROR: No API credentials configured.');
  console.error('Set one of the following:');
  console.error('  - ANTHROPIC_API_KEY for direct Anthropic API');
  console.error('  - AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY for Bedrock');

  // Set default Anthropic model so logs are accurate
  if (!currentModel || isBedrockModelId(currentModel)) {
    process.env.ANTHROPIC_MODEL = DEFAULT_ANTHROPIC_MODEL;
  }
}

// Run backend configuration before SDK import
console.log('Configuring backend...');
configureBackend();
console.log('Backend configured. Model:', process.env.ANTHROPIC_MODEL);

import { query, type SDKMessage, type McpServerConfig } from '@anthropic-ai/claude-agent-sdk';
import { loadSkills, filterSkillsByRoles, buildSystemPromptFromSkills } from './skills/loader';
import { buildMcpServers, parseConnectorsFromEnv } from './mcp/servers';

export interface ChatOptions {
  sessionId?: string;
  tenantId: string;
  userId: string;
  userRoles?: string[];
  skills?: string[];
  model?: string;
}

export interface ChatResult {
  response: string;
  sessionId: string;
  usage: {
    inputTokens: number;
    outputTokens: number;
    cacheReadTokens?: number;
    cacheWriteTokens?: number;
  };
  timing?: {
    totalMs: number;
    skillsLoadMs: number;
    mcpBuildMs: number;
    promptBuildMs: number;
    sdkFirstChunkMs: number;
    sdkTotalMs: number;
  };
}

/**
 * Build query options for the SDK
 */
function buildQueryOptions(
  systemPrompt: string,
  mcpServers: Record<string, McpServerConfig>,
  model?: string,
  resume?: string
) {
  const options = {
    resume,
    model: model || process.env.ANTHROPIC_MODEL || 'us.anthropic.claude-opus-4-5-20251101-v1:0',
    includePartialMessages: true,
    permissionMode: 'bypassPermissions' as const,
    cwd: process.env.WORKSPACE_PATH || process.cwd(),
    allowedTools: ['Read', 'Write', 'Edit', 'Bash', 'Glob', 'Grep'] as string[],
    systemPrompt,
    mcpServers: Object.keys(mcpServers).length > 0 ? mcpServers : undefined,
    // Path to globally installed Claude CLI (npm install -g @anthropic-ai/claude-code)
    pathToClaudeCodeExecutable: '/usr/local/bin/claude',
  };
  console.log('Query options:', {
    model: options.model,
    cwd: options.cwd,
    permissionMode: options.permissionMode,
    resume: options.resume,
    mcpServersCount: Object.keys(mcpServers).length,
    systemPromptLength: systemPrompt.length,
  });
  return options;
}

/**
 * Execute a chat request using Claude Agent SDK (streaming)
 *
 * If sessionId is provided, attempts to resume that session first.
 * If resume fails (session doesn't exist), falls back to creating a new session.
 */
// Custom timing event type for telemetry
export interface TimingEvent {
  type: 'timing';
  phase: string;
  ms: number;
  details?: Record<string, unknown>;
}

export async function* chat(
  message: string,
  options: ChatOptions
): AsyncGenerator<SDKMessage | TimingEvent> {
  const t0 = Date.now();
  const t = () => Date.now() - t0;

  console.log(`[CHAT] T+${t()}ms: chat() started`);

  // Load skills
  console.log(`[CHAT] T+${t()}ms: Loading skills...`);
  const skillsStart = Date.now();
  const allSkills = await loadSkills();
  const skillsMs = Date.now() - skillsStart;
  console.log(`[CHAT] T+${t()}ms: Skills loaded (${allSkills.length}) in ${skillsMs}ms`);

  // Filter skills based on user roles
  const userRoles = options.userRoles || ['user'];
  let skills = filterSkillsByRoles(allSkills, userRoles);

  // Filter to specific skills if requested
  if (options.skills && options.skills.length > 0) {
    skills = skills.filter((s) => options.skills!.includes(s.name));
  }

  // Build MCP servers from connectors
  console.log(`[CHAT] T+${t()}ms: Building MCP servers...`);
  const mcpStart = Date.now();
  const connectors = parseConnectorsFromEnv();
  const mcpServers = buildMcpServers(connectors);
  const mcpMs = Date.now() - mcpStart;
  console.log(`[CHAT] T+${t()}ms: MCP servers built (${Object.keys(mcpServers).length}) in ${mcpMs}ms`);

  // Build system prompt
  console.log(`[CHAT] T+${t()}ms: Building system prompt...`);
  const promptStart = Date.now();
  const systemPrompt = buildSystemPromptFromSkills(skills);
  const promptMs = Date.now() - promptStart;
  console.log(`[CHAT] T+${t()}ms: System prompt built (${systemPrompt.length} chars) in ${promptMs}ms`);

  // Emit timing event before SDK call so client can see pre-SDK overhead
  yield {
    type: 'timing',
    phase: 'pre_sdk',
    ms: t(),
    details: {
      skillsMs,
      mcpMs,
      promptMs,
      skillCount: skills.length,
      promptLength: systemPrompt.length,
    },
  } as TimingEvent;

  // NOTE: Session resume disabled - widget-generated sessionIds don't exist in
  // Claude CLI's session storage (~/.claude/), causing 6+ second delays when
  // the SDK tries to load non-existent sessions. Always start fresh queries.
  // TODO: Re-enable resume only for sessions that originated from Claude SDK responses.

  // Start new session
  console.log(`[CHAT] T+${t()}ms: Starting Claude SDK query()...`);
  const sdkStart = Date.now();
  const result = query({
    prompt: message,
    options: buildQueryOptions(systemPrompt, mcpServers, options.model),
  });

  let firstYield = true;
  for await (const msg of result) {
    if (firstYield) {
      const sdkFirstYieldMs = Date.now() - sdkStart;
      console.log(`[CHAT] T+${t()}ms: First yield from SDK (type: ${msg.type}) in ${sdkFirstYieldMs}ms`);

      // Emit timing event for SDK first yield
      yield {
        type: 'timing',
        phase: 'sdk_first_yield',
        ms: t(),
        details: {
          sdkFirstYieldMs,
          msgType: msg.type,
        },
      } as TimingEvent;

      firstYield = false;
    }
    yield msg;
  }

  console.log(`[CHAT] T+${t()}ms: chat() completed`);
}

/**
 * Execute a chat request and return final result
 */
export async function chatSync(
  message: string,
  options: ChatOptions
): Promise<ChatResult> {
  const t0 = Date.now();
  let response = '';
  let sessionId = options.sessionId || '';
  let usage = {
    inputTokens: 0,
    outputTokens: 0,
    cacheReadTokens: 0,
    cacheWriteTokens: 0,
  };

  // Timing tracking
  const timing = {
    totalMs: 0,
    skillsLoadMs: 0,
    mcpBuildMs: 0,
    promptBuildMs: 0,
    sdkFirstChunkMs: 0,
    sdkTotalMs: 0,
  };

  let firstChunkTime: number | null = null;

  console.log(`[SDK TIMING] T+0ms: chatSync started`);

  // Load skills with timing
  const skillsStart = Date.now();
  const allSkills = await loadSkills();
  timing.skillsLoadMs = Date.now() - skillsStart;
  console.log(`[SDK TIMING] T+${Date.now() - t0}ms: Skills loaded (${allSkills.length}) in ${timing.skillsLoadMs}ms`);

  // Filter skills based on user roles
  const userRoles = options.userRoles || ['user'];
  let skills = filterSkillsByRoles(allSkills, userRoles);
  if (options.skills && options.skills.length > 0) {
    skills = skills.filter((s) => options.skills!.includes(s.name));
  }

  // Build MCP servers with timing
  const mcpStart = Date.now();
  const connectors = parseConnectorsFromEnv();
  const mcpServers = buildMcpServers(connectors);
  timing.mcpBuildMs = Date.now() - mcpStart;
  console.log(`[SDK TIMING] T+${Date.now() - t0}ms: MCP built in ${timing.mcpBuildMs}ms`);

  // Build system prompt with timing
  const promptStart = Date.now();
  const systemPrompt = buildSystemPromptFromSkills(skills);
  timing.promptBuildMs = Date.now() - promptStart;
  console.log(`[SDK TIMING] T+${Date.now() - t0}ms: Prompt built (${systemPrompt.length} chars) in ${timing.promptBuildMs}ms`);

  // SDK query with timing
  const sdkStart = Date.now();
  console.log(`[SDK TIMING] T+${Date.now() - t0}ms: Starting SDK query...`);

  // Note: Only pass resume if we're explicitly resuming an existing session
  // Passing a new UUID as resume causes the SDK to try to load a non-existent session
  // For new sessions, let the SDK generate its own session ID
  const result = query({
    prompt: message,
    options: buildQueryOptions(systemPrompt, mcpServers, options.model),
  });

  for await (const msg of result) {
    if (!firstChunkTime) {
      firstChunkTime = Date.now() - sdkStart;
      timing.sdkFirstChunkMs = firstChunkTime;
      console.log(`[SDK TIMING] T+${Date.now() - t0}ms: First SDK chunk in ${firstChunkTime}ms`);
    }

    if (msg.type === 'assistant') {
      for (const block of msg.message.content) {
        if (block.type === 'text') {
          response += block.text;
        }
      }
    } else if (msg.type === 'result') {
      sessionId = msg.session_id;
      usage = {
        inputTokens: msg.usage.input_tokens,
        outputTokens: msg.usage.output_tokens,
        cacheReadTokens: msg.usage.cache_read_input_tokens || 0,
        cacheWriteTokens: msg.usage.cache_creation_input_tokens || 0,
      };
    }
  }

  timing.sdkTotalMs = Date.now() - sdkStart;
  timing.totalMs = Date.now() - t0;
  console.log(`[SDK TIMING] T+${timing.totalMs}ms: chatSync completed (SDK: ${timing.sdkTotalMs}ms)`);

  return {
    response,
    sessionId,
    usage,
    timing,
  };
}

