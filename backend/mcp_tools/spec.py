from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ToolSpec:
    name: str
    description: str
    when_to_use: list[str]
    when_not_to_use: list[str]
    returns: str
    category: str = "general"
    parameters: dict = field(default_factory=dict)
