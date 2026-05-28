"""
MEMORY TOOLS
====================================================
The Core Long-Term Memory System for Apex.
Handles decision logging, deep search, project tracking,
and surface (short-term) interaction logs.

FEATURES:
- Windows-Compatible File Locking (Concurrency Safe)
- Secret Redaction (Security)
- Atomic Writes
- Advanced Skill Tracking (Mastery Levels)
- Project & Decision Management
- Web Research
"""

import os
import json
import re
import time
import errno
import datetime
import webbrowser
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple

from core.paths import MEMORY_DIR, load_config

# -----------------------------
# CONFIG
# -----------------------------


def _storage_base() -> Path:
    cfg = load_config()
    return Path(cfg.get("storage", {}).get("memory", str(MEMORY_DIR)))


def _init_paths():
    base = _storage_base()
    deep = base / "deep"
    return base, deep


_MEMORY_BASE, _DEEP_BASE = _init_paths()

MEMORY_DIR = str(os.environ.get("APEX_MEMORY_DIR", str(_MEMORY_BASE)))
DEEP_DIR = str(os.environ.get("APEX_DEEP_DIR", str(_DEEP_BASE)))

SURFACE_FILE = os.path.join(MEMORY_DIR, "surface.txt")
RAW_LOG_FILE = os.path.join(DEEP_DIR, "thread_raw.log")
DECISIONS_FILE = os.path.join(DEEP_DIR, "decisions.jsonl")
LESSONS_FILE = os.path.join(DEEP_DIR, "lessons.jsonl")
SUMMARIES_FILE = os.path.join(DEEP_DIR, "summaries.jsonl")
SKILLS_FILE = os.path.join(DEEP_DIR, "skills.jsonl")
PROJECTS_FILE = os.path.join(DEEP_DIR, "projects.jsonl")
ERROR_PATTERNS_FILE = os.path.join(DEEP_DIR, "error_patterns.jsonl")

# Safety / hygiene
SURFACE_MAX_LINES = 15
RAW_MAX_BYTES_HINT = 25_000_000
DEFAULT_ENCODING = "utf-8"

# Ensure directories exist
os.makedirs(DEEP_DIR, exist_ok=True)

# -----------------------------
# INTERNAL: locking + atomic IO (WINDOWS FIXED)
# -----------------------------
class _FileLock:
    """Windows-compatible advisory lock using msvcrt"""
    def __init__(self, lock_path: str, timeout: float = 5.0, poll: float = 0.05):
        self.lock_path = lock_path
        self.timeout = timeout
        self.poll = poll
        self._fh = None

    def __enter__(self):
        try:
            import msvcrt
        except ImportError:
            return self

        os.makedirs(os.path.dirname(self.lock_path), exist_ok=True)

        self._fh = open(self.lock_path, "a+", encoding=DEFAULT_ENCODING)

        start = time.time()
        while True:
            try:
                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
                return self
            except (OSError, IOError):
                if time.time() - start > self.timeout:
                    raise TimeoutError("Timed out acquiring lock: %s" % self.lock_path)
                time.sleep(self.poll)

    def __exit__(self, exc_type, exc, tb):
        try:
            import msvcrt
            if self._fh:
                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
        except Exception:
            pass
        finally:
            try:
                if self._fh:
                    self._fh.close()
            except Exception:
                pass


def _lock_for(path: str) -> str:
    return path + ".lock"


def _now_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _safe_json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _atomic_write_text(path: str, text: str) -> None:
    """Atomic write: write temp then replace atomically"""
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    tmp = "%s.tmp.%s" % (path, os.getpid())
    try:
        with open(tmp, "w", encoding=DEFAULT_ENCODING) as f:
            f.write(text)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except:
                pass
        raise


def _append_line(path: str, line: str) -> None:
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    with open(path, "a", encoding=DEFAULT_ENCODING) as f:
        f.write(line.rstrip("\n") + "\n")


def _redact(text: str) -> str:
    """Minimal secret redaction"""
    if not text:
        return text
    text = re.sub(r"\b(sk-[A-Za-z0-9]{20,})\b", "sk-<REDACTED>", text)
    text = re.sub(r"\b(AKIA[0-9A-Z]{16})\b", "<AWS_KEY_REDACTED>", text)
    text = re.sub(r"\b(token|api[_-]?key|password|secret)\s*[:=]\s*([^\s]+)", r"\1=<REDACTED>", text, flags=re.I)
    return text


def _read_lines_tail(path: str, max_lines: int = 2000) -> List[str]:
    """Efficient tail read"""
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding=DEFAULT_ENCODING, errors="ignore") as f:
            lines = f.readlines()
        return lines[-max_lines:]
    except Exception:
        return []


def _next_jsonl_id(path: str) -> str:
    """Generates a monotonic 5-digit ID based on line count"""
    n = 0
    if os.path.exists(path):
        with open(path, "r", encoding=DEFAULT_ENCODING, errors="ignore") as f:
            for _ in f:
                n += 1
    return "%05d" % (n + 1)


def _read_jsonl(path: str, max_lines: int = 5000) -> List[Dict[str, Any]]:
    """Read JSONL file into list of dicts"""
    if not os.path.exists(path):
        return []

    items = []
    try:
        for line in _read_lines_tail(path, max_lines):
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except Exception:
                continue
    except Exception:
        pass

    return items


# -----------------------------
# PUBLIC: surface + raw logging
# -----------------------------
def append_to_surface(role: str, text: str) -> None:
    """Refreshes Surface memory (short-term rolling window)"""
    role = (role or "").strip()
    text = _redact((text or "").strip())
    ts = datetime.datetime.now().strftime("%H:%M")

    with _FileLock(_lock_for(SURFACE_FILE), timeout=5.0):
        lines = []
        if os.path.exists(SURFACE_FILE):
            try:
                with open(SURFACE_FILE, "r", encoding=DEFAULT_ENCODING, errors="ignore") as f:
                    lines = f.readlines()
            except Exception:
                lines = []

        lines.append("[%s] %s: %s\n" % (ts, role, text))
        if len(lines) > SURFACE_MAX_LINES:
            lines = lines[-SURFACE_MAX_LINES:]

        _atomic_write_text(SURFACE_FILE, "".join(lines))


def log_interaction_raw(role: str, text: str) -> None:
    """Appends to Infinite Raw Log (audit trail)"""
    role = (role or "").strip()
    text = _redact((text or "").strip())
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = "[%s] %s: %s" % (ts, role, text)
    with _FileLock(_lock_for(RAW_LOG_FILE), timeout=5.0):
        _append_line(RAW_LOG_FILE, line)


def read_surface(max_lines: int = 15) -> str:
    """Returns the current Surface buffer"""
    if not os.path.exists(SURFACE_FILE):
        return ""
    try:
        with open(SURFACE_FILE, "r", encoding=DEFAULT_ENCODING, errors="ignore") as f:
            lines = f.readlines()
        return "".join(lines[-max_lines:]).strip()
    except Exception:
        return ""


# -----------------------------
# PUBLIC: Research
# -----------------------------
def research_online(query: str) -> str:
    """Opens a browser tab for the query."""
    try:
        url = "https://search.brave.com/search?q=%s" % query.replace(" ", "+")
        webbrowser.open(url)
        return "Browser opened for: %s" % query
    except Exception as e:
        return "Failed to open browser: %s" % e


# -----------------------------
# PUBLIC: search / evidence
# -----------------------------
def search_deep_memory(query: str, limit: int = 5, use_regex: bool = False) -> str:
    """
    Scans Deep Memory for query string (or regex).
    Returns formatted evidence with IDs.
    """
    query = (query or "").strip()
    if not query:
        return "[SYSTEM] Empty query."

    patt = None
    if use_regex:
        try:
            patt = re.compile(query, flags=re.I)
        except re.error as e:
            return "[SYSTEM] Bad regex: %s" % e

    def _match(s: str) -> bool:
        if patt:
            return bool(patt.search(s))
        return query.lower() in s.lower()

    results: List[str] = []

    # 1) Decisions (highest signal)
    if os.path.exists(DECISIONS_FILE):
        try:
            for line in reversed(_read_lines_tail(DECISIONS_FILE, max_lines=4000)):
                if _match(line):
                    try:
                        entry = json.loads(line)
                        did = entry.get("decision_id", "?")
                        dec = entry.get("decision", "")
                        status = entry.get("status", "active")
                        results.append("[EVIDENCE D_%s] (%s) %s" % (did, status, dec))
                        if len(results) >= limit:
                            return "\n".join(results[:limit])
                    except Exception:
                        continue
        except Exception:
            pass

    # 2) Lessons (what worked/failed)
    if os.path.exists(LESSONS_FILE):
        try:
            for line in reversed(_read_lines_tail(LESSONS_FILE, max_lines=4000)):
                if _match(line):
                    try:
                        entry = json.loads(line)
                        lid = entry.get("lesson_id", "?")
                        text = entry.get("lesson", "")
                        results.append("[EVIDENCE L_%s] %s" % (lid, text))
                        if len(results) >= limit:
                            return "\n".join(results[:limit])
                    except Exception:
                        continue
        except Exception:
            pass

    # 3) Skills (if relevant)
    if os.path.exists(SKILLS_FILE):
        try:
            for line in reversed(_read_lines_tail(SKILLS_FILE, max_lines=1000)):
                if _match(line):
                    try:
                        entry = json.loads(line)
                        sid = entry.get("skill_id", "?")
                        name = entry.get("skill_name", "")
                        level = entry.get("mastery_level", "unknown")
                        results.append("[EVIDENCE S_%s] %s (mastery: %s)" % (sid, name, level))
                        if len(results) >= limit:
                            return "\n".join(results[:limit])
                    except Exception:
                        continue
        except Exception:
            pass

    # 4) Raw transcript (recency-first)
    if os.path.exists(RAW_LOG_FILE):
        try:
            lines = _read_lines_tail(RAW_LOG_FILE, max_lines=25_000)
            found = 0
            for idx, line in enumerate(reversed(lines), start=1):
                if _match(line):
                    results.append("[EVIDENCE T_tail_%s] ...%s..." % (idx, line.strip()))
                    found += 1
                    if found >= limit:
                        break
        except Exception:
            pass

    if not results:
        return "[SYSTEM] No matches found in Deep Memory."
    return "\n".join(results[:limit])


# -----------------------------
# PUBLIC: decisions (ledger)
# -----------------------------
def write_decision(decision_text: str, evidence_ids: Optional[List[str]] = None) -> str:
    """Writes a hard decision to immutable ledger"""
    evidence_ids = evidence_ids or []
    decision_text = (decision_text or "").strip()
    if not decision_text:
        return "D_?????"

    with _FileLock(_lock_for(DECISIONS_FILE), timeout=5.0):
        new_id = _next_jsonl_id(DECISIONS_FILE)
        entry = {
            "decision_id": new_id,
            "ts": _now_iso(),
            "decision": decision_text,
            "evidence_ids": evidence_ids,
            "status": "active",
        }
        _append_line(DECISIONS_FILE, _safe_json_dumps(entry))

    return "D_%s" % new_id


def close_decision(decision_id: str, reason: str = "superseded") -> bool:
    """Marks a decision as closed"""
    did = (decision_id or "").replace("D_", "").strip()
    if not did.isdigit():
        return False

    event = {
        "event": "decision_status_change",
        "decision_id": did,
        "ts": _now_iso(),
        "new_status": "closed",
        "reason": reason,
    }
    with _FileLock(_lock_for(DECISIONS_FILE), timeout=5.0):
        _append_line(DECISIONS_FILE, _safe_json_dumps(event))
    return True


def supersede_decision(old_decision_id: str, new_decision_text: str, evidence_ids: Optional[List[str]] = None) -> str:
    """Closes old decision and writes a new one"""
    old_clean = (old_decision_id or "").replace("D_", "").strip()
    close_decision(old_clean, reason="superseded")
    evidence_ids = (evidence_ids or []) + ["D_%s" % old_clean]
    return write_decision(new_decision_text, evidence_ids=evidence_ids)


# -----------------------------
# PUBLIC: lessons learned
# -----------------------------
def write_lesson(lesson_text: str, evidence_ids: Optional[List[str]] = None, tags: Optional[List[str]] = None) -> str:
    """Writes a 'lesson learned' entry"""
    evidence_ids = evidence_ids or []
    tags = tags or []
    lesson_text = (lesson_text or "").strip()
    if not lesson_text:
        return "L_?????"

    with _FileLock(_lock_for(LESSONS_FILE), timeout=5.0):
        new_id = _next_jsonl_id(LESSONS_FILE)
        entry = {
            "lesson_id": new_id,
            "ts": _now_iso(),
            "lesson": lesson_text,
            "evidence_ids": evidence_ids,
            "tags": tags,
        }
        _append_line(LESSONS_FILE, _safe_json_dumps(entry))

    return "L_%s" % new_id


# -----------------------------
# PUBLIC: summaries
# -----------------------------
def write_summary(title: str, summary_text: str, evidence_ids: Optional[List[str]] = None, tags: Optional[List[str]] = None) -> str:
    """Stores a compact session/task summary"""
    evidence_ids = evidence_ids or []
    tags = tags or []
    title = (title or "").strip()[:120]
    summary_text = (summary_text or "").strip()

    with _FileLock(_lock_for(SUMMARIES_FILE), timeout=5.0):
        new_id = _next_jsonl_id(SUMMARIES_FILE)
        entry = {
            "summary_id": new_id,
            "ts": _now_iso(),
            "title": title,
            "summary": summary_text,
            "evidence_ids": evidence_ids,
            "tags": tags,
        }
        _append_line(SUMMARIES_FILE, _safe_json_dumps(entry))
    return "S_%s" % new_id


# -----------------------------
# SKILL TRACKING
# -----------------------------
def track_skill_attempt(skill_name: str, success: bool, context: str = "", confidence: float = 0.5) -> str:
    """
    Track an attempt at using a skill.
    This builds a history of what works and what doesn't.
    """
    skill_name = (skill_name or "").strip().lower()
    if not skill_name:
        return "SKILL_?????"

    with _FileLock(_lock_for(SKILLS_FILE), timeout=5.0):
        skills = {}
        if os.path.exists(SKILLS_FILE):
            for line in _read_lines_tail(SKILLS_FILE, max_lines=2000):
                try:
                    entry = json.loads(line)
                    if entry.get("skill_name") and "event" not in entry:
                        skills[entry["skill_name"]] = entry
                except:
                    continue

        if skill_name in skills:
            skill = skills[skill_name]
            skill["attempts"] = skill.get("attempts", 0) + 1
            if success:
                skill["successes"] = skill.get("successes", 0) + 1
            else:
                skill["failures"] = skill.get("failures", 0) + 1

            old_conf = skill.get("avg_confidence", 0.5)
            new_conf = (old_conf * 0.9) + (confidence * 0.1)
            skill["avg_confidence"] = round(new_conf, 3)

            success_rate = skill["successes"] / skill["attempts"] if skill["attempts"] > 0 else 0

            if skill["attempts"] < 5:
                mastery = "novice"
            elif success_rate >= 0.85 and skill["attempts"] >= 20:
                mastery = "expert"
            elif success_rate >= 0.70 and skill["attempts"] >= 10:
                mastery = "advanced"
            elif success_rate >= 0.50:
                mastery = "intermediate"
            else:
                mastery = "learning"

            skill["mastery_level"] = mastery
            skill["success_rate"] = round(success_rate, 3)
            skill["last_attempt"] = _now_iso()

            if context:
                if "recent_contexts" not in skill:
                    skill["recent_contexts"] = []
                skill["recent_contexts"].append({
                    "ts": _now_iso(),
                    "success": success,
                    "context": context[:200]
                })
                skill["recent_contexts"] = skill["recent_contexts"][-10:]
        else:
            skill = {
                "skill_id": _next_jsonl_id(SKILLS_FILE),
                "skill_name": skill_name,
                "ts": _now_iso(),
                "attempts": 1,
                "successes": 1 if success else 0,
                "failures": 0 if success else 1,
                "avg_confidence": confidence,
                "success_rate": 1.0 if success else 0.0,
                "mastery_level": "novice",
                "last_attempt": _now_iso(),
                "recent_contexts": [{
                    "ts": _now_iso(),
                    "success": success,
                    "context": context[:200]
                }] if context else []
            }

        _append_line(SKILLS_FILE, _safe_json_dumps(skill))

        return "SKILL_%s" % skill["skill_id"]


def get_skill_status(skill_name: str) -> Optional[Dict[str, Any]]:
    """Get current status of a skill"""
    skill_name = (skill_name or "").strip().lower()
    if not skill_name or not os.path.exists(SKILLS_FILE):
        return None

    for line in reversed(_read_lines_tail(SKILLS_FILE, max_lines=2000)):
        try:
            entry = json.loads(line)
            if entry.get("skill_name") == skill_name and "event" not in entry:
                return entry
        except:
            continue

    return None


def list_weak_skills(min_attempts: int = 5, max_success_rate: float = 0.6) -> List[Dict[str, Any]]:
    """Identify skills that need practice"""
    if not os.path.exists(SKILLS_FILE):
        return []

    weak_skills = []
    skills_seen = set()

    for line in reversed(_read_lines_tail(SKILLS_FILE, max_lines=2000)):
        try:
            entry = json.loads(line)
            skill_name = entry.get("skill_name")

            if not skill_name or skill_name in skills_seen or "event" in entry:
                continue

            skills_seen.add(skill_name)

            attempts = entry.get("attempts", 0)
            success_rate = entry.get("success_rate", 0)

            if attempts >= min_attempts and success_rate <= max_success_rate:
                weak_skills.append(entry)
        except:
            continue

    return sorted(weak_skills, key=lambda x: x.get("success_rate", 1.0))


# -----------------------------
# ERROR PATTERN LEARNING
# -----------------------------
def log_error_pattern(error_type: str, symptom: str, diagnosis: str, solution: str = "") -> str:
    """
    Log an error pattern for future reference.
    This builds diagnostic knowledge over time.
    """
    error_type = (error_type or "").strip()
    symptom = (symptom or "").strip()
    diagnosis = (diagnosis or "").strip()

    if not error_type or not symptom:
        return "ERROR_?????"

    with _FileLock(_lock_for(ERROR_PATTERNS_FILE), timeout=5.0):
        new_id = _next_jsonl_id(ERROR_PATTERNS_FILE)
        entry = {
            "pattern_id": new_id,
            "ts": _now_iso(),
            "error_type": error_type,
            "symptom": symptom,
            "diagnosis": diagnosis,
            "solution": solution,
            "times_seen": 1
        }
        _append_line(ERROR_PATTERNS_FILE, _safe_json_dumps(entry))

    return "ERROR_%s" % new_id


def search_error_patterns(symptom: str, limit: int = 3) -> List[Dict[str, Any]]:
    """Search for similar error patterns we've seen before"""
    symptom = (symptom or "").strip().lower()
    if not symptom or not os.path.exists(ERROR_PATTERNS_FILE):
        return []

    matches = []
    for line in reversed(_read_lines_tail(ERROR_PATTERNS_FILE, max_lines=1000)):
        try:
            entry = json.loads(line)
            symptom_text = entry.get("symptom", "").lower()

            if symptom in symptom_text or symptom_text in symptom:
                matches.append(entry)
                if len(matches) >= limit:
                    break
        except:
            continue

    return matches


# -----------------------------
# PROJECT MANAGEMENT
# -----------------------------
def create_project(project_name: str, project_type: str, goal: str, outline: Optional[List[str]] = None) -> str:
    """
    Create a long-term project (e.g., writing a book, building a system).
    Returns project ID.
    """
    project_name = (project_name or "").strip()
    project_type = (project_type or "").strip()
    goal = (goal or "").strip()

    if not project_name or not goal:
        return "PROJECT_?????"

    with _FileLock(_lock_for(PROJECTS_FILE), timeout=5.0):
        new_id = _next_jsonl_id(PROJECTS_FILE)
        entry = {
            "project_id": new_id,
            "ts": _now_iso(),
            "project_name": project_name,
            "project_type": project_type,
            "goal": goal,
            "status": "active",
            "outline": outline or [],
            "completed_sections": [],
            "current_section": None,
            "progress_percent": 0,
            "metadata": {}
        }
        _append_line(PROJECTS_FILE, _safe_json_dumps(entry))

    return "PROJECT_%s" % new_id


def update_project_progress(project_id: str, completed_section: Optional[str] = None,
                            current_section: Optional[str] = None,
                            progress_percent: Optional[float] = None,
                            metadata_update: Optional[Dict] = None) -> bool:
    """Update project progress"""
    project_id = (project_id or "").replace("PROJECT_", "").strip()
    if not project_id.isdigit():
        return False

    event = {
        "event": "project_progress_update",
        "project_id": project_id,
        "ts": _now_iso(),
    }

    if completed_section:
        event["completed_section"] = completed_section
    if current_section:
        event["current_section"] = current_section
    if progress_percent is not None:
        event["progress_percent"] = progress_percent
    if metadata_update:
        event["metadata_update"] = metadata_update

    with _FileLock(_lock_for(PROJECTS_FILE), timeout=5.0):
        _append_line(PROJECTS_FILE, _safe_json_dumps(event))

    return True


def get_active_projects() -> List[Dict[str, Any]]:
    """Get list of active projects"""
    if not os.path.exists(PROJECTS_FILE):
        return []

    projects = {}

    for line in _read_lines_tail(PROJECTS_FILE, max_lines=5000):
        try:
            entry = json.loads(line)

            if "event" in entry:
                pid = entry.get("project_id")
                if pid in projects:
                    if "completed_section" in entry:
                        if entry["completed_section"] not in projects[pid]["completed_sections"]:
                            projects[pid]["completed_sections"].append(entry["completed_section"])
                    if "current_section" in entry:
                        projects[pid]["current_section"] = entry["current_section"]
                    if "progress_percent" in entry:
                        projects[pid]["progress_percent"] = entry["progress_percent"]
                    if "metadata_update" in entry:
                        projects[pid]["metadata"].update(entry["metadata_update"])
            else:
                pid = entry.get("project_id")
                if pid:
                    projects[pid] = entry
        except:
            continue

    return [p for p in projects.values() if p.get("status") == "active"]


# -----------------------------
# PUBLIC: stats / integrity
# -----------------------------
def get_memory_stats() -> str:
    """Returns formatted string of memory health"""
    stats = []
    stats.append("=== MEMORY INTEGRITY REPORT ===")

    def _file_stat(path: str, label: str) -> None:
        if not os.path.exists(path):
            stats.append("[%-15s] MISSING" % label)
            return
        try:
            size_kb = os.path.getsize(path) / 1024
            count = 0
            with open(path, "r", encoding=DEFAULT_ENCODING, errors="ignore") as f:
                for _ in f:
                    count += 1
            stats.append("[%-15s] Lines: %6d | Size: %8.2f KB | Status: HEALTHY" % (label, count, size_kb))
        except Exception as e:
            stats.append("[%-15s] ERROR: %s" % (label, e))

    _file_stat(RAW_LOG_FILE, "RAW_LOG")
    _file_stat(DECISIONS_FILE, "DECISIONS")
    _file_stat(LESSONS_FILE, "LESSONS")
    _file_stat(SUMMARIES_FILE, "SUMMARIES")
    _file_stat(SKILLS_FILE, "SKILLS")
    _file_stat(PROJECTS_FILE, "PROJECTS")
    _file_stat(ERROR_PATTERNS_FILE, "ERROR_PATTERNS")
    _file_stat(SURFACE_FILE, "SURFACE")

    stats.append("\n=== SKILL MASTERY SUMMARY ===")
    try:
        skills_seen = {}
        if os.path.exists(SKILLS_FILE):
            for line in reversed(_read_lines_tail(SKILLS_FILE, max_lines=500)):
                try:
                    entry = json.loads(line)
                    name = entry.get("skill_name")
                    if name and name not in skills_seen and "event" not in entry:
                        skills_seen[name] = entry
                except:
                    continue

        if skills_seen:
            for skill in sorted(skills_seen.values(), key=lambda x: x.get("mastery_level", ""), reverse=True):
                name = skill.get("skill_name", "unknown")
                level = skill.get("mastery_level", "unknown")
                rate = skill.get("success_rate", 0) * 100
                attempts = skill.get("attempts", 0)
                stats.append("  %-25s | %-12s | %5.1f%% success | %3d attempts" % (name, level, rate, attempts))
        else:
            stats.append("  No skills tracked yet")
    except Exception as e:
        stats.append("  Error reading skills: %s" % e)

    stats.append("\n=== ACTIVE PROJECTS ===")
    try:
        projects = get_active_projects()
        if projects:
            for proj in projects:
                name = proj.get("project_name", "unknown")
                progress = proj.get("progress_percent", 0)
                current = proj.get("current_section", "not started")
                stats.append("  %-30s | %5.1f%% | Current: %s" % (name, progress, current))
        else:
            stats.append("  No active projects")
    except Exception as e:
        stats.append("  Error reading projects: %s" % e)

    return "\n".join(stats)


# -----------------------------
# OPTIONAL: log rotation helper
# -----------------------------
def rotate_raw_log_if_large(max_bytes: int = RAW_MAX_BYTES_HINT) -> Optional[str]:
    """If raw log exceeds max_bytes, rotate it"""
    if not os.path.exists(RAW_LOG_FILE):
        return None
    try:
        size = os.path.getsize(RAW_LOG_FILE)
        if size < max_bytes:
            return None
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        rotated = os.path.join(DEEP_DIR, "thread_raw.%s.log" % ts)
        with _FileLock(_lock_for(RAW_LOG_FILE), timeout=5.0):
            os.replace(RAW_LOG_FILE, rotated)
        return rotated
    except Exception:
        return None


# -----------------------------
# TOOL REGISTRATION
# -----------------------------
def register_tools(registry) -> None:
    registry.register("memory_append_surface", append_to_surface)
    registry.register("memory_log_raw", log_interaction_raw)
    registry.register("memory_read_surface", read_surface)
    registry.register("memory_search_deep", search_deep_memory)
    registry.register("memory_write_decision", write_decision)
    registry.register("memory_close_decision", close_decision)
    registry.register("memory_add_lesson", write_lesson)
    registry.register("memory_read_lessons", lambda limit=20: _read_jsonl(LESSONS_FILE, limit))
    registry.register("memory_add_skill", track_skill_attempt)
    registry.register("memory_read_skills", lambda: list_weak_skills())
    registry.register("memory_add_project", create_project)
    registry.register("memory_read_projects", get_active_projects)
