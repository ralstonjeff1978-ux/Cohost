"""
TTS ENGINE — Female Voice for Podcast Co-Host
=============================================
Backends (best to worst for human realism):

  elevenlabs     — Best-in-class. Use built-in voices OR Voice Design to
                   generate a brand-new voice from a text description.
                   Needs: pip install elevenlabs + ELEVENLABS_API_KEY
                   https://elevenlabs.io  (~$5/mo starter)

  openai-tts     — Very good. "nova" is warm/conversational American female.
                   Needs: pip install openai + OPENAI_API_KEY

  coqui-xtts     — Free offline voice cloning from a sample WAV file.
                   Needs: pip install TTS + voice sample in voice/samples/

  edge-tts       — Free fallback, synthetic-sounding.
                   Needs: pip install edge-tts

  pyttsx3        — Offline Windows SAPI, last resort.

Voice Design (ElevenLabs) — create a UNIQUE voice from a text description:
    Use design_voice() to generate a voice with specific characteristics
    without cloning any real person. Safe for commercial/public podcast use.

Usage:
    from voice.tts_engine import speak, set_voice, design_voice
    speak("Welcome back to the show!")
    design_voice("American female, late 20s, warm and confident, slightly husky, podcast energy")
"""

import asyncio
import logging
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import List, Optional

from core.paths import AUDIO_DIR, VOICE_SAMPLE, VOICE_VENV, load_config

log = logging.getLogger("tts")


def _load_voice_cfg() -> dict:
    cfg = load_config()
    return cfg.get("voice", {})


_active_voice: Optional[str] = None
_active_backend: Optional[str] = None


# ── ElevenLabs recommended female voices ─────────────────────────────────────
# These are the built-in voices. You can add custom cloned voices via the dashboard.

_ELEVENLABS_FEMALE_VOICES = [
    {"name": "Aria",        "label": "Aria — Natural, expressive (recommended for podcast)"},
    {"name": "Rachel",      "label": "Rachel — Calm, warm, American"},
    {"name": "Domi",        "label": "Domi — Strong, confident"},
    {"name": "Bella",       "label": "Bella — Soft, friendly"},
    {"name": "Elli",        "label": "Elli — Quirky, energetic, young"},
    {"name": "Charlotte",   "label": "Charlotte — Seductive, confident (British)"},
    {"name": "Dorothy",     "label": "Dorothy — Warm, pleasant (British)"},
    {"name": "Sarah",       "label": "Sarah — Soft, friendly American"},
    {"name": "Alice",       "label": "Alice — Confident, British"},
    {"name": "Matilda",     "label": "Matilda — Warm, friendly American"},
]

# OpenAI TTS female voices
_OPENAI_FEMALE_VOICES = [
    {"name": "nova",    "label": "Nova — Warm, optimistic, conversational (best for podcast)"},
    {"name": "shimmer", "label": "Shimmer — Soft, clear, pleasant"},
    {"name": "alloy",   "label": "Alloy — Neutral, balanced"},
]

# edge-tts curated female voices
_EDGE_FEMALE_VOICES = [
    {"name": "en-US-AriaNeural",       "label": "Aria — Natural, conversational (US)"},
    {"name": "en-US-JennyNeural",      "label": "Jenny — Warm, friendly (US)"},
    {"name": "en-US-MichelleNeural",   "label": "Michelle — Clear, upbeat (US)"},
    {"name": "en-US-SaraNeural",       "label": "Sara — Bright, energetic (US)"},
    {"name": "en-GB-SoniaNeural",      "label": "Sonia — Polished, British"},
    {"name": "en-AU-NatashaNeural",    "label": "Natasha — Warm, Australian"},
]


# ── ElevenLabs ────────────────────────────────────────────────────────────────

def _elevenlabs_speak(text: str, voice_name: str) -> None:
    try:
        from elevenlabs.client import ElevenLabs
        from elevenlabs import play
    except ImportError:
        raise RuntimeError("ElevenLabs not installed. Run: pip install elevenlabs")

    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "ELEVENLABS_API_KEY not set. Get a key at https://elevenlabs.io "
            "then run: set ELEVENLABS_API_KEY=your_key_here"
        )

    client = ElevenLabs(api_key=api_key)
    audio = client.generate(
        text=text,
        voice=voice_name,
        model="eleven_turbo_v2_5",   # fast + high quality
    )
    play(audio)


def design_voice(description: str, voice_name: str = "cohost_custom",
                  preview_text: str = "Hey, welcome to the show! I'm so excited for today.") -> Optional[str]:
    """
    Generate a brand-new synthetic voice from a text description using
    ElevenLabs Voice Design. No real person is cloned — this creates a
    completely unique voice to your spec. Safe for commercial podcast use.

    Args:
        description:  Natural language description of the voice characteristics.
                      e.g. "American female, late 20s, warm but confident,
                           slightly husky, energetic podcast host energy,
                           sounds smart and a little quirky"
        voice_name:   Name to save the voice under in your ElevenLabs account.
        preview_text: Text to speak as a preview after generation.

    Returns:
        The voice_id string if successful, None on failure.

    Example:
        design_voice(
            "American female, late 20s to early 30s, warm and inviting but "
            "confident. Slightly husky. Fast-talking, excited about everything. "
            "Sounds like she's genuinely delighted to be talking to you. "
            "Smart but approachable, a little quirky.",
            voice_name="Aria_custom"
        )
    """
    try:
        from elevenlabs.client import ElevenLabs
    except ImportError:
        print("ElevenLabs not installed. Run: pip install elevenlabs")
        return None

    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        print("ELEVENLABS_API_KEY not set. Get a key at https://elevenlabs.io")
        return None

    try:
        client = ElevenLabs(api_key=api_key)

        print(f"Designing voice: {voice_name!r}")
        print(f"Description: {description}")
        print("Generating... (this takes ~10-20 seconds)")

        # Voice Design API — generates a unique new voice
        result = client.text_to_voice.create_previews(
            voice_description=description,
            text=preview_text,
        )

        if not result.previews:
            print("[Error] No previews returned.")
            return None

        # Play the first preview
        preview = result.previews[0]
        print(f"\nPreview generated. Playing...")

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            with open(tmp_path, "wb") as f:
                f.write(preview.audio_sample)
            _play_audio_file(tmp_path)
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

        # Ask if they want to save it
        save = input("\nSave this voice to your ElevenLabs account? (y/n): ").strip().lower()
        if save == "y":
            saved = client.text_to_voice.create_voice_from_preview(
                voice_name=voice_name,
                voice_description=description,
                generated_voice_id=preview.generated_voice_id,
            )
            voice_id = saved.voice_id
            print(f"Voice saved as '{voice_name}' (ID: {voice_id})")
            print(f"Use it with: set_voice('{voice_name}')")

            # Auto-set as active voice
            set_voice(voice_name)
            return voice_id
        else:
            print("Not saved. Run design_voice() again to try a different description.")
            return None

    except Exception as e:
        print(f"[Error] Voice design failed: {e}")
        return None


def _elevenlabs_list_voices() -> List[dict]:
    """Fetch actual voice list from ElevenLabs API if key is available."""
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        return _ELEVENLABS_FEMALE_VOICES   # return defaults if no key

    try:
        from elevenlabs.client import ElevenLabs
        client = ElevenLabs(api_key=api_key)
        voices = client.voices.get_all()
        return [
            {"name": v.name, "label": f"{v.name} ({v.labels.get('accent','')}, {v.labels.get('description','')})"[:80]}
            for v in voices.voices
        ]
    except Exception as e:
        log.warning("Could not fetch ElevenLabs voices: %s", e)
        return _ELEVENLABS_FEMALE_VOICES


# ── Coqui XTTS (free voice cloning) ─────────────────────────────────────────
# This is how the Jason Asano voice was made — clone any voice from a short sample.
# For the female co-host: provide a 10-30s clean WAV/MP3 of the voice you want.
#
# Install: pip install TTS  (~2GB download, one-time)
# Voice sample: ships at voice/samples/aria_voice.wav (resolved via core.paths.VOICE_SAMPLE)

_XTTS_MODEL = "tts_models/multilingual/multi-dataset/xtts_v2"
_DEFAULT_VOICE_SAMPLE = str(VOICE_SAMPLE)
_VENV_PYTHON   = str(VOICE_VENV)
_TTS_SERVER_PY = str(Path(__file__).parent / "tts_server.py")

# Persistent server process — loaded once, reused for every speak() call
_tts_proc = None


def _start_tts_server(voice_sample: str) -> "subprocess.Popen":
    import subprocess as _sp
    print("[Aria] Starting voice engine...", flush=True)
    proc = _sp.Popen(
        [_VENV_PYTHON, _TTS_SERVER_PY],
        stdin=_sp.PIPE, stdout=_sp.PIPE,
        stderr=_sp.DEVNULL, text=True, bufsize=1,
        encoding="utf-8", errors="replace",
    )
    proc.stdin.write(voice_sample + "\n")
    proc.stdin.flush()
    import time
    deadline = time.time() + 120
    while time.time() < deadline:
        line = proc.stdout.readline().strip()
        if line == "READY":
            print("[Aria] Voice engine ready.", flush=True)
            return proc
        if line.startswith("LOADING"):
            detail = line[len("LOADING"):].strip()
            if detail:
                print(f"[Aria] Loading voice model... ({detail})", flush=True)
                log.info("TTS device: %s", detail)
            else:
                print("[Aria] Loading voice model (Aria voice)...", flush=True)
        if line.startswith("ERROR"):
            raise RuntimeError(f"TTS server error: {line}")
    raise TimeoutError("TTS server timed out")


def _get_tts_server(voice_sample: str = _DEFAULT_VOICE_SAMPLE):
    global _tts_proc
    # Auto-recover if server died
    if _tts_proc is not None and _tts_proc.poll() is not None:
        log.warning("TTS server died (exit %s) — restarting", _tts_proc.poll())
        _tts_proc = None
    if _tts_proc is None:
        _tts_proc = _start_tts_server(voice_sample)
    return _tts_proc


def _sanitize_for_tts(text: str) -> str:
    """Replace Unicode characters that break cp1252 pipes and sound wrong in TTS."""
    replacements = {
        "‑": "-",    # non-breaking hyphen
        "–": "-",    # en dash
        "—": " - ",  # em dash
        "‘": "'",    # left single quote
        "’": "'",    # right single quote
        "“": '"',    # left double quote
        "”": '"',    # right double quote
        "…": "...",  # ellipsis
        " ": " ",    # narrow no-break space
        " ": " ",    # non-breaking space
        "‐": "-",    # hyphen
        "‒": "-",    # figure dash
        "―": " - ",  # horizontal bar
        "′": "'",    # prime
        "″": '"',    # double prime
    }
    for char, repl in replacements.items():
        text = text.replace(char, repl)
    return text


def _chatterbox_speak(text: str, voice_sample: str = _DEFAULT_VOICE_SAMPLE) -> None:
    """Speak via persistent Chatterbox server. Auto-restarts if server crashed."""
    import time

    if not Path(voice_sample).exists():
        raise FileNotFoundError(f"Voice sample not found: {voice_sample}")

    text = _sanitize_for_tts(text)

    for attempt in range(2):      # retry once on server crash
        try:
            proc = _get_tts_server(voice_sample)
            proc.stdin.write(text.strip().replace("\n", " ") + "\n")
            proc.stdin.flush()

            deadline = time.time() + 60
            while time.time() < deadline:
                response = proc.stdout.readline().strip()
                if not response:
                    # Empty line = server may have died
                    if proc.poll() is not None:
                        raise RuntimeError("TTS server exited unexpectedly")
                    continue
                if response.startswith("ERROR"):
                    log.error("TTS error: %s", response)
                    return
                wav_path = response
                if Path(wav_path).exists():
                    try:
                        _play_audio_file(wav_path)
                    finally:
                        time.sleep(0.15)
                        try:
                            os.unlink(wav_path)
                        except Exception:
                            pass
                    return
            log.warning("TTS server did not return a file within 60s")
            return
        except RuntimeError as e:
            log.warning("TTS attempt %d failed: %s — %s",
                        attempt + 1, e, "retrying" if attempt == 0 else "giving up")
            global _tts_proc
            _tts_proc = None   # force restart on next call
            if attempt == 1:
                log.error("TTS failed after retry")


def shutdown_tts_server() -> None:
    """Cleanly shut down the persistent TTS server. Call on app exit."""
    global _tts_proc
    if _tts_proc and _tts_proc.poll() is None:
        try:
            _tts_proc.stdin.write("QUIT\n")
            _tts_proc.stdin.flush()
            _tts_proc.wait(timeout=5)
        except Exception:
            _tts_proc.kill()
        _tts_proc = None


def _coqui_xtts_speak(text: str, voice_sample: str = _DEFAULT_VOICE_SAMPLE,
                       language: str = "en") -> None:
    """Legacy alias — routes to chatterbox."""
    _chatterbox_speak(text, voice_sample)


def set_voice_sample(sample_path: str) -> str:
    """Set the voice sample file path for Coqui XTTS cloning."""
    global _active_voice
    _active_voice = sample_path   # for xtts, the "voice" is the sample path
    return f"Voice sample set to: {sample_path}"


# ── OpenAI TTS ────────────────────────────────────────────────────────────────

def _openai_speak(text: str, voice: str = "nova") -> None:
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError("OpenAI SDK not installed. Run: pip install openai")

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "OPENAI_API_KEY not set. "
            "Run: set OPENAI_API_KEY=your_key_here"
        )

    client = OpenAI(api_key=api_key)

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        response = client.audio.speech.create(
            model="tts-1-hd",     # hd = better quality
            voice=voice,
            input=text,
        )
        response.stream_to_file(tmp_path)
        _play_audio_file(tmp_path)
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


# ── edge-tts ──────────────────────────────────────────────────────────────────

def _edge_speak_sync(text: str, voice: str, rate: str, volume: str, pitch: str,
                     output_mode: str, output_dir: str) -> None:
    try:
        import edge_tts
    except ImportError:
        raise RuntimeError("edge-tts not installed. Run: pip install edge-tts")

    async def _run():
        communicate = edge_tts.Communicate(text, voice, rate=rate, volume=volume, pitch=pitch)
        if output_mode in ("file", "both"):
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            import time
            fname = Path(output_dir) / f"tts_{int(time.time())}.mp3"
            await communicate.save(str(fname))
            if output_mode == "both":
                _play_audio_file(str(fname))
        else:
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                tmp_path = tmp.name
            try:
                await communicate.save(tmp_path)
                _play_audio_file(tmp_path)
            finally:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

    asyncio.run(_run())


# ── pyttsx3 ───────────────────────────────────────────────────────────────────

def _pyttsx3_speak(text: str, voice_index: int) -> None:
    try:
        import pyttsx3
    except ImportError:
        raise RuntimeError("pyttsx3 not installed. Run: pip install pyttsx3")
    engine = pyttsx3.init()
    voices = engine.getProperty("voices")
    if voices and voice_index < len(voices):
        engine.setProperty("voice", voices[voice_index].id)
    engine.setProperty("rate", 175)
    engine.say(text)
    engine.runAndWait()


# ── Audio playback ────────────────────────────────────────────────────────────


def _find_ffplay() -> Optional[str]:
    """Locate ffplay.exe on PATH, or in common Windows install locations."""
    found = shutil.which("ffplay")
    if found:
        return found
    # Common Windows install locations (winget, choco, scoop, system ffmpeg)
    user = os.environ.get("USERPROFILE", "")
    candidates = [
        Path(user) / "AppData/Local/Microsoft/WinGet/Links/ffplay.exe",
        Path("C:/ProgramData/chocolatey/bin/ffplay.exe"),
        Path(user) / "scoop/shims/ffplay.exe",
        Path("C:/ffmpeg/bin/ffplay.exe"),
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return None


def _play_audio_file(path: str) -> None:
    """Play a WAV or MP3 file, blocking until done. Tries fastest methods first."""
    import subprocess as _sp

    path = str(path)

    # 1. winsound — built-in Windows, zero dependencies, WAV only, instant
    if path.lower().endswith(".wav"):
        try:
            import winsound
            winsound.PlaySound(path, winsound.SND_FILENAME)
            return
        except Exception:
            pass

    # 2. ffplay — handles WAV + MP3, no window
    ffplay = _find_ffplay()
    if ffplay:
        try:
            _sp.run(
                [ffplay, "-nodisp", "-autoexit", "-loglevel", "quiet", path],
                check=True
            )
            return
        except Exception:
            pass

    # 3. PowerShell SoundPlayer — WAV only fallback
    if path.lower().endswith(".wav"):
        try:
            _sp.run(
                ["powershell", "-c",
                 f"(New-Object Media.SoundPlayer '{path}').PlaySync()"],
                check=False, capture_output=True
            )
            return
        except Exception:
            pass

    # 4. Last resort — open in default media player (non-blocking)
    os.startfile(path)


# ── Public API ────────────────────────────────────────────────────────────────

def speak(text: str, blocking: bool = True) -> None:
    """
    Speak text using the configured TTS backend.

    Args:
        text:     The text to speak aloud.
        blocking: Wait for speech to finish before returning. Set False for
                  non-blocking background speech during conversation.
    """
    if not text or not text.strip():
        return

    if not blocking:
        t = threading.Thread(target=speak, args=(text, True), daemon=True)
        t.start()
        return

    cfg = _load_voice_cfg()
    if not cfg.get("enabled", True):
        return

    backend = _active_backend or cfg.get("backend", "elevenlabs")
    voice = _active_voice or cfg.get("voice_name", "Aria")

    log.debug("TTS [%s] voice=%s len=%d", backend, voice, len(text))

    try:
        if backend == "elevenlabs":
            _elevenlabs_speak(text, voice)

        elif backend == "openai-tts":
            _openai_speak(text, voice)

        elif backend in ("coqui-xtts", "chatterbox-xtts"):
            sample = _active_voice or cfg.get("xtts_voice_sample", _DEFAULT_VOICE_SAMPLE)
            _chatterbox_speak(text, voice_sample=sample)

        elif backend == "edge-tts":
            _edge_speak_sync(
                text=text,
                voice=voice,
                rate=cfg.get("rate", "+5%"),
                volume=cfg.get("volume", "+0%"),
                pitch=cfg.get("pitch", "+0Hz"),
                output_mode=cfg.get("output_mode", "speaker"),
                output_dir=cfg.get("output_dir", str(AUDIO_DIR)),
            )

        elif backend == "pyttsx3":
            _pyttsx3_speak(text, cfg.get("pyttsx3_voice_index", 1))

        else:
            log.warning("Unknown TTS backend: %s", backend)

    except EnvironmentError as e:
        # Missing API key — print clearly so user knows what to do
        print(f"\n[VOICE] {e}\n")
    except Exception as e:
        log.error("TTS error (%s): %s — trying edge-tts fallback", backend, e)
        if backend not in ("edge-tts", "pyttsx3"):
            try:
                _edge_speak_sync(
                    text=text, voice="en-US-AriaNeural",
                    rate="+5%", volume="+0%", pitch="+0Hz",
                    output_mode="speaker", output_dir=str(AUDIO_DIR)
                )
            except Exception as e2:
                log.error("edge-tts fallback also failed: %s", e2)


def set_voice(voice_name: str) -> str:
    global _active_voice
    _active_voice = voice_name
    return f"Voice set to: {voice_name}"


def set_backend(backend: str) -> str:
    global _active_backend
    valid = {"elevenlabs", "openai-tts", "chatterbox-xtts", "coqui-xtts", "edge-tts", "pyttsx3"}
    if backend not in valid:
        raise ValueError(f"Unknown backend '{backend}'. Valid: {valid}")
    _active_backend = backend
    return f"TTS backend set to: {backend}"


def get_active_voice() -> str:
    if _active_voice:
        return _active_voice
    return _load_voice_cfg().get("voice_name", "Aria")


def get_active_backend() -> str:
    if _active_backend:
        return _active_backend
    return _load_voice_cfg().get("backend", "elevenlabs")


def list_voices(backend: Optional[str] = None) -> List[dict]:
    cfg = _load_voice_cfg()
    b = backend or _active_backend or cfg.get("backend", "elevenlabs")
    if b == "elevenlabs":
        return _elevenlabs_list_voices()
    elif b == "openai-tts":
        return _OPENAI_FEMALE_VOICES
    elif b == "edge-tts":
        return _EDGE_FEMALE_VOICES
    elif b == "pyttsx3":
        try:
            import pyttsx3
            engine = pyttsx3.init()
            voices = engine.getProperty("voices")
            return [{"name": str(i), "label": f"{v.name}"} for i, v in enumerate(voices)]
        except Exception:
            return []
    return []


def preview_voice(voice_name: str, text: str = "Hey, welcome back to the show! I'm so excited for today's guest.") -> None:
    global _active_voice
    original = _active_voice
    set_voice(voice_name)
    speak(text)
    _active_voice = original


def check_keys() -> dict:
    """Report which API keys are set."""
    return {
        "ELEVENLABS_API_KEY": "set" if os.environ.get("ELEVENLABS_API_KEY") else "NOT SET",
        "OPENAI_API_KEY":     "set" if os.environ.get("OPENAI_API_KEY") else "NOT SET",
    }


# ── Tool registration ─────────────────────────────────────────────────────────

def register_tools(registry) -> None:
    registry.register("voice_speak", speak)
    registry.register("voice_set_voice", set_voice)
    registry.register("voice_set_backend", set_backend)
    registry.register("voice_list_voices", list_voices)
    registry.register("voice_preview", preview_voice)
    registry.register("voice_get_active", get_active_voice)
    registry.register("voice_check_keys", check_keys)
    registry.register("voice_design", design_voice)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--design":
        desc = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else \
            "American female, late 20s, warm and confident, slightly husky, energetic podcast host, smart and quirky"
        design_voice(desc)
        sys.exit(0)
    if len(sys.argv) > 1 and sys.argv[1] == "--list":
        backend = sys.argv[2] if len(sys.argv) > 2 else None
        for v in list_voices(backend):
            print(f"  {v['name']:30s} {v['label']}")
        sys.exit(0)
    if len(sys.argv) > 1 and sys.argv[1] == "--keys":
        for k, v in check_keys().items():
            print(f"  {k}: {v}")
        sys.exit(0)
    if len(sys.argv) > 1 and sys.argv[1] == "--preview":
        voice = sys.argv[2] if len(sys.argv) > 2 else get_active_voice()
        text = " ".join(sys.argv[3:]) if len(sys.argv) > 3 else \
            "Hey, welcome to the show! I'm your co-host, and I am so pumped for today."
        print(f"Previewing voice: {voice} via {get_active_backend()}")
        preview_voice(voice, text)
        sys.exit(0)
    text = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else \
        "Hey! Welcome back. I'm Aria, your podcast co-host. Let's get into it!"
    speak(text)
