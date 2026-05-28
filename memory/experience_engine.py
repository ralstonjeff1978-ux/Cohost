"""
EXPERIENCE ENGINE - Learning From Doing
========================================
This is how Apex gets smarter over time WITHOUT retraining weights.

Every task teaches the system something. Every failure is a lesson.
It remembers what works and adapts its approach.

UPDATED: Per-tool reputation tracking for governance layer.
Tool success rates are tracked and used to inform tool selection.
"""

import json
import time
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta
from collections import defaultdict

from core.paths import MEMORY_DIR, load_config

log = logging.getLogger("experience")


def _storage_base() -> Path:
    cfg = load_config()
    return Path(cfg.get("storage", {}).get("memory", str(MEMORY_DIR)))


@dataclass
class TaskExperience:
    """Record of a completed task."""
    task_id: str
    task_description: str
    timestamp: float
    success: bool
    steps_completed: int
    steps_failed: int
    duration: float
    evidence: Dict[str, Any]
    failure_reason: Optional[str] = None
    patterns_learned: List[str] = field(default_factory=list)


@dataclass
class Pattern:
    """A learned pattern from experience."""
    pattern_id: str
    description: str
    context: str
    approach: str
    success_rate: float
    usage_count: int
    created_at: float
    last_used: float
    confidence: float


class ExperienceEngine:
    """Learn from every task to improve future performance."""

    def __init__(self, storage_path: str = None):
        if storage_path is None:
            storage_path = str(_storage_base() / "experience_data")
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)

        self.tasks_file = self.storage_path / "task_history.json"
        self.patterns_file = self.storage_path / "learned_patterns.json"
        self.tool_reputation_file = self.storage_path / "tool_reputation.json"

        self.task_history: List[Dict] = []
        self.patterns: Dict[str, Dict] = {}
        self.tool_reputation: Dict[str, Dict] = {}

        self._load_all()
        log.info(
            "Experience Engine: %s tasks, %s patterns, %s tools tracked",
            len(self.task_history),
            len(self.patterns),
            len(self.tool_reputation),
        )

    def record_task(self, task_result: Dict[str, Any], task_description: str) -> None:
        """Record a completed task and learn from it."""
        task_id = "task_%s" % int(time.time())

        experience = {
            "task_id": task_id,
            "description": task_description,
            "timestamp": time.time(),
            "success": task_result.get("success", False),
            "steps_completed": task_result.get("steps_completed", 0),
            "steps_failed": task_result.get("steps_failed", 0),
            "duration": task_result.get("duration", 0),
            "evidence": task_result.get("evidence", {}),
            "failure_reason": task_result.get("failure_reason") or task_result.get("error")
        }

        self.task_history.append(experience)

        if experience["success"]:
            self._extract_success_pattern(experience)

        self._save_all()
        log.info("Recorded: %s (%s)", task_id, "success" if experience["success"] else "failed")

    # ---- Tool Reputation System -----------------------------------------------

    def record_tool_use(self, tool_name: str, success: bool,
                        duration_ms: float = 0, context: str = "") -> None:
        """
        Record the outcome of a tool call.
        Updates running success rate, call count, and average duration.
        Called automatically by the tool execution engine.
        """
        if tool_name not in self.tool_reputation:
            self.tool_reputation[tool_name] = {
                "tool_name": tool_name,
                "total_calls": 0,
                "successes": 0,
                "failures": 0,
                "success_rate": 1.0,
                "avg_duration_ms": 0,
                "total_duration_ms": 0,
                "last_used": time.time(),
                "last_success": None,
                "last_failure": None,
                "consecutive_failures": 0,
                "reputation_score": 1.0,
                "first_seen": time.time()
            }

        rep = self.tool_reputation[tool_name]
        rep["total_calls"] += 1
        rep["last_used"] = time.time()
        rep["total_duration_ms"] += duration_ms
        rep["avg_duration_ms"] = rep["total_duration_ms"] / rep["total_calls"]

        if success:
            rep["successes"] += 1
            rep["last_success"] = time.time()
            rep["consecutive_failures"] = 0
        else:
            rep["failures"] += 1
            rep["last_failure"] = time.time()
            rep["consecutive_failures"] = rep.get("consecutive_failures", 0) + 1

        total = rep["total_calls"]
        if total <= 10:
            rep["success_rate"] = rep["successes"] / total
        else:
            old_rate = rep["success_rate"]
            new_outcome = 1.0 if success else 0.0
            rep["success_rate"] = (old_rate * 0.85) + (new_outcome * 0.15)

        consecutive_penalty = min(rep["consecutive_failures"] * 0.1, 0.5)
        rep["reputation_score"] = max(0.0, rep["success_rate"] - consecutive_penalty)

        self._save_tool_reputation()

    def get_tool_reputation(self, tool_name: str) -> Dict:
        """Get reputation data for a specific tool."""
        return self.tool_reputation.get(tool_name, {
            "tool_name": tool_name,
            "total_calls": 0,
            "success_rate": 1.0,
            "reputation_score": 1.0,
            "consecutive_failures": 0
        })

    def get_best_alternative(self, failed_tool: str, alternatives: List[str]) -> Optional[str]:
        """
        Given a failed tool and a list of alternatives,
        return the highest-reputation alternative.
        """
        if not alternatives:
            return None

        scored = []
        for alt in alternatives:
            rep = self.get_tool_reputation(alt)
            score = rep.get("reputation_score", 1.0)
            call_bonus = min(rep.get("total_calls", 0) / 100, 0.1)
            scored.append((alt, score + call_bonus))

        scored.sort(key=lambda x: x[1], reverse=True)
        best = scored[0][0]
        best_score = scored[0][1]

        if best_score > 0.3:
            return best
        return None

    def get_reputation_report(self) -> str:
        """Human-readable tool reputation summary."""
        if not self.tool_reputation:
            return "No tool reputation data yet."

        lines = ["TOOL REPUTATION REPORT", "=" * 40]
        sorted_tools = sorted(self.tool_reputation.values(),
                               key=lambda x: x["total_calls"], reverse=True)

        for rep in sorted_tools:
            name = rep["tool_name"]
            rate = rep["success_rate"]
            score = rep["reputation_score"]
            calls = rep["total_calls"]
            cons_fail = rep.get("consecutive_failures", 0)

            bar = "+" * int(rate * 10) + "-" * (10 - int(rate * 10))
            status = "!" if cons_fail >= 2 else "ok"
            lines.append("  [%s] %-22s %s %.0f%% (%d calls, score=%.2f)" % (
                status, name, bar, rate * 100, calls, score))

        return "\n".join(lines)

    def get_low_reputation_tools(self, threshold: float = 0.5) -> List[str]:
        """Return tools with reputation below threshold."""
        return [
            name for name, rep in self.tool_reputation.items()
            if rep.get("reputation_score", 1.0) < threshold
            and rep.get("total_calls", 0) >= 3
        ]

    def get_confidence_for_task(self, task_description: str,
                                tools_to_use: List[str]) -> float:
        """
        Estimate agent confidence for a task based on:
        - Pattern match to past tasks
        - Reputation of tools likely to be needed
        """
        patterns = self.get_relevant_patterns(task_description)
        pattern_confidence = 0.5
        if patterns:
            best_pattern = patterns[0]
            pattern_confidence = min(best_pattern.get("success_rate", 0.5), 1.0)

        if tools_to_use:
            tool_scores = [
                self.get_tool_reputation(t).get("reputation_score", 0.8)
                for t in tools_to_use
            ]
            tool_confidence = sum(tool_scores) / len(tool_scores)
        else:
            tool_confidence = 0.8

        combined = (pattern_confidence * 0.4) + (tool_confidence * 0.6)
        return round(combined, 2)

    # ---- Core learning methods ------------------------------------------------

    def _extract_success_pattern(self, experience: Dict) -> None:
        """Extract a success pattern from experience."""
        task_type = self._classify_task(experience["description"])
        pattern_id = "pattern_%s" % task_type

        if pattern_id in self.patterns:
            p = self.patterns[pattern_id]
            p["count"] += 1
            p["success_rate"] = (p["success_rate"] * (p["count"] - 1) + 1.0) / p["count"]
            p["last_used"] = time.time()
        else:
            self.patterns[pattern_id] = {
                "pattern_id": pattern_id,
                "task_type": task_type,
                "description": "Successful approach for %s" % task_type,
                "success_rate": 1.0,
                "count": 1,
                "created": time.time(),
                "last_used": time.time()
            }

    def _classify_task(self, description: str) -> str:
        """Classify task type from description."""
        desc_lower = description.lower()
        if "python" in desc_lower and "script" in desc_lower:
            return "python_script"
        elif "app" in desc_lower or "application" in desc_lower:
            return "app_creation"
        elif "file" in desc_lower and "create" in desc_lower:
            return "file_creation"
        elif "install" in desc_lower:
            return "package_installation"
        elif "screen" in desc_lower or "click" in desc_lower or "type" in desc_lower:
            return "screen_control"
        elif "chat" in desc_lower or "converse" in desc_lower:
            return "conversation"
        elif "test" in desc_lower or "exam" in desc_lower:
            return "exam_task"
        else:
            return "general_task"

    def get_relevant_patterns(self, task_description: str) -> List[Dict]:
        """Get patterns relevant to current task."""
        task_type = self._classify_task(task_description)
        relevant = [
            p for p in self.patterns.values()
            if p["task_type"] == task_type and p["success_rate"] > 0.7
        ]
        relevant.sort(key=lambda x: x["success_rate"], reverse=True)
        return relevant[:3]

    def get_statistics(self) -> Dict[str, Any]:
        """Get learning statistics."""
        if not self.task_history:
            return {"total_tasks": 0, "success_rate": 0, "recent_tasks": 0,
                    "recent_success_rate": 0, "patterns_learned": 0, "avg_duration": 0}

        total = len(self.task_history)
        successes = sum(1 for t in self.task_history if t["success"])
        recent = [t for t in self.task_history if time.time() - t["timestamp"] < 7 * 24 * 3600]
        recent_success = sum(1 for t in recent if t["success"]) if recent else 0

        return {
            "total_tasks": total,
            "success_rate": successes / total if total > 0 else 0,
            "recent_tasks": len(recent),
            "recent_success_rate": recent_success / len(recent) if recent else 0,
            "patterns_learned": len(self.patterns),
            "avg_duration": sum(t["duration"] for t in self.task_history) / total if total > 0 else 0,
            "tools_tracked": len(self.tool_reputation),
            "low_reputation_tools": self.get_low_reputation_tools()
        }

    # ---- Persistence ----------------------------------------------------------

    def _load_all(self):
        """Load persisted data."""
        if self.tasks_file.exists():
            try:
                with open(self.tasks_file, "r") as f:
                    self.task_history = json.load(f)
            except Exception:
                pass

        if self.patterns_file.exists():
            try:
                with open(self.patterns_file, "r") as f:
                    self.patterns = json.load(f)
            except Exception:
                pass

        if self.tool_reputation_file.exists():
            try:
                with open(self.tool_reputation_file, "r") as f:
                    self.tool_reputation = json.load(f)
            except Exception:
                pass

    def _save_all(self):
        """Save all data to disk."""
        with open(self.tasks_file, "w") as f:
            json.dump(self.task_history, f, indent=2)
        with open(self.patterns_file, "w") as f:
            json.dump(self.patterns, f, indent=2)
        self._save_tool_reputation()

    def _save_tool_reputation(self):
        """Save tool reputation data."""
        try:
            with open(self.tool_reputation_file, "w") as f:
                json.dump(self.tool_reputation, f, indent=2)
        except Exception as e:
            log.warning("Could not save tool reputation: %s", e)


# Singleton
_experience_engine = None


def get_experience_engine() -> ExperienceEngine:
    global _experience_engine
    if _experience_engine is None:
        _experience_engine = ExperienceEngine()
    return _experience_engine


# -----------------------------
# TOOL REGISTRATION
# -----------------------------
def register_tools(registry) -> None:
    registry.register("experience_record_task", get_experience_engine().record_task)
    registry.register("experience_record_tool_use", get_experience_engine().record_tool_use)
    registry.register("experience_get_reputation", get_experience_engine().get_tool_reputation)
    registry.register("experience_get_statistics", get_experience_engine().get_statistics)
    registry.register("experience_get_patterns", get_experience_engine().get_relevant_patterns)
    registry.register("experience_reputation_report", get_experience_engine().get_reputation_report)
