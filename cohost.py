"""
COHOST — Podcast AI Co-Host (Powered by Aria)
==============================================
Main entry point. Boots the full co-host system and starts an interactive
podcast session.

Usage:
    python cohost.py                    # start interactive session
    python cohost.py --model mistral:7b # start with a specific brain
    python cohost.py --episode "Title"  # start a named episode
    python cohost.py --guest "Jane"     # start with a named guest
    python cohost.py --voice            # speak to Aria (mic input + Whisper STT)
    python cohost.py --voice --mic 9    # use a specific microphone by device index
    python cohost.py --voice --whisper small  # use a more accurate Whisper model
    python cohost.py --no-voice         # disable TTS output
    python cohost.py --brains           # list available brain models
    python cohost.py --voices           # list available TTS voices
    python cohost.py --mics             # list available microphone devices

Slash commands (during a session):
    /brain <model>      — switch brain model
    /voice <name>       — switch TTS voice
    /mic                — list microphones
    /mic <index>        — switch to a specific microphone
    /whisper <size>     — change Whisper model (tiny/base/small/medium)
    /guest <name>       — set or change the guest
    /bio <text>         — set guest bio
    /quote              — save last guest line as memorable quote
    /followup <thread>  — flag a thread for follow-up
    /open               — generate an episode opening
    /question           — generate an interview question
    /end                — end and save the episode
    /status             — show system status
    /memory             — show memory stats
    /learning           — show learning report
    /guests             — list all past guests
    /episodes           — list recent episodes
    /help               — show all commands
    /quit               — save and exit
"""

import argparse
import logging
import sys
from pathlib import Path

from core.paths import COHOST_HOME, LOGS_DIR, ensure_dirs, load_config


def _setup_logging():
    ensure_dirs()
    cfg = load_config()
    log_cfg = cfg.get("logging", {})
    level = getattr(logging, log_cfg.get("level", "INFO").upper(), logging.INFO)
    log_file = Path(log_cfg.get("file", str(LOGS_DIR / "cohost.log")))
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stderr),
        ],
    )


log = logging.getLogger("cohost")


# ── Cohost class ──────────────────────────────────────────────────────────────

class Cohost:
    """
    Fully wired podcast co-host system.

    Subsystems:
        ai_bridge       — LLM provider with model selector
        interview_engine — Conversation, guest memory, episode tracking
        tts             — Female voice output
        memory_tools    — Long-term decisions, lessons, skills
        learning_engine — Curiosity, knowledge gaps, autonomous learning
        experience_engine — Task/interaction learning
        dream_cycle     — Nightly reflection and improvement
        self_evolution  — Autonomous self-improvement proposals
    """

    def __init__(self, voice_enabled: bool = True):
        log.info("Booting Cohost...")

        # ── Core LLM ─────────────────────────────────────────────────────────
        from core.ai_bridge import call_ai, set_model, list_models, get_active_model
        self.call_ai = call_ai
        self.set_model = set_model
        self.list_models = list_models
        self.get_active_model = get_active_model

        # ── Conversation / Interview ─────────────────────────────────────────
        from conversation.interview_engine import get_interview_engine
        self.interview = get_interview_engine()

        # ── Voice ────────────────────────────────────────────────────────────
        self.voice_enabled = voice_enabled
        self._speak_fn = None
        if voice_enabled:
            try:
                from voice.tts_engine import speak, set_voice, list_voices
                self._speak_fn = speak
                self.set_voice = set_voice
                self.list_voices = list_voices
                log.info("TTS online")
            except Exception as e:
                log.warning("TTS failed to load: %s — voice disabled", e)
                self.voice_enabled = False

        # ── Memory ───────────────────────────────────────────────────────────
        self.memory = None
        try:
            import memory.memory_tools as mt
            self.memory = mt
            log.info("Long-term memory online")
        except Exception as e:
            log.warning("Memory tools unavailable: %s", e)

        # ── Learning ─────────────────────────────────────────────────────────
        self.learning = None
        try:
            from memory.learning_engine import get_learning_manager
            self.learning = get_learning_manager()
            log.info("Learning engine online")
        except Exception as e:
            log.warning("Learning engine unavailable: %s", e)

        # ── Experience ───────────────────────────────────────────────────────
        self.experience = None
        try:
            from memory.experience_engine import get_experience_engine
            self.experience = get_experience_engine()
            log.info("Experience engine online")
        except Exception as e:
            log.warning("Experience engine unavailable: %s", e)

        # ── Self-Evolution & Dream Cycle ─────────────────────────────────────
        self.evolution = None
        self.dreamer = None
        try:
            from infrastructure.self_evolution import get_self_evolution
            self.evolution = get_self_evolution()
            try:
                from memory.dream_cycle import get_dream_cycle
                self.dreamer = get_dream_cycle(self.experience, self.evolution)
                log.info("Dream cycle online")
            except Exception as e:
                log.warning("Dream cycle unavailable: %s", e)
        except Exception as e:
            log.warning("Self-evolution unavailable: %s", e)

        # ── Load persona from config ──────────────────────────────────────────
        cfg = load_config()
        self.name = cfg.get("cohost", {}).get("name", "Aria")

        log.info("Cohost %s ready — brain: %s | voice: %s",
                 self.name, self.get_active_model(), "on" if self.voice_enabled else "off")

    # ── Speech ────────────────────────────────────────────────────────────────

    def speak(self, text: str, blocking: bool = True) -> None:
        """Output text — prints to console and speaks if TTS is enabled."""
        print(f"\n{self.name}: {text}\n")
        if self.voice_enabled and self._speak_fn:
            self._speak_fn(text, blocking=blocking)

    def speak_streaming(self, prompt: str, system: str = None,
                        history: list = None) -> str:
        """
        Stream LLM response sentence by sentence, speaking each as it arrives.
        Returns the full response text.
        Much faster than waiting for the complete response before speaking.
        """
        import re
        import time
        from core.ai_bridge import stream_sentences
        t_turn = time.time()
        t_first_audio = None
        full_response = []
        first = True
        for sentence in stream_sentences(prompt, system=system, history=history):
            if first:
                print(f"\n{self.name}: ", end="", flush=True)
                first = False
            print(sentence + " ", end="", flush=True)
            full_response.append(sentence)
            if self.voice_enabled and self._speak_fn:
                # Strip *actions* and (stage directions) before speaking
                spoken = re.sub(r'\*[^*]+\*', '', sentence)
                spoken = re.sub(r'\([^)]+\)', '', spoken).strip()
                if spoken:
                    if t_first_audio is None:
                        t_first_audio = time.time()
                        log.info("[TIMING] turn_first_audio=%.2fs", t_first_audio - t_turn)
                    t_tts = time.time()
                    self._speak_fn(spoken, blocking=True)
                    log.info("[TIMING] tts_sentence=%.2fs chars=%d", time.time() - t_tts, len(spoken))
        print()
        log.info("[TIMING] turn_total=%.2fs first_audio=%.2fs sentences=%d",
                 time.time() - t_turn,
                 (t_first_audio - t_turn) if t_first_audio else -1,
                 len(full_response))
        return " ".join(full_response)

    # ── Voice input ───────────────────────────────────────────────────────────

    def _get_voice_input(self, mic: "VoiceInput") -> str:
        """Listen to microphone and return transcribed text."""
        text = mic.listen()
        if not text:
            print("[Nothing heard — speak again]", flush=True)
        return text

    # ── Session loop ──────────────────────────────────────────────────────────

    def run(self, episode_title: str = "", guest_name: str = "",
            voice_mode: bool = False, mic_device: int = None,
            whisper_model: str = "base") -> None:
        """Start an interactive podcast session."""
        print("=" * 60)
        print(f"  {self.name} — Podcast Co-Host")
        print(f"  Brain: {self.get_active_model()}")
        mode_str = "VOICE MODE — speak to Aria" if voice_mode else "Type /help for commands"
        print(f"  {mode_str} | /quit to exit")
        print("=" * 60)

        # ── Voice input setup ─────────────────────────────────────────────────
        mic = None
        if voice_mode:
            try:
                from voice.voice_input import VoiceInput, DEFAULT_DEVICE
                effective_device = mic_device if mic_device is not None else DEFAULT_DEVICE
                mic = VoiceInput(device=effective_device, model=whisper_model)
                print(f"\n[Voice mode active — Whisper {whisper_model} | mic device: {effective_device}]")
            except Exception as e:
                print(f"\n[Voice input unavailable: {e} — falling back to text]")
                voice_mode = False

        if not episode_title:
            episode_title = input("\nEpisode title (or press Enter for 'Untitled'): ").strip()
            if not episode_title:
                episode_title = "Untitled Episode"

        if not guest_name:
            guest_name = input("Guest name (or press Enter for solo): ").strip()

        ep_id = self.interview.start_episode(
            title=episode_title,
            topic=episode_title,
            guest_name=guest_name or None,
        )
        log.info("Session started: %s", ep_id)

        opening = self.interview.generate_opening(self.call_ai)
        self.speak(opening)

        last_guest_line = ""
        label = f"{'Guest' if guest_name else 'You'}"

        while True:
            try:
                if voice_mode and mic:
                    user_input = self._get_voice_input(mic)
                    if not user_input:
                        continue
                else:
                    user_input = input(f"{label}: ").strip()
            except (KeyboardInterrupt, EOFError):
                print()
                self._handle_end()
                break

            if not user_input:
                continue

            # ── Slash commands ────────────────────────────────────────────────
            if user_input.startswith("/"):
                if self._handle_command(user_input, last_guest_line):
                    break
                continue

            last_guest_line = user_input
            # Build context for streaming
            system = self.interview.build_system_prompt()
            history = self.interview.get_history_for_llm()
            self.interview.add_guest_turn(user_input)
            response = self.speak_streaming(user_input, system=system, history=history)
            self.interview.add_host_turn(response)
            # Log to memory surface
            if self.memory:
                self.memory.append_to_surface("guest", user_input)
                self.memory.append_to_surface(self.name, response)

            # Log to memory surface
            if self.memory:
                self.memory.append_to_surface("guest", user_input)
                self.memory.append_to_surface(self.name, response)

    def _handle_command(self, cmd: str, last_guest_line: str) -> bool:
        """Handle a slash command. Returns True if session should end."""
        parts = cmd.split(maxsplit=1)
        verb = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if verb == "/quit" or verb == "/exit":
            self._handle_end()
            return True

        elif verb == "/end":
            summary = self.interview.end_episode()
            print(f"\n[Episode ended]\n{summary}\n")

        elif verb == "/brain":
            if not arg:
                models = self.list_models()
                print("\nAvailable brains:")
                for i, m in enumerate(models):
                    print(f"  {i+1}. {m['name']}\n     {m['label']}")
                choice = input("\nEnter model name or number: ").strip()
                if choice.isdigit():
                    idx = int(choice) - 1
                    if 0 <= idx < len(models):
                        arg = models[idx]["name"]
                    else:
                        print("Invalid number.")
                        return False
                else:
                    arg = choice
            try:
                print(self.set_model(arg))
            except ValueError as e:
                print(f"[Error] {e}")

        elif verb == "/voice":
            if not arg:
                voices = self.list_voices()
                print("\nAvailable voices:")
                for v in voices:
                    print(f"  {v['name']:30s} {v['label']}")
            else:
                print(self.set_voice(arg))

        elif verb == "/guest":
            if arg:
                self.interview.current_guest = self.interview.registry.get_or_create(arg)
                print(f"[Guest set to: {arg}]")

        elif verb == "/bio":
            if arg and self.interview.current_guest:
                self.interview.registry.set_bio(self.interview.current_guest.guest_id, arg)
                print("[Bio saved]")

        elif verb == "/quote":
            if last_guest_line and self.interview.current_guest:
                self.interview.save_memorable_quote(last_guest_line)
                print(f"[Quote saved: \"{last_guest_line[:60]}...\"]")

        elif verb == "/followup":
            if arg:
                self.interview.flag_follow_up(arg)
                print(f"[Follow-up thread flagged: {arg}]")

        elif verb == "/open":
            opening = self.interview.generate_opening(self.call_ai)
            self.speak(opening)

        elif verb == "/question":
            q = self.interview.generate_question(arg, self.call_ai)
            self.speak(q)

        elif verb == "/status":
            s = self.interview.status()
            print("\n[STATUS]")
            for k, v in s.items():
                print(f"  {k}: {v}")
            print(f"  brain: {self.get_active_model()}")
            print(f"  voice: {'on' if self.voice_enabled else 'off'}")

        elif verb == "/memory":
            if self.memory:
                print(self.memory.get_memory_stats())
            else:
                print("[Memory not available]")

        elif verb == "/learning":
            if self.learning:
                from memory.learning_engine import get_learning_report
                print(get_learning_report())
            else:
                print("[Learning engine not available]")

        elif verb == "/guests":
            guests = self.interview.registry.list_all()
            if guests:
                print(f"\n{'Name':<25} {'Episodes':>8}  Last seen")
                print("-" * 50)
                for g in guests:
                    print(f"  {g.name:<23} {g.episode_count:>8}  {g.last_seen[:10]}")
            else:
                print("[No guests yet]")

        elif verb == "/episodes":
            eps = self.interview.list_episodes()
            if eps:
                print(f"\n{'Title':<35} {'Guest':<20} {'Turns':>6}  Date")
                print("-" * 75)
                for e in eps:
                    print(f"  {e['title'][:33]:<35} {(e['guest_name'] or 'solo')[:18]:<20} "
                          f"{e['turn_count']:>6}  {(e['started_at'] or '')[:10]}")
            else:
                print("[No past episodes]")

        elif verb == "/mic":
            from voice.voice_input import list_devices, set_mic_device
            if not arg:
                print("\nAvailable microphones:")
                for d in list_devices():
                    print(f"  {d}")
            else:
                try:
                    print(set_mic_device(int(arg)))
                except ValueError:
                    print("[Error] Device must be a number — use /mic to list them")

        elif verb == "/whisper":
            from voice.voice_input import set_whisper_model
            if arg:
                try:
                    print(set_whisper_model(arg))
                except ValueError as e:
                    print(f"[Error] {e}")
            else:
                print("Models: tiny | base | small | medium | large-v3")
                print("Larger = more accurate, slower. 'small' is a good balance.")

        elif verb == "/help":
            print(__doc__.split("Slash commands")[1] if "Slash commands" in __doc__ else
                  "Commands: /brain /voice /mic /whisper /guest /bio /quote /followup "
                  "/open /question /end /status /memory /learning /guests /episodes /quit")

        else:
            print(f"[Unknown command: {verb}] — type /help for the list")

        return False

    def _handle_end(self) -> None:
        if self.interview.current_episode:
            print("\n[Saving episode...]")
            summary = self.interview.end_episode()
            print(summary)
        # Shut down the persistent TTS server cleanly
        try:
            from voice.tts_engine import shutdown_tts_server
            shutdown_tts_server()
        except Exception:
            pass
        try:
            from voice.voice_input import shutdown_whisper_server
            shutdown_whisper_server()
        except Exception:
            pass
        print(f"\nGoodbye from {self.name}!")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    _setup_logging()

    parser = argparse.ArgumentParser(
        description="Aria — Podcast AI Co-Host",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--model", help="Ollama model to use as brain")
    parser.add_argument("--episode", help="Episode title")
    parser.add_argument("--guest", help="Guest name")
    parser.add_argument("--no-voice", action="store_true", help="Disable TTS output")
    parser.add_argument("--voice", action="store_true", help="Enable voice input (speak to Aria)")
    parser.add_argument("--mic", type=int, default=None, help="Microphone device index (see --mics)")
    parser.add_argument("--whisper", default="base",
                        choices=["tiny", "base", "small", "medium", "large-v3"],
                        help="Whisper STT model size (default: base)")
    parser.add_argument("--brains", action="store_true", help="List available brain models")
    parser.add_argument("--voices", action="store_true", help="List available TTS voices")
    parser.add_argument("--mics", action="store_true", help="List available microphone devices")
    args = parser.parse_args()

    # Quick info commands (no full boot needed)
    if args.brains:
        from core.ai_bridge import list_models
        print("\nAvailable brain models:")
        for m in list_models():
            print(f"  {m['name']:<45} {m['label']}")
        sys.exit(0)

    if args.voices:
        from voice.tts_engine import list_voices
        print("\nAvailable voices (edge-tts):")
        for v in list_voices("edge-tts"):
            print(f"  {v['name']:<30} {v['label']}")
        sys.exit(0)

    if args.mics:
        from voice.voice_input import list_devices
        print("\nAvailable microphones:")
        for d in list_devices():
            print(f"  {d}")
        sys.exit(0)

    cohost = Cohost(voice_enabled=not args.no_voice)

    if args.model:
        cohost.set_model(args.model)

    cohost.run(
        episode_title=args.episode or "",
        guest_name=args.guest or "",
        voice_mode=args.voice,
        mic_device=args.mic,
        whisper_model=args.whisper,
    )


if __name__ == "__main__":
    main()
