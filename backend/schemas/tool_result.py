from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class ToolResult(BaseModel):
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    next_suggestion: Optional[str] = None

    @classmethod
    def ok(cls, data: Any) -> "ToolResult":
        return cls(success=True, data=data)

    @classmethod
    def fail(cls, error: str, next_suggestion: Optional[str] = None) -> "ToolResult":
        return cls(success=False, error=error, next_suggestion=next_suggestion)