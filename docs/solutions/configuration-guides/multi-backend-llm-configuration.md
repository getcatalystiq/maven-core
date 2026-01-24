---
type: feature
category: integration/llm
module: src/maven_core/llm/claude.py
components:
  - ClaudeClient
  - create_llm_client
problem: "Claude Agent SDK multi-backend configuration"
description: |
  Configuring Claude Agent SDK to support multiple backends (Anthropic API,
  AWS Bedrock, Google Vertex AI) for the maven-core framework.
symptoms:
  - Could only use direct Anthropic API calls
  - No enterprise cloud provider support (AWS/GCP)
  - Required hardcoded ANTHROPIC_API_KEY for all deployments
  - No regional deployment options for compliance requirements
tags:
  - claude-agent-sdk
  - multi-backend
  - aws-bedrock
  - google-vertex
  - anthropic-api
  - llm-client
  - enterprise-integration
  - configuration
severity: enhancement
tested_with:
  - AWS Bedrock
  - Claude Opus 4.5
files_modified:
  - src/maven_core/llm/claude.py
  - src/maven_core/llm/factory.py
  - src/maven_core/config.py
  - src/maven_core/agent.py
---

# Configuring Claude Agent SDK with Multiple Backends

## Overview

The Claude Agent SDK supports multiple LLM backends. This guide explains how to configure maven-core to use:

- **Anthropic API** (default) - Direct API access
- **AWS Bedrock** - Enterprise AWS integration
- **Google Vertex AI** - Enterprise GCP integration

## Root Cause

The Claude Agent SDK uses **environment variables** to select backends at runtime. When building a configurable agent framework, you need to:

1. Allow users to specify the backend in configuration files (YAML/JSON)
2. Translate configuration values into the appropriate environment variables
3. Pass backend-specific parameters (AWS region, model IDs, profiles)

## Solution

### Configuration Schema

The `LLMConfig` model in `config.py` defines all backend options:

```python
class LLMConfig(BaseModel):
    provider: str = "claude"  # claude | mock
    backend: str = "anthropic"  # anthropic | bedrock | vertex
    model: str | None = None  # Model ID (auto-detected if not set)
    allowed_tools: list[str] = Field(default_factory=lambda: ["Read", "Glob", "Grep"])
    cwd: str | None = None
    system_prompt: str | None = None
    max_turns: int | None = None
    permission_mode: str = "default"  # default | acceptEdits | bypassPermissions

    # AWS Bedrock settings
    aws_region: str | None = None
    aws_profile: str | None = None
```

### Backend Configuration Method

The `ClaudeClient._configure_backend()` method translates config to environment variables:

```python
def _configure_backend(self) -> None:
    """Configure Claude Agent SDK backend via environment variables."""
    if self.backend == "bedrock":
        os.environ["CLAUDE_CODE_USE_BEDROCK"] = "1"
        if self.aws_region:
            os.environ["AWS_REGION"] = self.aws_region
        if self.aws_profile:
            os.environ["AWS_PROFILE"] = self.aws_profile
        if self.model:
            os.environ["CLAUDE_CODE_BEDROCK_MODEL"] = self.model
    elif self.backend == "vertex":
        os.environ["CLAUDE_CODE_USE_VERTEX"] = "1"
        if self.model:
            os.environ["CLAUDE_CODE_VERTEX_MODEL"] = self.model
```

## Configuration Examples

### Anthropic API (Default)

```yaml
llm:
  provider: claude
  backend: anthropic
  allowed_tools:
    - Read
    - Write
    - Bash
```

**Required:** Set `ANTHROPIC_API_KEY` environment variable.

### AWS Bedrock

```yaml
llm:
  provider: claude
  backend: bedrock
  model: us.anthropic.claude-opus-4-5-20251101-v1:0
  aws_region: us-east-1
  aws_profile: default  # Optional
  allowed_tools:
    - Read
    - Write
    - Bash
```

**Bedrock Model IDs:**
| Model | ID |
|-------|-----|
| Claude Opus 4.5 | `us.anthropic.claude-opus-4-5-20251101-v1:0` |
| Claude Sonnet 4 | `us.anthropic.claude-sonnet-4-20250514-v1:0` |
| Claude Haiku 3.5 | `us.anthropic.claude-3-5-haiku-20241022-v1:0` |

**AWS Credentials:** Configure via `~/.aws/credentials`, environment variables, or IAM role.

### Google Vertex AI

```yaml
llm:
  provider: claude
  backend: vertex
  model: claude-sonnet-4@20250514
  allowed_tools:
    - Read
    - Write
```

**Required:**
```bash
gcloud auth application-default login
export GOOGLE_CLOUD_PROJECT=your-project-id
```

## Environment Variables Reference

| Backend | Variable | Description |
|---------|----------|-------------|
| anthropic | `ANTHROPIC_API_KEY` | API key |
| bedrock | `CLAUDE_CODE_USE_BEDROCK=1` | Enable Bedrock |
| bedrock | `AWS_REGION` | AWS region |
| bedrock | `AWS_PROFILE` | Profile name (optional) |
| bedrock | `CLAUDE_CODE_BEDROCK_MODEL` | Model ID |
| vertex | `CLAUDE_CODE_USE_VERTEX=1` | Enable Vertex |
| vertex | `CLAUDE_CODE_VERTEX_MODEL` | Model ID |

## Verification

### Test Configuration Loading

```python
from maven_core.config import Config

config = Config.from_file("config.yaml")
print(f"Backend: {config.llm.backend}")
print(f"Model: {config.llm.model}")
print(f"Region: {config.llm.aws_region}")
```

### Test with Bedrock

```python
import asyncio
from maven_core import Agent

async def test():
    agent = Agent.from_config("config.yaml")
    response = await agent.chat(
        message="Hello!",
        user_id="test-user",
    )
    print(response.content)

asyncio.run(test())
```

## Common Pitfalls

### 1. Multiple Backend Flags Set

**Problem:** Both `CLAUDE_CODE_USE_BEDROCK=1` and `CLAUDE_CODE_USE_VERTEX=1` are set.

**Solution:** Only configure one backend in your YAML config. The `_configure_backend()` method handles setting the correct environment variables.

### 2. Wrong Model ID Format

**Problem:** Using Anthropic model IDs with Bedrock.

**Solution:** Use backend-specific model IDs:
- Anthropic: `claude-3-5-sonnet-20241022`
- Bedrock: `us.anthropic.claude-3-5-sonnet-20241022-v2:0`
- Vertex: `claude-3-5-sonnet@20241022`

### 3. Missing AWS Permissions

**Problem:** `AccessDeniedException` from Bedrock.

**Solution:** Ensure IAM role has:
```json
{
    "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
    ],
    "Resource": "arn:aws:bedrock:*::foundation-model/anthropic.claude-*"
}
```

### 4. Model Not Enabled in Bedrock

**Problem:** Model returns 404 or access denied.

**Solution:** Enable model access in AWS Console → Bedrock → Model access → Request access for Claude models.

## Troubleshooting Checklist

```bash
# Check which backend is configured
env | grep -E "CLAUDE_CODE_USE_(BEDROCK|VERTEX)"

# Test AWS credentials (for Bedrock)
aws sts get-caller-identity
aws bedrock list-foundation-models --region us-east-1 --query "modelSummaries[?contains(modelId, 'claude')]"

# Test GCP credentials (for Vertex)
gcloud auth list
gcloud config get-value project
```

## Related Documentation

- [Configuration Reference](../../configuration.md)
- [Quick Start Guide](../../quickstart.md)
- [config.example.yaml](../../../config.example.yaml)
