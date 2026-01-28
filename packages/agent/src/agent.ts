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
  sessionPath?: string; // Session workspace path for native skill loading
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
 *
 * When sessionPath is provided, enables native skill loading via:
 * - cwd: set to sessionPath for project-scoped discovery
 * - settingSources: ['project'] to load skills from {cwd}/.claude/skills/
 * - Skill added to allowedTools
 *
 * systemPrompt is kept as fallback for environments without native skill support.
 */
function buildQueryOptions(
  systemPrompt: string,
  mcpServers: Record<string, McpServerConfig>,
  model?: string,
  resume?: string,
  sessionPath?: string
) {
  // Use sessionPath for native skill loading, fall back to WORKSPACE_PATH or cwd
  const cwd = sessionPath || process.env.SESSION_PATH || process.env.WORKSPACE_PATH || process.cwd();

  // Enable native skill loading when we have a session path
  const useNativeSkills = !!(sessionPath || process.env.SESSION_PATH);

  // Include 'Skill' tool when native skills are enabled
  const allowedTools = useNativeSkills
    ? ['Skill', 'Read', 'Write', 'Edit', 'Bash', 'Glob', 'Grep']
    : ['Read', 'Write', 'Edit', 'Bash', 'Glob', 'Grep'];

  const options = {
    resume,
    model: model || process.env.ANTHROPIC_MODEL || DEFAULT_BEDROCK_MODEL,
    includePartialMessages: true,
    permissionMode: 'bypassPermissions' as const,
    cwd,
    allowedTools: allowedTools as string[],
    // Enable native skill loading from {cwd}/.claude/skills/ when session path is set
    ...(useNativeSkills && { settingSources: ['project'] as ('user' | 'project')[] }),
    // Keep systemPrompt as fallback for backward compatibility
    // When native skills work, this becomes redundant but harmless
    systemPrompt,
    mcpServers: Object.keys(mcpServers).length > 0 ? mcpServers : undefined,
    // Path to globally installed Claude CLI (npm install -g @anthropic-ai/claude-code)
    pathToClaudeCodeExecutable: '/usr/local/bin/claude',
    // Disable session persistence to avoid filesystem writes and slow session loading
    persistSession: false,
    // Capture stderr from Claude Code subprocess for debugging
    stderr: (data: string) => {
      console.log('[SDK STDERR]', data.trim());
    },
  };
  console.log('Query options:', {
    model: options.model,
    cwd: options.cwd,
    useNativeSkills,
    settingSources: useNativeSkills ? ['project'] : undefined,
    permissionMode: options.permissionMode,
    resume: options.resume,
    mcpServersCount: Object.keys(mcpServers).length,
    systemPromptLength: systemPrompt.length,
    allowedTools: options.allowedTools,
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
  // Use sessionPath for native skill loading if provided
  const sessionPath = options.sessionPath || process.env.SESSION_PATH;
  console.log(`[CHAT] T+${t()}ms: Starting Claude SDK query() (sessionPath: ${sessionPath || 'none'})...`);
  const sdkStart = Date.now();
  const result = query({
    prompt: message,
    options: buildQueryOptions(systemPrompt, mcpServers, options.model, undefined, sessionPath),
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


