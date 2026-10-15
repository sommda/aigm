from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from aigm.models import SSEEvent


@dataclass
class ToolOutcome:
    content: str
    is_error: bool = False
    event: SSEEvent | None = None


@dataclass
class Tool:
    schema: dict[str, Any]
    # handler(tool_use_id, tool_input) -> ToolOutcome
    handler: Callable[[str, dict[str, Any]], ToolOutcome]
