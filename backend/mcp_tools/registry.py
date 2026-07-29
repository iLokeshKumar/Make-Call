from dataclasses import dataclass
from importlib import import_module
from typing import Any, Callable

@dataclass
class RegisteredTool:
    name: str
    module_path: str
    attr_name: str
    spec: Any
    category: str
    lazy: bool = True

class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, RegisteredTool] = {}

    def register(self, tool: RegisteredTool) -> None:
        self._tools[tool.name] = tool

    def get_spec(self, name: str):
        return self._tools[name].spec

    def list_all(self) -> list[str]:
        return list(self._tools.keys())

    def list_by_category(self, category: str) -> list[str]:
        return [t.name for t in self._tools.values() if t.category == category]

    def get_executor(self, name: str) -> Callable:
        tool = self._tools[name]
        module = import_module(tool.module_path)
        return getattr(module, tool.attr_name)