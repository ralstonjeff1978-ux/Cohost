"""
TOOL REGISTRY - Central Tool Hub with Auto-Discovery
=====================================================
Single source of truth for all callable tools in Apex.

Design principles:
- Dependency injection: the registry is passed to components that need tools.
  No module imports another module directly — everything routes through here.
- Auto-discovery: on startup the registry scans every enabled apex subpackage
  for a register_tools(registry) function and calls it.
- Per-module control: set modules.<name>: true/false in config.yaml to
  enable or disable an entire subpackage at startup.

Authoring tools in a submodule
-------------------------------
Option A — explicit (recommended for complex modules):

    # apex/memory/__init__.py
    def register_tools(registry):
        registry.register("memory_read",  "Read from agent memory",  _read)
        registry.register("memory_write", "Write to agent memory",   _write)

Option B — decorator (good for simple utility files):

    from core.tool_registry import tool

    @tool("list_files", "List files in a directory", tags=["file"])
    def list_files(path: str) -> list:
        ...

Both patterns are discovered automatically during registry.discover().
"""

import importlib.util
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.paths import COHOST_HOME, load_config as _load_config

log = logging.getLogger("tool_registry")

_APEX_ROOT = COHOST_HOME


# ── Tool model ─────────────────────────────────────────────────────────────────

@dataclass
class Tool:
    """Metadata and callable for a registered tool."""
    name:        str
    description: str
    fn:          Callable
    module:      str                            # source subpackage label
    enabled:     bool = True
    tags:        List[str] = field(default_factory=list)

    def __str__(self) -> str:
        status = "✓" if self.enabled else "✗"
        tag_str = f"  [{', '.join(self.tags)}]" if self.tags else ""
        return f"[{status}] {self.name:<28} ({self.module}){tag_str} — {self.description}"


# ── Decorator ──────────────────────────────────────────────────────────────────

def tool(name: str, description: str, tags: List[str] = None):
    """
    Mark a function as an Apex tool so the registry can collect it automatically.

    The function is unchanged at runtime — the decorator only attaches metadata.
    Discovery picks it up; no import of the registry is needed at call time.

    Args:
        name:        Unique tool name referenced in LLM plans.
        description: One-line description shown in planning prompts.
        tags:        Optional category labels (e.g. ["file", "io"]).

    Example:
        @tool("read_file", "Read a file and return its text content", tags=["file"])
        def read_file(path: str) -> str:
            return Path(path).read_text(encoding="utf-8")
    """
    def decorator(fn: Callable) -> Callable:
        fn._tool_meta = {
            "name":        name,
            "description": description,
            "tags":        tags or [],
        }
        return fn
    return decorator


# ── Registry ───────────────────────────────────────────────────────────────────

class ToolRegistry:
    """
    Central registry for all callable tools.

    Instantiate once at startup, run discover(), then pass this instance
    to AgentCore, VerificationEngine, and any other component that needs
    to call tools — never import tool functions directly across modules.
    """

    def __init__(self):
        self._tools: Dict[str, Tool] = {}
        cfg = _load_config()
        self._module_flags: Dict[str, bool] = cfg.get("modules", {})

    # ── Registration ───────────────────────────────────────────────────────────

    def register(self, name: str, description: str, fn: Callable,
                 module: str = "manual", tags: List[str] = None,
                 enabled: bool = True) -> None:
        """
        Register a single callable tool.

        Args:
            name:        Unique tool identifier used in LLM plan tool_calls.
            description: One-line description injected into planning prompts.
            fn:          The callable to invoke.
            module:      Source module label used for filtering and reporting.
            tags:        Optional category tags.
            enabled:     Whether the tool is immediately active. Default True.
        """
        if name in self._tools:
            log.debug("Re-registering tool: %s (module: %s)", name, module)
        self._tools[name] = Tool(
            name=name, description=description, fn=fn,
            module=module, enabled=enabled, tags=tags or [],
        )
        log.debug("Registered tool: %s (%s)", name, module)

    def register_many(self, tools: List[Dict]) -> None:
        """
        Bulk-register from a list of dicts.

        Each dict must have: name, description, fn.
        Optional keys: module, tags, enabled.
        """
        for t in tools:
            self.register(**t)

    # ── Discovery ──────────────────────────────────────────────────────────────

    def discover(self, apex_root: Path = None) -> int:
        """
        Scan all enabled apex subpackages and register their tools.

        For each enabled subfolder under apex/ (excluding core/):
          1. Calls register_tools(registry) if present in __init__.py or any .py
          2. Falls back to collecting @tool-decorated functions

        Args:
            apex_root: Override root directory. Defaults to apex/ (parent of core/).

        Returns:
            Number of new tools registered during this call.
        """
        root   = apex_root or _APEX_ROOT
        before = len(self._tools)

        for folder in sorted(root.iterdir()):
            if not folder.is_dir():
                continue
            module_name = folder.name
            if module_name in ("core", "__pycache__") or module_name.startswith("."):
                continue
            if not self._module_flags.get(module_name, True):
                log.info("Module '%s' disabled in config — skipping", module_name)
                continue
            self._discover_package(folder, module_name)

        count = len(self._tools) - before
        log.info("Discovery complete — %d tool(s) registered", count)
        return count

    def _discover_package(self, folder: Path, module_name: str) -> None:
        """Load and register tools from one apex subpackage folder."""
        # Prefer __init__.py; fall back to all .py files
        init = folder / "__init__.py"
        candidates = [init] if init.exists() else sorted(folder.glob("*.py"))

        for py_file in candidates:
            self._load_file(py_file, module_name)

    def _load_file(self, py_file: Path, module_name: str) -> None:
        """Dynamically import one Python file and collect any tools it defines."""
        import_name = f"apex.{module_name}.{py_file.stem}"

        # Ensure apex parent is importable
        apex_parent = str(_APEX_ROOT.parent)
        if apex_parent not in sys.path:
            sys.path.insert(0, apex_parent)

        try:
            spec   = importlib.util.spec_from_file_location(import_name, py_file)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Strategy 1: explicit register_tools(registry) — preferred
            if hasattr(module, "register_tools") and callable(module.register_tools):
                module.register_tools(self)
                log.info("  [%s] register_tools() called", import_name)
                return

            # Strategy 2: @tool-decorated functions
            found = 0
            for attr_name in dir(module):
                fn = getattr(module, attr_name)
                if callable(fn) and hasattr(fn, "_tool_meta"):
                    meta = fn._tool_meta
                    self.register(
                        name=meta["name"],
                        description=meta["description"],
                        fn=fn,
                        module=module_name,
                        tags=meta.get("tags", []),
                    )
                    found += 1

            if found:
                log.info("  [%s] collected %d @tool function(s)", import_name, found)

        except Exception as e:
            log.warning("  Could not load %s: %s", py_file.name, e)

    # ── Calling tools ──────────────────────────────────────────────────────────

    def call_tool(self, name: str, *args, **kwargs) -> Tuple[bool, Any]:
        """
        Call a registered tool by name.

        Args:
            name:     The tool name as registered.
            *args:    Positional arguments forwarded to the tool function.
            **kwargs: Keyword arguments forwarded to the tool function.

        Returns:
            (success: bool, result: Any)
            Returns (False, error_str) on unknown tool, disabled tool, or exception.
        """
        t = self._tools.get(name)
        if t is None:
            return False, f"Unknown tool: '{name}'"
        if not t.enabled:
            return False, f"Tool '{name}' is disabled"
        try:
            return True, t.fn(*args, **kwargs)
        except Exception as e:
            log.error("Tool '%s' raised: %s", name, e)
            return False, str(e)

    # ── Enable / disable ───────────────────────────────────────────────────────

    def enable(self, name: str) -> None:
        """Enable a single tool by name."""
        if name in self._tools:
            self._tools[name].enabled = True
            log.info("Enabled tool: %s", name)
        else:
            log.warning("enable() — unknown tool: %s", name)

    def disable(self, name: str) -> None:
        """Disable a single tool. Calls return an error string, not an exception."""
        if name in self._tools:
            self._tools[name].enabled = False
            log.info("Disabled tool: %s", name)
        else:
            log.warning("disable() — unknown tool: %s", name)

    def enable_module(self, module_name: str) -> int:
        """Enable all tools belonging to a module. Returns count changed."""
        count = 0
        for t in self._tools.values():
            if t.module == module_name and not t.enabled:
                t.enabled = True
                count += 1
        log.info("Enabled %d tool(s) in module '%s'", count, module_name)
        return count

    def disable_module(self, module_name: str) -> int:
        """Disable all tools belonging to a module. Returns count changed."""
        count = 0
        for t in self._tools.values():
            if t.module == module_name and t.enabled:
                t.enabled = False
                count += 1
        log.info("Disabled %d tool(s) in module '%s'", count, module_name)
        return count

    # ── Introspection ──────────────────────────────────────────────────────────

    def list_tools(self, enabled_only: bool = False,
                   module: str = None, tag: str = None) -> List[Tool]:
        """
        Return registered tools with optional filtering.

        Args:
            enabled_only: Return only enabled tools.
            module:       Filter by source module name.
            tag:          Filter by tag string.
        """
        tools = list(self._tools.values())
        if enabled_only:
            tools = [t for t in tools if t.enabled]
        if module:
            tools = [t for t in tools if t.module == module]
        if tag:
            tools = [t for t in tools if tag in t.tags]
        return tools

    def get_tool_list_for_prompt(self) -> str:
        """
        Return a formatted string of enabled tools for LLM planning prompts.

        Consumed by AgentCore._create_plan() to populate the AVAILABLE TOOLS
        section of the planning prompt.
        """
        enabled = self.list_tools(enabled_only=True)
        if not enabled:
            return "  (no tools registered)"

        lines = []
        for t in sorted(enabled, key=lambda x: x.name):
            tag_str = f"  [{', '.join(t.tags)}]" if t.tags else ""
            lines.append(f"  {t.name:<28} {t.description}{tag_str}")
        return "\n".join(lines)

    def summary(self) -> str:
        """One-line summary of registry state."""
        total   = len(self._tools)
        enabled = sum(1 for t in self._tools.values() if t.enabled)
        modules = len({t.module for t in self._tools.values()})
        return f"{enabled}/{total} tools enabled across {modules} module(s)"

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __repr__(self) -> str:
        return f"ToolRegistry({self.summary()})"
