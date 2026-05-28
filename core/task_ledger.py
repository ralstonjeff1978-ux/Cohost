"""
TASK LEDGER - Governance & Accountability Layer
================================================
Full audit trail of every agent action and decision.

Every action is logged. Every decision is auditable.
Authority, responsibility, and accountability are tracked at every step.

Features:
- Full audit trail of every tool call and decision
- Delegation chain tracking (who decided what and why)
- Confidence scoring per decision
- Escalation records (when the agent requested user guidance)
- Failure analysis and recovery tracking
- Exportable reports

Storage path is read from core/config.yaml (storage.logs).
"""

import json
import time
import logging
import threading
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict, field
from datetime import datetime

from core.paths import LOGS_DIR, load_config as _load_config

log = logging.getLogger("task_ledger")


def _ledger_storage_path() -> Path:
    cfg = _load_config()
    # Dedicated ledger sub-directory under the configured logs path
    logs = cfg.get("storage", {}).get("logs", str(LOGS_DIR))
    return Path(logs) / "ledger"

def _agent_name() -> str:
    cfg = _load_config()
    return cfg.get("agent", {}).get("name", "Apex")

# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class LedgerEntry:
    """A single auditable action record."""
    entry_id:             str
    timestamp:            float
    session_id:           str
    entry_type:           str            # tool_call | decision | escalation | recovery | task_start | task_end
    actor:                str            # agent name | user | system
    action:               str            # what was done
    target:               str            # tool name, task name, etc.
    args:                 List[Any]
    outcome:              str            # success | failure | escalated | recovered
    result_summary:       str
    confidence:           float          # 0.0–1.0
    duration_ms:          float
    parent_task_id:       str
    reasoning:            str
    alternatives_tried:   List[str] = field(default_factory=list)
    escalation_required:  bool = False
    escalation_reason:    str = ""


# ── Ledger ─────────────────────────────────────────────────────────────────────

class TaskLedger:
    """
    Maintains a full audit trail of all agent actions.
    Implements accountability chain tracking per delegation governance principles.
    """

    def __init__(self, storage_path: Optional[str] = None):
        """
        Args:
            storage_path: Override the ledger directory.
                          Defaults to storage.logs/ledger from config.yaml.
        """
        self.storage_path = Path(storage_path) if storage_path else _ledger_storage_path()
        self.storage_path.mkdir(parents=True, exist_ok=True)

        self._agent_name    = _agent_name()
        self.ledger_file    = self.storage_path / "action_ledger.jsonl"
        self.session_file   = self.storage_path / "sessions.json"

        self._lock              = threading.Lock()
        self._session_id        = f"session_{int(time.time())}"
        self._current_task_id   = None
        self._entry_counter     = 0
        self._sessions: List[Dict] = []

        self._load_sessions()
        self._start_session()
        log.info("Task Ledger initialised — session: %s", self._session_id)

    # ── Session management ─────────────────────────────────────────────────────

    def _load_sessions(self):
        if self.session_file.exists():
            try:
                with open(self.session_file, "r", encoding="utf-8") as f:
                    self._sessions = json.load(f)
            except Exception:
                self._sessions = []

    def _start_session(self):
        session = {
            "session_id": self._session_id,
            "started":       time.time(),
            "started_human": datetime.now().isoformat(),
            "entries":    0,
            "tasks":      0,
            "escalations": 0,
            "failures":   0,
            "recoveries": 0,
        }
        self._sessions.append(session)
        self._save_sessions()

    def _save_sessions(self):
        try:
            with open(self.session_file, "w", encoding="utf-8") as f:
                json.dump(self._sessions[-50:], f, indent=2)   # keep last 50
        except Exception as e:
            log.warning("Could not save sessions: %s", e)

    def _generate_entry_id(self) -> str:
        self._entry_counter += 1
        return f"{self._session_id}_e{self._entry_counter:04d}"

    # ── Public logging API ─────────────────────────────────────────────────────

    def start_task(self, task_description: str, initiated_by: str = "user") -> str:
        """Record the start of a new task. Returns task_id."""
        task_id = f"task_{int(time.time())}_{self._entry_counter}"
        self._current_task_id = task_id

        entry = LedgerEntry(
            entry_id       = self._generate_entry_id(),
            timestamp      = time.time(),
            session_id     = self._session_id,
            entry_type     = "task_start",
            actor          = initiated_by,
            action         = "initiate_task",
            target         = task_description[:100],
            args           = [],
            outcome        = "started",
            result_summary = f"Task initiated: {task_description[:80]}",
            confidence     = 1.0,
            duration_ms    = 0,
            parent_task_id = task_id,
            reasoning      = f"Initiated by {initiated_by}",
        )
        self._write_entry(entry)

        if self._sessions:
            self._sessions[-1]["tasks"] = self._sessions[-1].get("tasks", 0) + 1
            self._save_sessions()

        return task_id

    def log_tool_call(self, tool_name: str, args: List[Any], success: bool,
                      result_summary: str, duration_ms: float,
                      confidence: float = 0.8, reasoning: str = "",
                      alternatives_tried: List[str] = None) -> str:
        """Log a tool execution with full context."""
        entry = LedgerEntry(
            entry_id          = self._generate_entry_id(),
            timestamp         = time.time(),
            session_id        = self._session_id,
            entry_type        = "tool_call",
            actor             = self._agent_name,
            action            = f"call_tool:{tool_name}",
            target            = tool_name,
            args              = [str(a)[:50] for a in args],
            outcome           = "success" if success else "failure",
            result_summary    = result_summary[:200],
            confidence        = confidence,
            duration_ms       = duration_ms,
            parent_task_id    = self._current_task_id or "no_task",
            reasoning         = reasoning or f"Executing {tool_name}",
            alternatives_tried = alternatives_tried or [],
        )
        self._write_entry(entry)

        if not success and self._sessions:
            self._sessions[-1]["failures"] = self._sessions[-1].get("failures", 0) + 1
            self._save_sessions()

        return entry.entry_id

    def log_decision(self, decision: str, reasoning: str, confidence: float,
                     alternatives: List[str] = None) -> str:
        """Log a routing or strategic decision."""
        entry = LedgerEntry(
            entry_id       = self._generate_entry_id(),
            timestamp      = time.time(),
            session_id     = self._session_id,
            entry_type     = "decision",
            actor          = self._agent_name,
            action         = "decide",
            target         = decision,
            args           = alternatives or [],
            outcome        = "decided",
            result_summary = f"Decision: {decision} (confidence: {confidence:.0%})",
            confidence     = confidence,
            duration_ms    = 0,
            parent_task_id = self._current_task_id or "no_task",
            reasoning      = reasoning,
        )
        self._write_entry(entry)
        return entry.entry_id

    def log_escalation(self, reason: str, context: str, confidence: float) -> str:
        """Log when the agent escalates to the user for guidance."""
        entry = LedgerEntry(
            entry_id           = self._generate_entry_id(),
            timestamp          = time.time(),
            session_id         = self._session_id,
            entry_type         = "escalation",
            actor              = self._agent_name,
            action             = "escalate_to_user",
            target             = "user",
            args               = [],
            outcome            = "escalated",
            result_summary     = f"Escalated: {reason[:100]}",
            confidence         = confidence,
            duration_ms        = 0,
            parent_task_id     = self._current_task_id or "no_task",
            reasoning          = reason,
            escalation_required = True,
            escalation_reason  = reason,
        )
        self._write_entry(entry)

        if self._sessions:
            self._sessions[-1]["escalations"] = self._sessions[-1].get("escalations", 0) + 1
            self._save_sessions()

        return entry.entry_id

    def log_recovery(self, failed_tool: str, recovery_tool: str,
                     success: bool, reasoning: str) -> str:
        """Log a failure recovery attempt."""
        entry = LedgerEntry(
            entry_id          = self._generate_entry_id(),
            timestamp         = time.time(),
            session_id        = self._session_id,
            entry_type        = "recovery",
            actor             = self._agent_name,
            action            = f"recover:{failed_tool}->{recovery_tool}",
            target            = recovery_tool,
            args              = [failed_tool],
            outcome           = "recovered" if success else "recovery_failed",
            result_summary    = (
                f"Recovery from {failed_tool} using {recovery_tool}: "
                f"{'OK' if success else 'FAILED'}"
            ),
            confidence        = 0.5,
            duration_ms       = 0,
            parent_task_id    = self._current_task_id or "no_task",
            reasoning         = reasoning,
            alternatives_tried = [failed_tool],
        )
        self._write_entry(entry)

        if success and self._sessions:
            self._sessions[-1]["recoveries"] = self._sessions[-1].get("recoveries", 0) + 1
            self._save_sessions()

        return entry.entry_id

    def end_task(self, task_id: str, success: bool, summary: str):
        """Record task completion."""
        entry = LedgerEntry(
            entry_id       = self._generate_entry_id(),
            timestamp      = time.time(),
            session_id     = self._session_id,
            entry_type     = "task_end",
            actor          = self._agent_name,
            action         = "complete_task",
            target         = task_id,
            args           = [],
            outcome        = "success" if success else "failure",
            result_summary = summary[:200],
            confidence     = 1.0,
            duration_ms    = 0,
            parent_task_id = task_id,
            reasoning      = "Task completed",
        )
        self._write_entry(entry)

        if self._current_task_id == task_id:
            self._current_task_id = None

    # ── Read / reporting ───────────────────────────────────────────────────────

    def get_recent_entries(self, n: int = 20) -> List[Dict]:
        """Return the N most recent ledger entries."""
        entries = []
        try:
            with open(self.ledger_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entries.append(json.loads(line))
                        except Exception:
                            pass
        except FileNotFoundError:
            pass
        return entries[-n:]

    def get_tool_stats(self) -> Dict[str, Dict]:
        """Aggregate tool success/failure stats across the full ledger."""
        stats: Dict[str, Dict] = {}
        try:
            with open(self.ledger_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if entry.get("entry_type") != "tool_call":
                            continue
                        tool = entry["target"]
                        if tool not in stats:
                            stats[tool] = {
                                "calls": 0, "successes": 0, "failures": 0,
                                "avg_duration_ms": 0, "total_duration": 0,
                            }
                        stats[tool]["calls"] += 1
                        if entry["outcome"] == "success":
                            stats[tool]["successes"] += 1
                        else:
                            stats[tool]["failures"] += 1
                        stats[tool]["total_duration"] += entry.get("duration_ms", 0)
                        stats[tool]["avg_duration_ms"] = (
                            stats[tool]["total_duration"] / stats[tool]["calls"]
                        )
                    except Exception:
                        pass
        except FileNotFoundError:
            pass

        for s in stats.values():
            s["success_rate"] = s["successes"] / s["calls"] if s["calls"] > 0 else 0.0

        return stats

    def get_session_summary(self) -> str:
        """Human-readable summary of the current session."""
        if not self._sessions:
            return "No session data"
        s        = self._sessions[-1]
        duration = time.time() - s.get("started", time.time())
        return (
            f"Session:          {self._session_id}\n"
            f"Duration:         {duration / 60:.1f} minutes\n"
            f"Actions logged:   {s.get('entries', 0)}\n"
            f"Tasks:            {s.get('tasks', 0)}\n"
            f"Failures:         {s.get('failures', 0)}\n"
            f"Recoveries:       {s.get('recoveries', 0)}\n"
            f"Escalations:      {s.get('escalations', 0)}"
        )

    def get_accountability_report(self, last_n_entries: int = 50) -> str:
        """Generate a governance accountability report."""
        entries    = self.get_recent_entries(last_n_entries)
        tool_stats = self.get_tool_stats()

        report  = f"ACCOUNTABILITY REPORT\n{'=' * 40}\n"
        report += f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        report += self.get_session_summary() + "\n\n"

        report += "TOOL RELIABILITY:\n"
        for tool, stats in sorted(tool_stats.items(),
                                  key=lambda x: x[1]["calls"], reverse=True):
            filled  = int(stats["success_rate"] * 10)
            bar     = "█" * filled + "░" * (10 - filled)
            report += (
                f"  {tool:<20} {bar} "
                f"{stats['success_rate']:.0%} ({stats['calls']} calls)\n"
            )

        escalations = [e for e in entries if e.get("entry_type") == "escalation"]
        if escalations:
            report += f"\nESCALATIONS ({len(escalations)}):\n"
            for e in escalations[-5:]:
                ts      = datetime.fromtimestamp(e["timestamp"]).strftime("%H:%M:%S")
                report += f"  [{ts}] {e.get('reasoning', '')[:80]}\n"

        failures = [e for e in entries if e.get("outcome") == "failure"]
        if failures:
            report += f"\nRECENT FAILURES ({len(failures)}):\n"
            for e in failures[-5:]:
                ts      = datetime.fromtimestamp(e["timestamp"]).strftime("%H:%M:%S")
                report += (
                    f"  [{ts}] {e.get('target', '')} — "
                    f"{e.get('result_summary', '')[:60]}\n"
                )

        return report

    def export_json(self, filepath: str = None) -> str:
        """Export the full ledger to a JSON file. Returns the path written."""
        if not filepath:
            filepath = str(self.storage_path / f"export_{int(time.time())}.json")
        entries = self.get_recent_entries(10000)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "session":  self._session_id,
                    "exported": datetime.now().isoformat(),
                    "entries":  entries,
                },
                f, indent=2,
            )
        return filepath

    # ── Internal ───────────────────────────────────────────────────────────────

    def _write_entry(self, entry: LedgerEntry):
        """Write a ledger entry to disk. Thread-safe."""
        with self._lock:
            try:
                with open(self.ledger_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(asdict(entry)) + "\n")
                if self._sessions:
                    self._sessions[-1]["entries"] = (
                        self._sessions[-1].get("entries", 0) + 1
                    )
            except Exception as e:
                log.warning("Ledger write error: %s", e)


# ── Singleton ──────────────────────────────────────────────────────────────────

_ledger_instance: Optional[TaskLedger] = None

def get_ledger() -> TaskLedger:
    """Return the process-level TaskLedger singleton, creating it if needed."""
    global _ledger_instance
    if _ledger_instance is None:
        _ledger_instance = TaskLedger()   # path read from config inside __init__
    return _ledger_instance
