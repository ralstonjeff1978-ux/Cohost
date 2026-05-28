"""
INTERVIEW ENGINE — Podcast Conversation & Guest Memory
======================================================
Manages multi-turn podcast conversations, guest profiles, episode tracking,
and interview flow. Remembers guests from previous episodes and builds on
those relationships.

Key features:
- Guest profile persistence (who they are, what they said before)
- Episode session tracking (current episode, topic, conversation turns)
- Interview mode with follow-up question generation
- Episode summaries saved to disk for the dream cycle to reflect on
- Conversation context window management

Usage:
    from conversation.interview_engine import InterviewEngine
    eng = InterviewEngine()
    eng.start_episode("The Future of AI", guest_name="Dr. Jane Smith")
    response = eng.respond("Tell me about your research.")
    eng.end_episode()
"""

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

from core.paths import MEMORY_DIR, SESSIONS_DIR, load_config as _load_cfg

log = logging.getLogger("interview")


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _storage() -> dict:
    cfg = _load_cfg()
    return cfg.get("storage", {})


# ── Data models ────────────────────────────────────────────────────────────────

@dataclass
class GuestProfile:
    guest_id: str
    name: str
    first_seen: str
    last_seen: str
    episode_count: int = 0
    bio: str = ""
    topics_discussed: List[str] = field(default_factory=list)
    memorable_quotes: List[str] = field(default_factory=list)
    follow_up_threads: List[str] = field(default_factory=list)
    episode_ids: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def summary_for_prompt(self) -> str:
        """Return a compact summary for injecting into the LLM system prompt."""
        lines = [f"Guest: {self.name}"]
        if self.bio:
            lines.append(f"Bio: {self.bio}")
        if self.episode_count > 1:
            lines.append(f"Previous appearances: {self.episode_count - 1}")
        if self.topics_discussed:
            lines.append(f"Topics we've covered before: {', '.join(self.topics_discussed[-5:])}")
        if self.memorable_quotes:
            lines.append(f"Something they said before: \"{self.memorable_quotes[-1]}\"")
        if self.follow_up_threads:
            lines.append(f"Unfinished thread from last time: {self.follow_up_threads[-1]}")
        return "\n".join(lines)


@dataclass
class ConversationTurn:
    role: str          # "host" | "guest" | "system"
    content: str
    timestamp: str
    turn_index: int


@dataclass
class Episode:
    episode_id: str
    title: str
    guest_name: Optional[str]
    guest_id: Optional[str]
    started_at: str
    ended_at: Optional[str]
    topic: str
    turns: List[ConversationTurn] = field(default_factory=list)
    summary: str = ""
    key_moments: List[str] = field(default_factory=list)
    follow_up_threads: List[str] = field(default_factory=list)
    status: str = "active"    # active | completed | archived


# ── Guest Registry ────────────────────────────────────────────────────────────

class GuestRegistry:
    """Persistent memory of all podcast guests across all episodes."""

    def __init__(self, guests_file: str):
        self.path = Path(guests_file)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.guests: Dict[str, GuestProfile] = {}
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                for gid, data in raw.items():
                    self.guests[gid] = GuestProfile(**data)
            except Exception as e:
                log.warning("Could not load guests file: %s", e)

    def _save(self):
        tmp = self.path.with_suffix(".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({gid: asdict(g) for gid, g in self.guests.items()}, f, indent=2)
            os.replace(tmp, self.path)
        except Exception as e:
            log.error("Could not save guests file: %s", e)

    def get_or_create(self, name: str) -> GuestProfile:
        # Search by name (case-insensitive)
        name_lower = name.strip().lower()
        for g in self.guests.values():
            if g.name.lower() == name_lower:
                return g
        # New guest
        gid = "guest_" + uuid.uuid4().hex[:8]
        guest = GuestProfile(
            guest_id=gid,
            name=name.strip(),
            first_seen=_now_iso(),
            last_seen=_now_iso(),
        )
        self.guests[gid] = guest
        self._save()
        log.info("New guest registered: %s (%s)", name, gid)
        return guest

    def update_after_episode(self, guest: GuestProfile, episode: "Episode"):
        """Update guest profile after an episode ends."""
        guest.last_seen = _now_iso()
        guest.episode_count += 1
        if episode.episode_id not in guest.episode_ids:
            guest.episode_ids.append(episode.episode_id)
        if episode.topic and episode.topic not in guest.topics_discussed:
            guest.topics_discussed.append(episode.topic)
        if episode.follow_up_threads:
            guest.follow_up_threads.extend(episode.follow_up_threads)
            guest.follow_up_threads = guest.follow_up_threads[-5:]
        self._save()

    def set_bio(self, guest_id: str, bio: str):
        if guest_id in self.guests:
            self.guests[guest_id].bio = bio
            self._save()

    def add_quote(self, guest_id: str, quote: str):
        if guest_id in self.guests:
            self.guests[guest_id].memorable_quotes.append(quote)
            self.guests[guest_id].memorable_quotes = \
                self.guests[guest_id].memorable_quotes[-10:]
            self._save()

    def list_all(self) -> List[GuestProfile]:
        return sorted(self.guests.values(), key=lambda g: g.last_seen, reverse=True)


# ── Interview Engine ──────────────────────────────────────────────────────────

class InterviewEngine:
    """
    Manages podcast conversation sessions with full memory and interview flow.
    """

    def __init__(self):
        cfg = _load_cfg()
        conv_cfg = cfg.get("conversation", {})
        storage_cfg = cfg.get("storage", {})
        cohost_cfg = cfg.get("cohost", {})

        self.sessions_dir = Path(conv_cfg.get("sessions_dir", str(SESSIONS_DIR)))
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

        guests_file = conv_cfg.get(
            "guests_file",
            str(Path(storage_cfg.get("memory", str(MEMORY_DIR))) / "guests.json")
        )
        self.registry = GuestRegistry(guests_file)

        self.cohost_name = cohost_cfg.get("name", "Aria")
        self.persona = cohost_cfg.get("persona", "You are a warm podcast co-host.")
        self.max_history = conv_cfg.get("max_history_turns", 40)
        self.follow_up_depth = cfg.get("cohost", {}).get("follow_up_depth", 2)
        self.max_response_sentences = cfg.get("cohost", {}).get("max_response_sentences", 4)
        self.voice_mode = False   # set to True by cohost.py when --voice is active

        self.current_episode: Optional[Episode] = None
        self.current_guest: Optional[GuestProfile] = None
        self._follow_up_stack: List[str] = []

        log.info("Interview Engine ready — host: %s", self.cohost_name)

    # ── Episode lifecycle ─────────────────────────────────────────────────────

    def start_episode(
        self,
        title: str,
        topic: str = "",
        guest_name: Optional[str] = None,
        guest_bio: Optional[str] = None,
    ) -> str:
        """Start a new episode. Returns episode ID."""
        episode_id = "ep_" + datetime.now().strftime("%Y%m%d_%H%M%S")

        self.current_guest = None
        guest_id = None
        if guest_name:
            self.current_guest = self.registry.get_or_create(guest_name)
            guest_id = self.current_guest.guest_id
            if guest_bio:
                self.registry.set_bio(guest_id, guest_bio)
                self.current_guest.bio = guest_bio

        self.current_episode = Episode(
            episode_id=episode_id,
            title=title,
            guest_name=guest_name,
            guest_id=guest_id,
            started_at=_now_iso(),
            ended_at=None,
            topic=topic or title,
        )

        self._follow_up_stack = []
        log.info("Episode started: %s (guest: %s)", episode_id, guest_name or "solo")
        return episode_id

    def end_episode(self, generate_summary: bool = True) -> str:
        """End the current episode, save it, and update guest profile."""
        if not self.current_episode:
            return "No active episode."

        ep = self.current_episode
        ep.ended_at = _now_iso()
        ep.status = "completed"

        summary = ""
        if generate_summary:
            summary = self._generate_episode_summary()
            ep.summary = summary

        self._save_episode(ep)

        if self.current_guest:
            self.registry.update_after_episode(self.current_guest, ep)

        log.info("Episode ended: %s — %d turns", ep.episode_id, len(ep.turns))

        self.current_episode = None
        self.current_guest = None
        return summary or f"Episode '{ep.title}' saved."

    # ── Conversation core ─────────────────────────────────────────────────────

    def build_system_prompt(self) -> str:
        """Build the full system prompt for the current episode context."""
        parts = [self.persona]

        if self.current_episode:
            ep = self.current_episode
            parts.append(f"\nCurrent episode: \"{ep.title}\"")
            if ep.topic:
                parts.append(f"Episode topic: {ep.topic}")

        if self.current_guest:
            g = self.current_guest
            parts.append(f"\n{g.summary_for_prompt()}")
            if g.episode_count > 1:
                parts.append(
                    f"\nThis is {g.name}'s episode #{g.episode_count} on this podcast. "
                    "Reference your prior conversations naturally when relevant."
                )
            else:
                parts.append(f"\nThis is {g.name}'s first appearance on this podcast.")

        if self._follow_up_stack:
            parts.append(
                f"\nUnresolved thread to follow up on when natural: {self._follow_up_stack[-1]}"
            )

        parts.append(
            f"\nKeep responses conversational and to no more than "
            f"{self.max_response_sentences} sentences unless the story demands more. "
            "Never use asterisks for actions or stage directions."
        )

        return "\n".join(parts)

    def get_history_for_llm(self) -> List[Dict]:
        """Return the conversation history in LLM chat format."""
        if not self.current_episode:
            return []
        turns = self.current_episode.turns[-self.max_history:]
        history = []
        for turn in turns:
            if turn.role == "host":
                history.append({"role": "assistant", "content": turn.content})
            elif turn.role == "guest":
                history.append({"role": "user", "content": turn.content})
        return history

    def add_guest_turn(self, text: str) -> None:
        """Record what the guest said."""
        if not self.current_episode:
            return
        idx = len(self.current_episode.turns)
        self.current_episode.turns.append(
            ConversationTurn(role="guest", content=text, timestamp=_now_iso(), turn_index=idx)
        )

    def add_host_turn(self, text: str) -> None:
        """Record what Aria said."""
        if not self.current_episode:
            return
        idx = len(self.current_episode.turns)
        self.current_episode.turns.append(
            ConversationTurn(role="host", content=text, timestamp=_now_iso(), turn_index=idx)
        )

    def respond(self, guest_input: str, call_ai_fn=None) -> str:
        """
        Process guest input and generate Aria's response.

        Args:
            guest_input: What the guest just said.
            call_ai_fn:  The LLM caller (ai_bridge.call_ai). If None, returns
                         a placeholder (for testing without LLM).
        Returns:
            Aria's response text.
        """
        if not self.current_episode:
            log.warning("respond() called with no active episode — call start_episode() first")
            return "I don't think we've started the episode yet!"

        self.add_guest_turn(guest_input)

        if call_ai_fn is None:
            placeholder = f"[TTS placeholder — LLM not connected] You said: {guest_input[:80]}"
            self.add_host_turn(placeholder)
            return placeholder

        system = self.build_system_prompt()
        history = self.get_history_for_llm()

        response = call_ai_fn(guest_input, system=system, history=history)
        self.add_host_turn(response)

        # Autosave periodically
        if len(self.current_episode.turns) % 10 == 0:
            self._save_episode(self.current_episode)

        return response

    def generate_opening(self, call_ai_fn=None) -> str:
        """Generate Aria's opening line for the episode."""
        if not self.current_episode:
            return "Welcome to the show!"

        ep = self.current_episode
        guest_ctx = ""
        if self.current_guest:
            g = self.current_guest
            if g.episode_count > 1:
                guest_ctx = (
                    f"You're welcoming back {g.name}, who has been on the show "
                    f"{g.episode_count - 1} time(s) before."
                )
            else:
                guest_ctx = f"You're welcoming {g.name} for the first time."

        prompt = (
            f"Generate a warm, engaging opening for today's episode titled \"{ep.title}\". "
            f"{guest_ctx} Keep it to 2-3 sentences. Be natural, not scripted-sounding."
        )

        if call_ai_fn is None:
            return f"Welcome to {ep.title}! I'm your host Aria."

        system = self.build_system_prompt()
        opening = call_ai_fn(prompt, system=system)
        self.add_host_turn(opening)
        return opening

    def generate_question(self, context: str = "", call_ai_fn=None) -> str:
        """Generate an interview question based on the current conversation context."""
        if not self.current_episode or call_ai_fn is None:
            return "What do you think about that?"

        history = self.get_history_for_llm()
        history_text = "\n".join(
            f"{t['role'].upper()}: {t['content']}" for t in history[-6:]
        ) if history else "No conversation yet."

        prompt = (
            f"Based on this conversation so far:\n{history_text}\n\n"
            f"{'Additional context: ' + context if context else ''}\n"
            "Generate ONE great follow-up interview question that digs deeper. "
            "Be curious, warm, and conversational. Just the question, no preamble."
        )
        return call_ai_fn(prompt, system=self.build_system_prompt())

    def flag_follow_up(self, thread: str) -> None:
        """Flag a topic thread to follow up on later in the episode."""
        self._follow_up_stack.append(thread)
        if self.current_episode:
            self.current_episode.follow_up_threads.append(thread)

    def save_memorable_quote(self, quote: str) -> None:
        """Save a memorable guest quote to their profile."""
        if self.current_guest:
            self.registry.add_quote(self.current_guest.guest_id, quote)

    # ── Episode persistence ───────────────────────────────────────────────────

    def _save_episode(self, ep: Episode) -> None:
        path = self.sessions_dir / f"{ep.episode_id}.json"
        tmp = path.with_suffix(".tmp")
        try:
            data = {
                "episode_id": ep.episode_id,
                "title": ep.title,
                "guest_name": ep.guest_name,
                "guest_id": ep.guest_id,
                "started_at": ep.started_at,
                "ended_at": ep.ended_at,
                "topic": ep.topic,
                "status": ep.status,
                "summary": ep.summary,
                "key_moments": ep.key_moments,
                "follow_up_threads": ep.follow_up_threads,
                "turn_count": len(ep.turns),
                "turns": [
                    {"role": t.role, "content": t.content,
                     "timestamp": t.timestamp, "turn_index": t.turn_index}
                    for t in ep.turns
                ],
            }
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, path)
            log.debug("Episode saved: %s", path)
        except Exception as e:
            log.error("Failed to save episode %s: %s", ep.episode_id, e)

    def _generate_episode_summary(self) -> str:
        """Generate a plain-text summary of the episode for memory/dream cycle."""
        if not self.current_episode:
            return ""
        ep = self.current_episode
        turn_count = len(ep.turns)
        guest_line = f"with {ep.guest_name}" if ep.guest_name else "(solo)"
        threads = (
            "Open threads: " + "; ".join(ep.follow_up_threads)
            if ep.follow_up_threads else ""
        )
        return (
            f"Episode: \"{ep.title}\" {guest_line}. "
            f"{turn_count} turns. Topic: {ep.topic}. {threads}"
        ).strip()

    def list_episodes(self, limit: int = 20) -> List[dict]:
        """List recent episodes from disk."""
        episodes = []
        for path in sorted(self.sessions_dir.glob("ep_*.json"), reverse=True)[:limit]:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                episodes.append({
                    "episode_id": data.get("episode_id"),
                    "title": data.get("title"),
                    "guest_name": data.get("guest_name"),
                    "started_at": data.get("started_at"),
                    "turn_count": data.get("turn_count", 0),
                    "status": data.get("status"),
                })
            except Exception:
                continue
        return episodes

    def load_episode(self, episode_id: str) -> Optional[dict]:
        """Load a past episode from disk."""
        path = self.sessions_dir / f"{episode_id}.json"
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log.error("Could not load episode %s: %s", episode_id, e)
            return None

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "active_episode": self.current_episode.episode_id if self.current_episode else None,
            "guest": self.current_guest.name if self.current_guest else None,
            "turns_this_episode": len(self.current_episode.turns) if self.current_episode else 0,
            "total_guests": len(self.registry.guests),
            "follow_up_threads": len(self._follow_up_stack),
        }


# ── Singleton ─────────────────────────────────────────────────────────────────

_engine: Optional[InterviewEngine] = None


def get_interview_engine() -> InterviewEngine:
    global _engine
    if _engine is None:
        _engine = InterviewEngine()
    return _engine


# ── Tool registration ─────────────────────────────────────────────────────────

def register_tools(registry) -> None:
    eng = get_interview_engine()
    registry.register("interview_start_episode", eng.start_episode)
    registry.register("interview_end_episode", eng.end_episode)
    registry.register("interview_respond", eng.respond)
    registry.register("interview_generate_opening", eng.generate_opening)
    registry.register("interview_generate_question", eng.generate_question)
    registry.register("interview_add_guest_turn", eng.add_guest_turn)
    registry.register("interview_flag_followup", eng.flag_follow_up)
    registry.register("interview_save_quote", eng.save_memorable_quote)
    registry.register("interview_list_episodes", eng.list_episodes)
    registry.register("interview_load_episode", eng.load_episode)
    registry.register("interview_status", eng.status)
    registry.register("interview_list_guests",
                       lambda: [{"name": g.name, "appearances": g.episode_count,
                                 "last_seen": g.last_seen}
                                for g in eng.registry.list_all()])
