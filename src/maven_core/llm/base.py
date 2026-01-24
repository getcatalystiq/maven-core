"""Base types for LLM clients."""

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class StreamEvent:
    """An event from the LLM stream."""

    type: Literal["text", "tool_use", "tool_result", "done", "error"]
    content: str = ""
    tool_name: str | None = None
    tool_input: dict[str, Any] | None = None
    error: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
