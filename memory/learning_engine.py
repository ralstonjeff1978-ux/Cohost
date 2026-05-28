"""
LEARNING ENGINE
==========================================================
Autonomous Curiosity & Self-Improvement System.

FEATURES:
- Dual Persistence (Event Logs + Canonical State).
- Crash-Safe Atomic Writes with Failure Reporting.
- Smart Jaccard Similarity for Gap Resolution (Improved Tokenization).
- Auto-Pruning of Old Metadata (Persisted).
- Optimized I/O (No nested save loops).

PATCHED:
- Fixed hallucination check to only trigger on genuinely uncertain responses
- Improved confidence assessment logic
- Hallucination guard no longer adds qualifiers to confident responses
"""

from __future__ import annotations

import os
import sys
import json
import time
import random
import uuid
import logging
import re
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path
from dataclasses import dataclass, field, asdict
from enum import Enum
from collections import defaultdict

from core.paths import MEMORY_DIR, load_config

log = logging.getLogger("learning")

# ============================================================================
# CONFIG
# ============================================================================


def _storage_base() -> Path:
    cfg = load_config()
    return Path(cfg.get("storage", {}).get("memory", str(MEMORY_DIR)))


# ============================================================================
# CONFIGURATION
# ============================================================================

class LearningConfig:
    """Configuration for learning engine"""

    # Storage Roots (computed at import time from config)
    LEARNING_DIR = _storage_base() / "learning"
    STATE_DIR = LEARNING_DIR / "state"

    # Event Logs (Append-Only History)
    KNOWLEDGE_GAPS_LOG = LEARNING_DIR / "knowledge_gaps.jsonl"
    CURIOSITY_LOG = LEARNING_DIR / "curiosity_log.jsonl"
    RESEARCH_LOG = LEARNING_DIR / "research_queue.jsonl"
    PRACTICE_LOG = LEARNING_DIR / "practice_log.jsonl"
    INSIGHTS_LOG = LEARNING_DIR / "insights.jsonl"

    # Canonical State (Current Brain)
    GAPS_STATE = STATE_DIR / "gaps.json"
    QUESTIONS_STATE = STATE_DIR / "questions.json"
    RESEARCH_STATE = STATE_DIR / "research.json"
    PRACTICE_STATE = STATE_DIR / "practice.json"
    INSIGHTS_STATE = STATE_DIR / "insights.json"
    META_STATE = STATE_DIR / "meta.json"

    # Settings
    CURIOSITY_THRESHOLD = 0.7
    QUESTIONS_PER_TOPIC = 3
    MIN_CONFIDENCE_FOR_TEACHING = 0.8

    # Autonomous learning
    AUTONOMOUS_RESEARCH_ENABLED = True
    IDLE_TIME_BEFORE_RESEARCH = 300
    MAX_RESEARCH_SESSIONS_PER_DAY = 5
    PREFERRED_RESEARCH_HOURS = [2, 3, 4, 5]

    # Skill practice
    PRACTICE_WEAK_SKILLS = True
    WEAK_SKILL_THRESHOLD = 0.6

    # Hallucination prevention
    VERIFY_BEFORE_CLAIMING = True
    CONFIDENCE_HONESTY = True
    HALLUCINATION_CONFIDENCE_THRESHOLD = 0.5

    # Logic Thresholds
    JACCARD_SIMILARITY_THRESHOLD = 0.3
    JACCARD_MIN_TOKENS = 2
    JACCARD_MIN_STRONG_TOKEN = 1
    MAX_HISTORY_DAYS = 30

    # Limits
    SCHEMA_VERSION = 2
    MAX_TEXT_LEN = 5000


# Ensure directories exist
LearningConfig.LEARNING_DIR.mkdir(parents=True, exist_ok=True)
LearningConfig.STATE_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================================
# UTILITIES
# ============================================================================

_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "else",
    "to", "of", "in", "on", "for", "with", "by", "from", "at", "as",
    "is", "are", "was", "were", "be", "been", "being",
    "this", "that", "these", "those", "it", "its", "into", "about"
}


def _now() -> str:
    return datetime.now().isoformat()


def _today() -> str:
    return date.today().isoformat()


def _atomic_write_json(path: Path, data: Dict[str, Any]) -> bool:
    """Safe write. Returns True if successful, False if failed."""
    tmp = path.with_suffix(".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
        return True
    except Exception as e:
        log.error("CRITICAL: Atomic write failed for %s: %s", path, e)
        return False


def _append_jsonl(path: Path, data: Dict[str, Any]):
    """Append record to log."""
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")
    except Exception as e:
        log.error("Log append failed for %s: %s", path, e)


def _append_event(path: Path, event: str, payload: Dict[str, Any]):
    """
    Structured event wrapper.
    Logs remain JSONL with event + ts + data.
    """
    _append_jsonl(path, {"event": event, "ts": _now(), "data": payload})


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log.warning("Failed to read %s, using default. Error: %s", path, e)
        return default


def _generate_id(prefix: str) -> str:
    return "%s_%s_%s" % (prefix, datetime.now().strftime("%Y%m%d"), uuid.uuid4().hex[:12])


def _safe_enum(enum_cls, value, default):
    try:
        if isinstance(value, int):
            return enum_cls(value)
        return enum_cls(value)
    except (ValueError, TypeError):
        return default


def _clamp_text(text: str) -> str:
    if not text:
        return ""
    return str(text)[:LearningConfig.MAX_TEXT_LEN]


def _tokenize(text: str) -> List[str]:
    """
    Tokenization hardened vs split():
    - lowercases
    - strips punctuation
    - removes stopwords
    - drops very short tokens (<3)
    """
    if not text:
        return []
    text = str(text).lower()
    text = re.sub(r"[^a-z0-9\s]+", " ", text)
    raw = text.split()
    toks = []
    for t in raw:
        if len(t) < 3:
            continue
        if t in _STOPWORDS:
            continue
        toks.append(t)
    return toks


def _calculate_jaccard(text1: str, text2: str) -> float:
    """Calculate token overlap similarity (0.0 to 1.0) with basic normalization."""
    t1 = _tokenize(text1)
    t2 = _tokenize(text2)
    if len(t1) < LearningConfig.JACCARD_MIN_TOKENS or len(t2) < LearningConfig.JACCARD_MIN_TOKENS:
        return 0.0

    set1 = set(t1)
    set2 = set(t2)
    inter = set1 & set2
    if not inter:
        return 0.0

    strong_inter = [t for t in inter if len(t) >= 5]
    if len(strong_inter) < LearningConfig.JACCARD_MIN_STRONG_TOKEN:
        return 0.0

    union = set1 | set2
    return len(inter) / len(union) if union else 0.0


# ============================================================================
# ENUMS
# ============================================================================

class KnowledgeGapType(Enum):
    UNKNOWN_TOPIC = 1
    SKILL_GAP = 2
    FACTUAL_GAP = 3
    CONCEPTUAL_GAP = 4
    PROCEDURAL_GAP = 5


class ResearchPriority(Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


class CuriosityTrigger(Enum):
    USER_QUESTION = 1
    AUTONOMOUS_DISCOVERY = 2
    ERROR_ENCOUNTER = 3
    PATTERN_RECOGNITION = 4


# ============================================================================
# DATA MODELS
# ============================================================================

@dataclass
class KnowledgeGap:
    gap_id: str
    timestamp: str
    topic: str
    gap_type: KnowledgeGapType
    description: str
    trigger: CuriosityTrigger
    priority: ResearchPriority
    context: str
    researched: bool = False
    research_results: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["gap_type"] = self.gap_type.value
        d["trigger"] = self.trigger.value
        d["priority"] = self.priority.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KnowledgeGap":
        data = dict(data)
        data["gap_type"] = _safe_enum(KnowledgeGapType, data.get("gap_type"), KnowledgeGapType.UNKNOWN_TOPIC)
        data["trigger"] = _safe_enum(CuriosityTrigger, data.get("trigger"), CuriosityTrigger.AUTONOMOUS_DISCOVERY)
        data["priority"] = _safe_enum(ResearchPriority, data.get("priority"), ResearchPriority.MEDIUM)
        return cls(**data)


@dataclass
class CuriousQuestion:
    question_id: str
    timestamp: str
    question: str
    topic: str
    priority: int
    answered: bool = False
    answer: str = ""
    confidence: float = 0.0
    follow_up_questions: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CuriousQuestion":
        """Load from dict, filtering out unknown fields and filling missing required ones"""
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_fields}

        if "question_id" not in filtered:
            filtered["question_id"] = _generate_id("q_recovered")
        if "timestamp" not in filtered:
            filtered["timestamp"] = _now()
        if "question" not in filtered:
            filtered["question"] = data.get("text", "Recovered question")
        if "topic" not in filtered:
            filtered["topic"] = "Unknown"
        if "priority" not in filtered:
            filtered["priority"] = 3

        return cls(**filtered)


@dataclass
class ResearchSession:
    session_id: str
    timestamp: str
    topic: str
    status: str
    sources: List[str] = field(default_factory=list)
    findings: List[str] = field(default_factory=list)
    confidence: float = 0.0

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ResearchSession":
        """Load from dict, filtering out unknown fields and filling missing required ones"""
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_fields}

        if "session_id" not in filtered:
            filtered["session_id"] = _generate_id("research_recovered")
        if "timestamp" not in filtered:
            filtered["timestamp"] = _now()
        if "topic" not in filtered:
            filtered["topic"] = "Unknown"
        if "status" not in filtered:
            filtered["status"] = "queued"

        return cls(**filtered)


@dataclass
class PracticeSession:
    session_id: str
    timestamp: str
    skill: str
    practice_type: str
    success: bool = False
    notes: str = ""
    completed_at: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PracticeSession":
        """Load from dict, filtering out unknown fields and filling missing required ones"""
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_fields}

        if "session_id" not in filtered:
            filtered["session_id"] = _generate_id("practice_recovered")
        if "timestamp" not in filtered:
            filtered["timestamp"] = _now()
        if "skill" not in filtered:
            filtered["skill"] = "Unknown"
        if "practice_type" not in filtered:
            filtered["practice_type"] = "drill"

        return cls(**filtered)


@dataclass
class Insight:
    insight_id: str
    timestamp: str
    text: str
    category: str
    confidence: float
    evidence: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Insight":
        """Load from dict, filtering out unknown fields and filling missing required ones"""
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_fields}

        if "insight_id" not in filtered:
            filtered["insight_id"] = _generate_id("insight_recovered")
        if "timestamp" not in filtered:
            filtered["timestamp"] = _now()
        if "text" not in filtered:
            filtered["text"] = data.get("description", "Recovered insight")
        if "category" not in filtered:
            filtered["category"] = "general"
        if "confidence" not in filtered:
            filtered["confidence"] = 0.5

        return cls(**filtered)


# ============================================================================
# CURIOSITY ENGINE
# ============================================================================

class CuriosityEngine:
    @staticmethod
    def generate_questions(topic: str, gap_type: KnowledgeGapType, count: int = 3) -> List[str]:
        """Generate curious questions based on gap type"""
        templates = {
            KnowledgeGapType.UNKNOWN_TOPIC: [
                "What is %s?" % topic,
                "Why is %s important?" % topic,
                "How does %s work?" % topic,
                "What are the key concepts in %s?" % topic,
                "What are common misconceptions about %s?" % topic
            ],
            KnowledgeGapType.SKILL_GAP: [
                "How can I improve at %s?" % topic,
                "What are the fundamentals of %s?" % topic,
                "What mistakes do beginners make with %s?" % topic,
                "What resources are best for learning %s?" % topic,
                "How long does it take to master %s?" % topic
            ],
            KnowledgeGapType.FACTUAL_GAP: [
                "What are the facts about %s?" % topic,
                "What evidence supports claims about %s?" % topic,
                "What are reliable sources for %s?" % topic,
                "What is currently known about %s?" % topic,
                "What research has been done on %s?" % topic
            ],
            KnowledgeGapType.CONCEPTUAL_GAP: [
                "What is the underlying theory of %s?" % topic,
                "How does %s relate to other concepts?" % topic,
                "What are the principles behind %s?" % topic,
                "How do experts think about %s?" % topic,
                "What frameworks explain %s?" % topic
            ],
            KnowledgeGapType.PROCEDURAL_GAP: [
                "What is the process for %s?" % topic,
                "What are the steps involved in %s?" % topic,
                "What tools are needed for %s?" % topic,
                "What is the best workflow for %s?" % topic,
                "How do I troubleshoot problems with %s?" % topic
            ]
        }

        available = templates.get(gap_type, templates[KnowledgeGapType.UNKNOWN_TOPIC])
        return random.sample(available, min(count, len(available)))


# ============================================================================
# LEARNING MANAGER
# ============================================================================

class LearningManager:
    def __init__(self):
        self.knowledge_gaps: Dict[str, KnowledgeGap] = {}
        self.questions: Dict[str, CuriousQuestion] = {}
        self.research_queue: Dict[str, ResearchSession] = {}
        self.practice_sessions: Dict[str, PracticeSession] = {}
        self.insights: Dict[str, Insight] = {}
        self.meta: Dict[str, Any] = {}

        self._load_state()

    def _load_state(self):
        """Load canonical state from disk, auto-repairing corrupted entries"""
        repairs = {"gaps": 0, "questions": 0, "research": 0, "practice": 0, "insights": 0}

        gaps_data = _read_json(LearningConfig.GAPS_STATE, {})
        for k, v in gaps_data.items():
            try:
                self.knowledge_gaps[k] = KnowledgeGap.from_dict(v)
            except Exception as e:
                log.warning("Skipping corrupted gap %s: %s", k, e)
                repairs["gaps"] += 1

        questions_data = _read_json(LearningConfig.QUESTIONS_STATE, {})
        for k, v in questions_data.items():
            try:
                self.questions[k] = CuriousQuestion.from_dict(v)
            except Exception as e:
                log.warning("Skipping corrupted question %s: %s", k, e)
                repairs["questions"] += 1

        research_data = _read_json(LearningConfig.RESEARCH_STATE, {})
        for k, v in research_data.items():
            try:
                self.research_queue[k] = ResearchSession.from_dict(v)
            except Exception as e:
                log.warning("Skipping corrupted research %s: %s", k, e)
                repairs["research"] += 1

        practice_data = _read_json(LearningConfig.PRACTICE_STATE, {})
        for k, v in practice_data.items():
            try:
                self.practice_sessions[k] = PracticeSession.from_dict(v)
            except Exception as e:
                log.warning("Skipping corrupted practice %s: %s", k, e)
                repairs["practice"] += 1

        insights_data = _read_json(LearningConfig.INSIGHTS_STATE, {})
        for k, v in insights_data.items():
            try:
                self.insights[k] = Insight.from_dict(v)
            except Exception as e:
                log.warning("Skipping corrupted insight %s: %s", k, e)
                repairs["insights"] += 1

        self.meta = _read_json(LearningConfig.META_STATE, {})
        self._prune_old_metadata()

        total_repairs = sum(repairs.values())
        if total_repairs > 0:
            log.info("State loaded with %s repairs: %s", total_repairs, repairs)

    def _prune_old_metadata(self):
        """Remove metadata older than MAX_HISTORY_DAYS"""
        cutoff = (datetime.now() - timedelta(days=LearningConfig.MAX_HISTORY_DAYS)).isoformat()

        if "research_counts" in self.meta:
            old_dates = [d for d in self.meta["research_counts"].keys() if d < cutoff[:10]]
            for d in old_dates:
                del self.meta["research_counts"][d]

    def _save_state(self):
        """Save canonical state to disk"""
        gaps_dict = {k: v.to_dict() for k, v in self.knowledge_gaps.items()}
        _atomic_write_json(LearningConfig.GAPS_STATE, gaps_dict)

        questions_dict = {k: asdict(v) for k, v in self.questions.items()}
        _atomic_write_json(LearningConfig.QUESTIONS_STATE, questions_dict)

        research_dict = {k: asdict(v) for k, v in self.research_queue.items()}
        _atomic_write_json(LearningConfig.RESEARCH_STATE, research_dict)

        practice_dict = {k: asdict(v) for k, v in self.practice_sessions.items()}
        _atomic_write_json(LearningConfig.PRACTICE_STATE, practice_dict)

        insights_dict = {k: asdict(v) for k, v in self.insights.items()}
        _atomic_write_json(LearningConfig.INSIGHTS_STATE, insights_dict)

        _atomic_write_json(LearningConfig.META_STATE, self.meta)

    def identify_knowledge_gap(
        self,
        topic: str,
        gap_type: KnowledgeGapType,
        description: str,
        trigger: CuriosityTrigger,
        priority: ResearchPriority = ResearchPriority.MEDIUM,
        context: str = ""
    ) -> str:
        """Identify a new knowledge gap"""
        topic = _clamp_text(topic)
        description = _clamp_text(description)
        context = _clamp_text(context)

        for existing in self.knowledge_gaps.values():
            if existing.topic.lower() == topic.lower():
                similarity = _calculate_jaccard(description, existing.description)
                if similarity > LearningConfig.JACCARD_SIMILARITY_THRESHOLD:
                    log.info("Duplicate gap detected for '%s', using existing: %s", topic, existing.gap_id)
                    return existing.gap_id

        gap_id = _generate_id("gap")
        gap = KnowledgeGap(
            gap_id=gap_id,
            timestamp=_now(),
            topic=topic,
            gap_type=gap_type,
            description=description,
            trigger=trigger,
            priority=priority,
            context=context
        )

        self.knowledge_gaps[gap_id] = gap
        _append_event(LearningConfig.KNOWLEDGE_GAPS_LOG, "gap_identified", gap.to_dict())
        self._save_state()

        log.info("Knowledge gap identified: %s - %s", gap_id, topic)
        return gap_id

    def ask_question(self, question: str, topic: str = "General", priority: int = 3) -> str:
        """Ask a curious question"""
        question = _clamp_text(question)
        topic = _clamp_text(topic)

        qid = _generate_id("q")
        q = CuriousQuestion(
            question_id=qid,
            timestamp=_now(),
            question=question,
            topic=topic,
            priority=priority
        )

        self.questions[qid] = q
        _append_event(LearningConfig.CURIOSITY_LOG, "question_asked", asdict(q))
        self._save_state()

        log.info("Question asked: %s - %s", qid, question)
        return qid

    def answer_question(
        self,
        question_id: str,
        answer: str,
        confidence: float = 1.0,
        follow_ups: Optional[List[str]] = None
    ) -> bool:
        """Answer a question"""
        if question_id not in self.questions:
            return False

        q = self.questions[question_id]
        q.answered = True
        q.answer = _clamp_text(answer)
        q.confidence = max(0.0, min(1.0, confidence))
        if follow_ups:
            q.follow_up_questions = follow_ups

        _append_event(LearningConfig.CURIOSITY_LOG, "question_answered", {
            "question_id": question_id,
            "answer": q.answer,
            "confidence": q.confidence
        })
        self._save_state()

        log.info("Question answered: %s", question_id)
        return True

    def queue_research(self, topic: str) -> str:
        """Queue a research session"""
        topic = _clamp_text(topic)

        sid = _generate_id("research")
        session = ResearchSession(
            session_id=sid,
            timestamp=_now(),
            topic=topic,
            status="queued"
        )

        self.research_queue[sid] = session
        _append_event(LearningConfig.RESEARCH_LOG, "research_queued", asdict(session))
        self._save_state()

        log.info("Research queued: %s - %s", sid, topic)
        return sid

    def start_research_session(self, session_id: str) -> bool:
        """Start a research session"""
        if session_id not in self.research_queue:
            return False

        session = self.research_queue[session_id]
        session.status = "in_progress"

        _append_event(LearningConfig.RESEARCH_LOG, "research_started", {"session_id": session_id})
        self._save_state()

        log.info("Research started: %s", session_id)
        return True

    def complete_research_session(
        self,
        session_id: str,
        sources: List[str],
        findings: List[str],
        confidence: float = 0.5
    ) -> bool:
        """Complete a research session"""
        if session_id not in self.research_queue:
            return False

        session = self.research_queue[session_id]
        session.status = "completed"
        session.sources = sources
        session.findings = findings
        session.confidence = max(0.0, min(1.0, confidence))

        _append_event(LearningConfig.RESEARCH_LOG, "research_completed", {
            "session_id": session_id,
            "sources_count": len(sources),
            "findings_count": len(findings),
            "confidence": confidence
        })
        self._save_state()

        log.info("Research completed: %s", session_id)
        return True

    def schedule_skill_practice(self, skill: str, practice_type: str = "drill") -> str:
        """Schedule a skill practice session"""
        skill = _clamp_text(skill)
        practice_type = _clamp_text(practice_type)

        sid = _generate_id("practice")
        session = PracticeSession(
            session_id=sid,
            timestamp=_now(),
            skill=skill,
            practice_type=practice_type
        )

        self.practice_sessions[sid] = session
        _append_event(LearningConfig.PRACTICE_LOG, "practice_scheduled", asdict(session))
        self._save_state()

        log.info("Practice scheduled: %s - %s", sid, skill)
        return sid

    def complete_practice_session(
        self,
        session_id: str,
        success: bool,
        notes: str = ""
    ) -> bool:
        """Complete a practice session"""
        if session_id not in self.practice_sessions:
            return False

        session = self.practice_sessions[session_id]
        session.success = success
        session.notes = _clamp_text(notes)
        session.completed_at = _now()

        _append_event(LearningConfig.PRACTICE_LOG, "practice_completed", {
            "session_id": session_id,
            "success": success
        })
        self._save_state()

        log.info("Practice completed: %s - %s", session_id, "Success" if success else "Failed")
        return True

    def record_insight(
        self,
        text: str,
        category: str = "general",
        confidence: float = 0.5,
        evidence: Optional[List[str]] = None
    ) -> str:
        """Record an insight"""
        text = _clamp_text(text)
        category = _clamp_text(category)

        iid = _generate_id("insight")
        insight = Insight(
            insight_id=iid,
            timestamp=_now(),
            text=text,
            category=category,
            confidence=max(0.0, min(1.0, confidence)),
            evidence=evidence or []
        )

        self.insights[iid] = insight
        _append_event(LearningConfig.INSIGHTS_LOG, "insight_recorded", asdict(insight))
        self._save_state()

        log.info("Insight recorded: %s", iid)
        return iid

    def identify_skills_needing_practice(self) -> List[str]:
        """Identify skills that need practice based on past performance"""
        skill_stats = defaultdict(lambda: {"total": 0, "success": 0})

        for session in self.practice_sessions.values():
            if session.completed_at:
                skill_stats[session.skill]["total"] += 1
                if session.success:
                    skill_stats[session.skill]["success"] += 1

        weak_skills = []
        for skill, stats in skill_stats.items():
            if stats["total"] > 0:
                success_rate = stats["success"] / stats["total"]
                if success_rate < LearningConfig.WEAK_SKILL_THRESHOLD:
                    weak_skills.append(skill)

        return weak_skills

    def should_research_now(self) -> bool:
        """Determine if autonomous research should happen"""
        if not LearningConfig.AUTONOMOUS_RESEARCH_ENABLED:
            return False

        hour = datetime.now().hour
        if hour not in LearningConfig.PREFERRED_RESEARCH_HOURS:
            return False

        if time.time() - self.meta.get("last_activity", 0) < LearningConfig.IDLE_TIME_BEFORE_RESEARCH:
            return False

        today = _today()
        if self.meta.get("research_counts", {}).get(today, 0) >= LearningConfig.MAX_RESEARCH_SESSIONS_PER_DAY:
            return False

        return True

    def autonomous_learning_cycle(self) -> Dict[str, Any]:
        """Run one cycle of autonomous learning"""
        actions = {"research": 0, "questions": 0, "practice": 0}

        # 1. Research
        if self.should_research_now():
            queued = [s for s in self.research_queue.values() if s.status == "queued"]
            if queued:
                target = queued[0]
                self.start_research_session(target.session_id)
                today = _today()
                self.meta.setdefault("research_counts", {})
                self.meta["research_counts"][today] = self.meta["research_counts"].get(today, 0) + 1
                self._save_state()
                actions["research"] = 1

        # 2. Curiosity
        if random.random() < LearningConfig.CURIOSITY_THRESHOLD:
            unresearched = [g for g in self.knowledge_gaps.values() if not g.researched]
            if unresearched:
                gap = random.choice(unresearched)
                qs = CuriosityEngine.generate_questions(gap.topic, gap.gap_type, count=1)
                for q in qs:
                    self.ask_question(q, gap.topic, priority=2)
                actions["questions"] += 1

        # 3. Practice
        if LearningConfig.PRACTICE_WEAK_SKILLS:
            weak_skills = self.identify_skills_needing_practice()
            if weak_skills:
                target = random.choice(weak_skills)
                self.schedule_skill_practice(target, "autonomous_drill")
                actions["practice"] = 1

        return actions

    def generate_report(self) -> str:
        lines = ["\n" + "=" * 60, "LEARNING REPORT", "=" * 60]

        total_gaps = len(self.knowledge_gaps)
        solved_gaps = sum(1 for g in self.knowledge_gaps.values() if g.researched)
        lines.append("GAPS: %d/%d Researched" % (solved_gaps, total_gaps))

        total_q = len(self.questions)
        ans_q = sum(1 for q in self.questions.values() if q.answered)
        lines.append("QUESTIONS: %d/%d Answered" % (ans_q, total_q))

        queued = sum(1 for s in self.research_queue.values() if s.status == "queued")
        completed = sum(1 for s in self.research_queue.values() if s.status == "completed")
        today = _today()
        count_today = self.meta.get("research_counts", {}).get(today, 0)
        lines.append("RESEARCH: %d Done, %d Queued. (Today: %d)" % (completed, queued, count_today))

        prac_total = len(self.practice_sessions)
        prac_done = sum(1 for s in self.practice_sessions.values() if s.completed_at)
        lines.append("PRACTICE: %d/%d Sessions" % (prac_done, prac_total))

        lines.append("INSIGHTS: %d Total" % len(self.insights))

        high_pri = [g for g in self.knowledge_gaps.values() if (not g.researched and g.priority == ResearchPriority.CRITICAL)]
        if high_pri:
            lines.append("\nCRITICAL GAPS:")
            for g in high_pri[:3]:
                lines.append(" - %s" % g.topic)

        lines.append("=" * 60 + "\n")
        return "\n".join(lines)

    def get_unanswered_questions(self, min_priority: int = 1) -> List[CuriousQuestion]:
        return [q for q in self.questions.values() if (not q.answered and q.priority >= min_priority)]

    def get_unresearched_gaps(self, min_priority: int = 1) -> List[KnowledgeGap]:
        return [g for g in self.knowledge_gaps.values() if (not g.researched and g.priority.value >= min_priority)]


# ============================================================================
# HALLUCINATION PREVENTION
# ============================================================================

class HallucinationDetector:
    @staticmethod
    def assess_confidence(statement: str, evidence: List[str]) -> Tuple[float, str]:
        """
        More accurate confidence assessment:
        - Starts at neutral (0.5)
        - Only penalizes if MULTIPLE uncertainty indicators present
        - Rewards strong evidence
        """
        confidence = 0.5
        reasoning_parts = []

        statement_lower = str(statement).lower()

        strong_hedging = ["i'm not sure", "i don't know", "i have no idea"]
        weak_hedging = ["might", "maybe", "possibly", "probably", "perhaps", "seems"]

        strong_hedge_count = sum(1 for h in strong_hedging if h in statement_lower)
        weak_hedge_count = sum(1 for h in weak_hedging if h in statement_lower)

        if strong_hedge_count > 0:
            confidence -= 0.3
            reasoning_parts.append("Strong uncertainty expressed")
        elif weak_hedge_count >= 2:
            confidence -= 0.2
            reasoning_parts.append("Multiple hedging words")
        elif weak_hedge_count == 1:
            confidence -= 0.05
            reasoning_parts.append("Minor hedging")

        if not evidence:
            confidence -= 0.15
            reasoning_parts.append("No evidence provided")
        elif len(evidence) >= 3:
            confidence += 0.3
            reasoning_parts.append("Strong evidence base")
        elif len(evidence) >= 2:
            confidence += 0.2
            reasoning_parts.append("Good evidence")
        else:
            confidence += 0.1
            reasoning_parts.append("Some evidence")

        return max(0.0, min(1.0, confidence)), "; ".join(reasoning_parts)

    @staticmethod
    def generate_honest_response(statement: str, confidence: float) -> str:
        """
        Only modify response if confidence is genuinely low:
        - High confidence (>= threshold): Return as-is
        - Medium confidence (0.4-threshold): Add mild qualifier
        - Low confidence (< 0.4): Add stronger qualifier
        """
        if not LearningConfig.CONFIDENCE_HONESTY:
            return str(statement)

        if confidence >= LearningConfig.HALLUCINATION_CONFIDENCE_THRESHOLD:
            return str(statement)

        if confidence >= 0.4:
            return "I believe %s" % statement

        return "I'm not certain, but %s" % statement


def check_for_hallucination(statement: str, evidence: List[str] = None) -> Dict[str, Any]:
    """
    Intelligent hallucination check:
    - Only triggers on genuinely uncertain responses
    - Provides detailed reasoning
    - Does not corrupt confident responses
    """
    evidence = evidence or []
    confidence, reasoning = HallucinationDetector.assess_confidence(statement, evidence)
    honest = HallucinationDetector.generate_honest_response(statement, confidence)

    return {
        "confidence": confidence,
        "should_verify": confidence < LearningConfig.HALLUCINATION_CONFIDENCE_THRESHOLD,
        "honest_version": honest,
        "reasoning": reasoning,
        "original_modified": honest != statement
    }


# ============================================================================
# CONVENIENCE EXPORTS
# ============================================================================

_inst = None


def get_learning_manager() -> LearningManager:
    global _inst
    if _inst is None:
        _inst = LearningManager()
    return _inst


def identify_gap(topic, gap_type, desc, trigger, priority=ResearchPriority.MEDIUM, context=""):
    return get_learning_manager().identify_knowledge_gap(topic, gap_type, desc, trigger, priority, context)


def ask_curious_question(question, topic="General Inquiry", priority=3):
    return get_learning_manager().ask_question(question, topic, priority)


def answer_question(question_id, answer, confidence=1.0, follow_ups=None):
    return get_learning_manager().answer_question(question_id, answer, confidence, follow_ups)


def record_insight(text, cat="general", conf=0.5, evidence=None):
    return get_learning_manager().record_insight(text, cat, conf, evidence)


def get_learning_report():
    return get_learning_manager().generate_report()


def autonomous_learn():
    return get_learning_manager().autonomous_learning_cycle()


def practice_skill(skill, practice_type="drill"):
    return get_learning_manager().schedule_skill_practice(skill, practice_type)


# ============================================================================
# TOOL REGISTRATION
# ============================================================================

def register_tools(registry) -> None:
    registry.register("learning_identify_gap", identify_gap)
    registry.register("learning_ask_question", ask_curious_question)
    registry.register("learning_answer_question", answer_question)
    registry.register("learning_record_insight", record_insight)
    registry.register("learning_get_report", get_learning_report)
    registry.register("learning_autonomous_cycle", autonomous_learn)
    registry.register("learning_practice_skill", practice_skill)
    registry.register("learning_check_hallucination", check_for_hallucination)
    registry.register("learning_queue_research", lambda topic: get_learning_manager().queue_research(topic))
    registry.register("learning_complete_research", lambda sid, sources, findings, conf=0.5: get_learning_manager().complete_research_session(sid, sources, findings, conf))


# ============================================================================
# CLI ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Apex Learning Engine")
    parser.add_argument("--report", action="store_true", help="Show report")
    parser.add_argument("--autonomous", action="store_true", help="Run autonomous cycle")
    parser.add_argument("--add-gap", nargs=2, metavar=("TOPIC", "DESC"), help="Add gap")
    parser.add_argument("--ask", nargs=2, metavar=("Q", "TOPIC"), help="Ask question")

    args = parser.parse_args()
    mgr = get_learning_manager()

    if args.report:
        print(get_learning_report())

    elif args.autonomous:
        print(autonomous_learn())

    elif args.add_gap:
        identify_gap(args.add_gap[0], KnowledgeGapType.UNKNOWN_TOPIC, args.add_gap[1], CuriosityTrigger.USER_QUESTION)
        print("Gap added.")

    elif args.ask:
        ask_curious_question(args.ask[0], args.ask[1])
        print("Question asked.")

    else:
        print("Use --help for options.")
