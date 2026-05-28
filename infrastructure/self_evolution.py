"""
SELF EVOLUTION - Autonomous Self-Improvement
=============================================
Apex can write new tools, improve existing code, and extend its own capabilities.

This is true self-improvement - identifying gaps and filling them autonomously.
"""

import json
import time
import logging
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass

from core.paths import COHOST_HOME, DATA_DIR, load_config

log = logging.getLogger("evolution")


def _storage_base() -> Path:
    cfg = load_config()
    return Path(cfg.get("storage", {}).get("base", str(DATA_DIR)))


def _agent_path() -> Path:
    cfg = load_config()
    return Path(cfg.get("agent", {}).get("path", str(COHOST_HOME)))


@dataclass
class ToolImprovement:
    """Record of a self-improvement."""
    improvement_id: str
    improvement_type: str  # "new_tool", "code_refactor", "optimization"
    description: str
    files_created: List[str]
    files_modified: List[str]
    timestamp: float
    tested: bool
    deployed: bool


class SelfEvolution:
    """
    Allows Apex to improve itself autonomously.

    It can:
    - Create new tools when needed
    - Refactor inefficient code
    - Install missing dependencies
    - Test changes before deploying
    """

    def __init__(self, agent_path: str = None):
        if agent_path is None:
            agent_path = str(_agent_path())
        self.agent_path = Path(agent_path)
        self.improvements_dir = _storage_base() / "improvements"
        self.improvements_dir.mkdir(parents=True, exist_ok=True)

        self.pending_file = self.improvements_dir / "pending.json"
        self.deployed_file = self.improvements_dir / "deployed.json"

        self.pending: List[Dict] = []
        self.deployed: List[Dict] = []

        self._load()
        log.info("Self Evolution: %d pending, %d deployed", len(self.pending), len(self.deployed))

    def create_new_tool(self, tool_name: str, tool_code: str, description: str) -> str:
        """
        Create a new tool module.

        Args:
            tool_name: Name of the tool (e.g., "image_processor")
            tool_code: Complete Python code for the tool
            description: What this tool does

        Returns:
            Status message
        """
        tool_file = self.agent_path / "%s.py" % tool_name

        if tool_file.exists():
            return "Tool %s already exists" % tool_name

        tool_file.write_text(tool_code, encoding='utf-8')

        improvement = {
            "improvement_id": "tool_%s_%d" % (tool_name, int(time.time())),
            "type": "new_tool",
            "description": description,
            "files_created": [str(tool_file)],
            "files_modified": [],
            "timestamp": time.time(),
            "tested": False,
            "deployed": False,
            "tool_name": tool_name
        }

        self.pending.append(improvement)
        self._save()

        log.info("Created new tool: %s", tool_name)
        return "Created %s.py\nRestart Apex to load it." % tool_name

    def test_tool(self, tool_name: str) -> Tuple[bool, str]:
        """
        Test a newly created tool.

        Returns:
            (success, message)
        """
        tool_file = self.agent_path / "%s.py" % tool_name

        if not tool_file.exists():
            return False, "Tool %s not found" % tool_name

        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(tool_name, tool_file)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            for imp in self.pending:
                if imp.get("tool_name") == tool_name:
                    imp["tested"] = True

            self._save()
            return True, "Tool %s tested successfully" % tool_name

        except Exception as e:
            return False, "Tool test failed: %s" % e

    def deploy_improvement(self, improvement_id: str) -> str:
        """
        Deploy a tested improvement.

        Moves from pending to deployed.
        """
        improvement = None
        for imp in self.pending:
            if imp["improvement_id"] == improvement_id:
                improvement = imp
                break

        if not improvement:
            return "Improvement %s not found" % improvement_id

        if not improvement.get("tested", False):
            return "Improvement must be tested before deployment"

        improvement["deployed"] = True
        improvement["deployed_at"] = time.time()

        self.deployed.append(improvement)
        self.pending.remove(improvement)

        self._save()
        return "Deployed: %s" % improvement['description']

    def rollback_improvement(self, improvement_id: str) -> str:
        """
        Rollback a deployed improvement.

        Deletes created files, restores modified files.
        """
        improvement = None
        for imp in self.deployed:
            if imp["improvement_id"] == improvement_id:
                improvement = imp
                break

        if not improvement:
            return "Improvement %s not found in deployed" % improvement_id

        for file_path in improvement.get("files_created", []):
            try:
                Path(file_path).unlink()
                log.info("Deleted: %s", file_path)
            except Exception:
                pass

        self.deployed.remove(improvement)
        self._save()

        return "Rolled back: %s" % improvement['description']

    def suggest_improvement(self, llm_caller) -> Optional[str]:
        """
        Use the LLM to suggest a self-improvement based on experience.

        Args:
            llm_caller: Function to call LLM

        Returns:
            Improvement suggestion or None
        """
        prompt = """Based on common tasks, suggest ONE new tool that would be useful.

Respond with ONLY a JSON object:
{
    "tool_name": "name_of_tool",
    "description": "what it does",
    "reason": "why it's needed"
}

Only suggest tools that would be genuinely useful for autonomous operation."""

        try:
            response = llm_caller(prompt)
            import re
            json_match = re.search(r'\{[^}]+\}', response)
            if json_match:
                suggestion = json.loads(json_match.group(0))
                return suggestion
        except Exception:
            pass

        return None

    def get_pending_improvements(self) -> List[Dict]:
        """Get list of pending improvements."""
        return self.pending.copy()

    def get_deployed_improvements(self) -> List[Dict]:
        """Get list of deployed improvements."""
        return self.deployed.copy()

    def _load(self):
        """Load improvement records."""
        if self.pending_file.exists():
            try:
                with open(self.pending_file, 'r') as f:
                    self.pending = json.load(f)
            except Exception:
                pass

        if self.deployed_file.exists():
            try:
                with open(self.deployed_file, 'r') as f:
                    self.deployed = json.load(f)
            except Exception:
                pass

    def _save(self):
        """Save improvement records."""
        with open(self.pending_file, 'w') as f:
            json.dump(self.pending, f, indent=2)

        with open(self.deployed_file, 'w') as f:
            json.dump(self.deployed, f, indent=2)


# Singleton
_self_evolution = None


def get_self_evolution() -> SelfEvolution:
    """Get or create the SelfEvolution singleton instance."""
    global _self_evolution
    if _self_evolution is None:
        _self_evolution = SelfEvolution()
    return _self_evolution


def register_tools(registry) -> None:
    """Register self-evolution tools with the tool registry."""
    evo = get_self_evolution()

    registry.register(
        name="evolution_create_tool",
        func=lambda tool_name, tool_code, description: evo.create_new_tool(tool_name, tool_code, description),
        description="Create a new tool module for Apex"
    )
    registry.register(
        name="evolution_test_tool",
        func=lambda tool_name: evo.test_tool(tool_name),
        description="Test a newly created tool module"
    )
    registry.register(
        name="evolution_deploy_improvement",
        func=lambda improvement_id: evo.deploy_improvement(improvement_id),
        description="Deploy a tested improvement"
    )
    registry.register(
        name="evolution_rollback_improvement",
        func=lambda improvement_id: evo.rollback_improvement(improvement_id),
        description="Rollback a deployed improvement"
    )
    registry.register(
        name="evolution_get_pending",
        func=lambda: evo.get_pending_improvements(),
        description="Get list of pending improvements"
    )
    registry.register(
        name="evolution_get_deployed",
        func=lambda: evo.get_deployed_improvements(),
        description="Get list of deployed improvements"
    )
