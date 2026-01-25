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
 * Execute a chat request using Claude Agent SDK
 *
 * If sessionId is provided, attempts to resume that session first.
 * If resume fails (session doesn't exist), falls back to creating a new session.
 */
export async function* chat(
  message: string,
  options: ChatOptions
): AsyncGenerator<SDKMessage> {
  // Load skills
  const allSkills = await loadSkills();

  // Filter skills based on user roles
  const userRoles = options.userRoles || ['user'];
  let skills = filterSkillsByRoles(allSkills, userRoles);

  // Filter to specific skills if requested
  if (options.skills && options.skills.length > 0) {
    skills = skills.filter((s) => options.skills!.includes(s.name));
  }

  // Build MCP servers from connectors
  const connectors = parseConnectorsFromEnv();
  const mcpServers = buildMcpServers(connectors);

  // Build system prompt
  const systemPrompt = buildSystemPromptFromSkills(skills);

  // If sessionId provided, try to resume first
  if (options.sessionId) {
    try {
      const resumeResult = query({
        prompt: message,
        options: buildQueryOptions(systemPrompt, mcpServers, options.model, options.sessionId),
      });

      // Collect messages from resume attempt to check if it was successful
      // We buffer messages and only yield them if we got meaningful output
      const bufferedMessages: SDKMessage[] = [];
      let hasContent = false;

      for await (const msg of resumeResult) {
        bufferedMessages.push(msg);

        // Check if we got actual content (not just an empty result)
        if (msg.type === 'assistant' && msg.message.content.length > 0) {
          hasContent = true;
        }
        if (msg.type === 'stream_event') {
          hasContent = true;
        }
        if (msg.type === 'result' && msg.usage.output_tokens > 0) {
          hasContent = true;
        }
      }

      // If we got meaningful content, yield all buffered messages
      if (hasContent) {
        for (const msg of bufferedMessages) {
          yield msg;
        }
        return;
      }

      // Resume returned empty - session doesn't exist, fall through to new session
      console.log(`Session ${options.sessionId} returned empty response, starting new session`);
    } catch (error) {
      // Resume failed - session doesn't exist or is invalid
      // Log and fall through to create new session
      console.log(`Session resume failed for ${options.sessionId}, starting new session:`, (error as Error).message);
    }
  }

  // Start new session (either no sessionId provided, or resume failed)
  const result = query({
    prompt: message,
    options: buildQueryOptions(systemPrompt, mcpServers, options.model),
  });

  for await (const msg of result) {
    yield msg;
  }
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

  let firstChunkTime: number | null = null;

  console.log(`[SDK TIMING] T+0ms: chatSync started, calling chat()`);
  for await (const msg of chat(message, options)) {
    if (!firstChunkTime) {
      firstChunkTime = Date.now() - t0;
      console.log(`[SDK TIMING] T+${firstChunkTime}ms: First message from SDK (time to first chunk)`);
    }

    if (msg.type === 'assistant') {
      // Extract text content
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

  console.log(`[SDK TIMING] T+${Date.now() - t0}ms: chatSync completed, total time`);

  return {
    response,
    sessionId,
    usage,
  };
}

