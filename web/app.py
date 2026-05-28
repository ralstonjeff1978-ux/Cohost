"""
COHOST WEB — Visual Interface for Aria
=======================================
Flask app serving the podcast co-host UI.

Architecture:
  - Always-listening mic loop runs in a background thread
  - Mutes mic while Aria is speaking (prevents feedback)
  - /api/poll delivers events to the browser (SSE fallback)
  - LLM + TTS run in background threads, broadcast via poll
"""

import json
import logging
import queue
import re
import secrets
import shutil
import subprocess
import sys
import threading
import traceback
import time
from pathlib import Path

from flask import Flask, render_template, request, jsonify, Response

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from core.ai_bridge import (
    call_ai, stream_sentences, set_model, get_active_model, list_models,
)
from conversation.interview_engine import get_interview_engine

log = logging.getLogger("web")

app = Flask(__name__)

# ── Global state ──────────────────────────────────────────────────────────────

_speak_fn = None
_voice_enabled = True
_chime_in = False   # default: wake-word mode (Aria only speaks when invited)
_engine = get_interview_engine()
_status_lock = threading.Lock()
_aria_status = "idle"

_dreamer = None
_experience = None
_evolution = None

# Pending messages for browser polling
_pending_messages: list[dict] = []
_pending_lock = threading.Lock()

# Listening loop state
_listening = False
_listen_thread = None
_listen_device = None
_mic_muted = False
_mic_mute_lock = threading.Lock()

# ── Wake-word + active/cooldown state machine ────────────────────────────────
# Aria is a *second*. By default she only speaks when invited (wake word,
# hotkey, or the "chime in" button). An invitation opens a 90-second active
# window where she chimes in freely. When that closes, a 180-second cooldown
# blocks chime-ins until the next explicit invitation.
ACTIVE_WINDOW_SECS = 90
COOLDOWN_SECS = 180
_WAKE_PATTERN = re.compile(
    r'\b(hey\s+|okay\s+|ok\s+)?aria\b'
    r'|aria[,\s].*(what.*think|your.*take|chime.*in|weigh.*in|go.*ahead)',
    re.IGNORECASE,
)

_invite_lock = threading.Lock()
_active_until: float = 0.0    # unix ts; > now() means we're in the active window
_cooldown_until: float = 0.0  # unix ts; > now() means cooldown is locking out chime-ins
_aria_mode: str = "passive"   # "passive" | "active" | "cooldown"


def _set_aria_mode(mode: str) -> None:
    global _aria_mode
    if mode != _aria_mode:
        _aria_mode = mode
        _broadcast({"type": "aria_mode", "mode": mode})


def _invite_aria(reason: str = "manual") -> None:
    """Open the 90-second active window. Used by wake word, hotkey, and UI button."""
    global _active_until, _cooldown_until
    with _invite_lock:
        _active_until = time.time() + ACTIVE_WINDOW_SECS
        _cooldown_until = 0.0
    _set_aria_mode("active")
    _broadcast({"type": "system",
                "text": f"Aria invited ({reason}). Active for {ACTIVE_WINDOW_SECS}s."})
    log.info("Aria invited via %s — active for %ds", reason, ACTIVE_WINDOW_SECS)


def _refresh_aria_mode() -> str:
    """Recompute the current state based on timers. Returns the live mode."""
    global _active_until, _cooldown_until
    now = time.time()
    with _invite_lock:
        if now < _active_until:
            mode = "active"
        elif _active_until and now < _active_until + COOLDOWN_SECS and _cooldown_until == 0.0:
            # Active window just closed — open the cooldown window once.
            _cooldown_until = _active_until + COOLDOWN_SECS
            _active_until = 0.0
            mode = "cooldown"
        elif _cooldown_until and now < _cooldown_until:
            mode = "cooldown"
        else:
            _cooldown_until = 0.0
            mode = "passive"
    _set_aria_mode(mode)
    return mode


def _should_aria_respond(text: str) -> tuple[bool, str]:
    """
    Decide whether Aria should respond to a transcribed guest turn.

    Order:
      1. Free mode (_chime_in toggle bypasses gating entirely)
      2. Wake-word match → opens a fresh active window
      3. Already inside an active window
      4. Otherwise silent (cooldown or passive)
    """
    if _chime_in:
        return True, "free_mode"
    if _WAKE_PATTERN.search(text or ""):
        _invite_aria("wake_word")
        return True, "wake_word"
    mode = _refresh_aria_mode()
    if mode == "active":
        return True, "active_window"
    return False, mode  # "passive" or "cooldown"


def _init_voice():
    global _speak_fn, _voice_enabled
    try:
        from voice.tts_engine import speak
        _speak_fn = speak
        _voice_enabled = True
        log.info("TTS loaded")
    except Exception as e:
        log.warning("TTS unavailable: %s", e)
        _voice_enabled = False


def _init_hotkey():
    """Register a global hotkey (Ctrl+Alt+A) to invite Aria. Best-effort —
    on some Windows configs the keyboard hook needs admin; if it fails we just
    log and continue (the UI 'Aria, chime in' button still works)."""
    try:
        import keyboard
        keyboard.add_hotkey("ctrl+alt+a", lambda: _invite_aria("hotkey"))
        log.info("Hotkey registered: Ctrl+Alt+A invites Aria")
    except Exception as e:
        log.warning("Hotkey unavailable: %s (UI chime-in button still works)", e)


def _start_mode_refresher():
    """Background thread that broadcasts mode transitions even when nobody
    speaks — so the UI sees cooldown→passive and active→cooldown changes."""
    def loop():
        while True:
            try:
                _refresh_aria_mode()
            except Exception:
                pass
            time.sleep(5)
    threading.Thread(target=loop, daemon=True).start()


def _init_dream():
    global _dreamer, _experience, _evolution
    try:
        from memory.experience_engine import get_experience_engine
        _experience = get_experience_engine()
        from infrastructure.self_evolution import get_self_evolution
        _evolution = get_self_evolution()
        from memory.dream_cycle import get_dream_cycle
        _dreamer = get_dream_cycle(_experience, _evolution)
        log.info("Dream cycle loaded")
    except Exception as e:
        log.warning("Dream cycle unavailable: %s", e)


def _set_status(s: str):
    global _aria_status
    with _status_lock:
        _aria_status = s
    _broadcast({"type": "status", "status": s})


def _broadcast(data: dict):
    with _pending_lock:
        _pending_messages.append(data)
        if len(_pending_messages) > 100:
            _pending_messages.pop(0)


# ── Mic muting during TTS ────────────────────────────────────────────────────

def _speak_and_mute(text: str):
    """Speak text via TTS, muting the mic while speaking to prevent feedback."""
    global _mic_muted
    with _mic_mute_lock:
        _mic_muted = True
    try:
        _speak_fn(text, blocking=True)
    except Exception as e:
        log.error("TTS error: %s", e)
    finally:
        time.sleep(0.3)
        with _mic_mute_lock:
            _mic_muted = False


# ── Always-listening loop ─────────────────────────────────────────────────────

def _listen_loop(device: int):
    """
    Continuous listening loop. Records mic -> Whisper transcribe -> broadcast.
    Pauses while Aria is speaking (mic muted).
    """
    global _listening

    from voice.voice_input import VoiceInput, set_mic_callback
    log.info("Starting listen loop on device %d", device)

    # Wire mic state callbacks so the UI sees real-time mic activity
    def on_mic_event(event):
        _broadcast({"type": "mic_state", "state": event})
    set_mic_callback(on_mic_event)

    _broadcast({"type": "system", "text": f"Mic started on device {device}. Listening..."})
    _broadcast({"type": "mic_state", "state": "listening"})

    mic = VoiceInput(device=device, model="tiny")

    while _listening:
        try:
            with _mic_mute_lock:
                muted = _mic_muted
            if muted:
                time.sleep(0.1)
                continue

            text = mic.listen()

            if not text or not text.strip():
                continue

            lower = text.strip().lower()
            if lower in ("", "you", "thank you.", "thanks for watching!",
                         "thank you for watching.", "thanks.",
                         "the end.", "bye.", "...", "heh."):
                continue

            log.info("Heard: %s", text[:80])
            _broadcast({"type": "mic_state", "state": "transcribed"})
            _broadcast({"type": "heard", "text": text})

            if not _engine.current_episode:
                continue

            _engine.add_guest_turn(text)

            should, reason = _should_aria_respond(text)
            if should:
                log.info("Aria responding (%s)", reason)
                _generate_response(text)
            else:
                log.debug("Aria silent (%s) — guest turn recorded only", reason)

        except Exception as e:
            if _listening:
                log.error("Listen loop error: %s\n%s", e, traceback.format_exc())
                _broadcast({"type": "error", "text": f"Mic error: {e}"})
                time.sleep(1)

    set_mic_callback(None)
    _broadcast({"type": "system", "text": "Mic stopped."})
    _broadcast({"type": "mic_state", "state": "off"})
    log.info("Listen loop ended")


def _start_listening(device: int):
    global _listening, _listen_thread, _listen_device
    if _listening:
        return
    _listening = True
    _listen_device = device
    _listen_thread = threading.Thread(target=_listen_loop, args=(device,), daemon=True)
    _listen_thread.start()


def _stop_listening():
    global _listening
    _listening = False


# ── Response generation ───────────────────────────────────────────────────────

def _generate_response(prompt: str, is_chime: bool = False):
    """
    Run LLM streaming + TTS via a decoupled pipeline.

    LLM thread (this thread) yields sentences and pushes them onto a queue.
    A worker thread drains the queue and speaks each sentence in order.

    Effect: while sentence N is being spoken, sentence N+1 is being generated.
    Without this, the per-turn time was sum(LLM) + sum(TTS); with it, it's
    roughly max(LLM_total, TTS_total) plus first-sentence overhead.
    """
    try:
        _set_status("thinking")
        system = _engine.build_system_prompt()
        history = _engine.get_history_for_llm()

        if is_chime:
            actual_prompt = (
                "Based on the conversation so far, share your thoughts or ask a "
                "follow-up question. Be natural and conversational."
            )
        else:
            actual_prompt = prompt

        sentences: list[str] = []
        tts_queue: queue.Queue = queue.Queue()
        _DONE = object()

        def _tts_worker():
            spoke_anything = False
            while True:
                item = tts_queue.get()
                if item is _DONE:
                    return
                if not _voice_enabled or not _speak_fn:
                    continue
                if not spoke_anything:
                    _set_status("speaking")
                    spoke_anything = True
                try:
                    _speak_and_mute(item)
                except Exception as e:
                    log.error("TTS worker error: %s", e)

        worker = threading.Thread(target=_tts_worker, daemon=True)
        worker.start()

        for sentence in stream_sentences(actual_prompt, system=system, history=history):
            sentences.append(sentence)
            _broadcast({"type": "sentence", "text": sentence})

            if _voice_enabled and _speak_fn:
                spoken = re.sub(r'\*[^*]+\*', '', sentence)
                spoken = re.sub(r'\([^)]+\)', '', spoken).strip()
                if spoken:
                    tts_queue.put(spoken)

        # Signal end-of-stream and wait for TTS to drain
        tts_queue.put(_DONE)
        worker.join()

        full_response = " ".join(sentences)
        if full_response:
            _engine.add_host_turn(full_response)

        _set_status("idle")
        _broadcast({"type": "done", "full_text": full_response})

    except Exception as e:
        log.error("Response failed: %s\n%s", e, traceback.format_exc())
        _set_status("idle")
        _broadcast({"type": "error", "text": f"Aria error: {e}"})
        _broadcast({"type": "done", "full_text": ""})


def _run_dream(llm_caller):
    try:
        _set_status("thinking")
        _broadcast({"type": "system", "text": "Aria is dreaming... reflecting on this session."})
        result = _dreamer.run_dream_cycle(llm_caller)
        insights = result.get("insights_gained", 0)
        improvements = result.get("improvements_identified", 0)
        duration = result.get("duration", 0)
        _broadcast({"type": "system", "text":
            f"Dream complete: {insights} insight(s), "
            f"{improvements} improvement(s). ({duration:.1f}s)"})
        _set_status("idle")
    except Exception as e:
        log.error("Dream failed: %s\n%s", e, traceback.format_exc())
        _broadcast({"type": "error", "text": f"Dream failed: {e}"})
        _set_status("idle")


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    brains = list_models()
    return render_template(
        "index.html",
        brains=brains,
        active_brain=get_active_model(),
        voice_enabled=_voice_enabled,
        chime_in=_chime_in,
        dream_available=_dreamer is not None,
    )


@app.route("/api/start", methods=["POST"])
def start_episode():
    data = request.json or {}
    title = data.get("title", "Untitled Episode")
    guest = data.get("guest", "")
    ep_id = _engine.start_episode(title=title, topic=title, guest_name=guest or None)

    opening = _engine.generate_opening(call_ai)

    if _voice_enabled and _speak_fn:
        def speak_opening():
            _set_status("speaking")
            _speak_and_mute(opening)
            _set_status("idle")
        threading.Thread(target=speak_opening, daemon=True).start()

    return jsonify({"episode_id": ep_id, "opening": opening})


@app.route("/api/send", methods=["POST"])
def send_message():
    data = request.json or {}
    text = data.get("text", "").strip()
    if not text:
        return jsonify({"error": "empty message"}), 400

    _engine.add_guest_turn(text)
    _broadcast({"type": "heard", "text": text})

    if not _chime_in:
        return jsonify({"status": "recorded", "auto_respond": False})

    threading.Thread(target=_generate_response, args=(text,), daemon=True).start()
    return jsonify({"status": "streaming", "auto_respond": True})


@app.route("/api/chime", methods=["POST"])
def request_chime():
    if not _engine.current_episode:
        return jsonify({"error": "no active episode"}), 400
    _invite_aria("manual_chime")
    threading.Thread(target=_generate_response, args=("", True), daemon=True).start()
    return jsonify({"status": "streaming"})


@app.route("/api/invite", methods=["POST"])
def invite_aria():
    """Open the active window without forcing an immediate chime — used by hotkey
    and any UI 'wake up Aria' control that doesn't want an instant response."""
    _invite_aria((request.json or {}).get("source", "api"))
    return jsonify({"status": "active", "mode": _aria_mode,
                    "active_secs": ACTIVE_WINDOW_SECS})


# ── Remote help (Cloudflare quick tunnel + one-time code) ────────────────────
#
# Hans clicks "Remote help" in the UI. We spawn `cloudflared tunnel --url
# http://localhost:<port>`, parse the public *.trycloudflare.com URL it
# prints, and generate a 6-digit access code. Hans reads the URL + code to
# Jeff over the phone. Jeff opens the URL, enters the code once, gets a
# session cookie. Anything from outside 127.0.0.1 without that cookie is
# blocked. Tunnel auto-closes after REMOTE_SESSION_TTL seconds or when Hans
# hits "Stop remote".

REMOTE_SESSION_TTL = 60 * 60  # 1 hour max
_remote_lock = threading.Lock()
_remote: dict = {
    "proc": None,       # cloudflared subprocess
    "url": None,        # https://*.trycloudflare.com
    "code": None,       # 6-digit one-time code
    "session_token": None,  # set after code is consumed
    "expires_at": 0.0,
}


def _spawn_cloudflared(local_port: int) -> tuple[subprocess.Popen, str]:
    """Start cloudflared and return (proc, public_url). Raises on timeout."""
    cf = shutil.which("cloudflared") or shutil.which("cloudflared.exe")
    if not cf:
        raise RuntimeError(
            "cloudflared not found on PATH. Install from "
            "https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/ "
            "or via 'winget install Cloudflare.cloudflared'."
        )
    proc = subprocess.Popen(
        [cf, "tunnel", "--url", f"http://localhost:{local_port}", "--no-autoupdate"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, encoding="utf-8", errors="replace",
    )
    url_re = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
    deadline = time.time() + 30
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line and proc.poll() is not None:
            raise RuntimeError("cloudflared exited before producing a URL")
        if not line:
            continue
        m = url_re.search(line)
        if m:
            # Drain remaining output in background so the pipe doesn't fill
            threading.Thread(
                target=lambda: [None for _ in iter(proc.stdout.readline, "")],
                daemon=True,
            ).start()
            return proc, m.group(0)
    proc.kill()
    raise TimeoutError("cloudflared did not produce a tunnel URL within 30s")


def _stop_remote_tunnel():
    with _remote_lock:
        proc = _remote.get("proc")
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
        _remote.update({"proc": None, "url": None, "code": None,
                        "session_token": None, "expires_at": 0.0})


@app.before_request
def _guard_remote_access():
    """Require the one-time code (or cookie issued after using it) for any
    request that isn't from this machine."""
    if request.path.startswith("/static/"):
        return None
    remote_ip = request.remote_addr or ""
    if remote_ip in ("127.0.0.1", "::1", "localhost"):
        return None
    with _remote_lock:
        if not _remote.get("proc") or time.time() > _remote.get("expires_at", 0):
            return jsonify({"error": "remote access not enabled"}), 403
        session_token = _remote.get("session_token")
        code = _remote.get("code")

    # If we already minted a session token, accept the cookie.
    cookie = request.cookies.get("cohost_remote")
    if session_token and cookie and secrets.compare_digest(cookie, session_token):
        return None

    # Otherwise expect the code (one-time consumption).
    supplied = request.args.get("code") or request.headers.get("X-Remote-Code")
    if code and supplied and secrets.compare_digest(str(supplied), str(code)):
        new_token = secrets.token_urlsafe(24)
        with _remote_lock:
            _remote["session_token"] = new_token
            _remote["code"] = None  # consume
        resp = jsonify({"ok": True, "message": "code accepted — redirecting"})
        resp.set_cookie("cohost_remote", new_token, max_age=REMOTE_SESSION_TTL,
                        secure=True, httponly=True, samesite="Lax")
        return resp

    return jsonify({"error": "remote code required"}), 401


@app.route("/api/remote-help/start", methods=["POST"])
def remote_help_start():
    with _remote_lock:
        if _remote.get("proc"):
            return jsonify({"error": "remote already active",
                            "url": _remote["url"]}), 409
    try:
        # Discover the port Flask actually bound to (set at startup).
        port = int(request.environ.get("SERVER_PORT", 6500))
        proc, url = _spawn_cloudflared(port)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    code = f"{secrets.randbelow(1_000_000):06d}"
    with _remote_lock:
        _remote.update({
            "proc": proc, "url": url, "code": code,
            "session_token": None,
            "expires_at": time.time() + REMOTE_SESSION_TTL,
        })

    def _auto_close():
        time.sleep(REMOTE_SESSION_TTL)
        _stop_remote_tunnel()
        _broadcast({"type": "system", "text": "Remote tunnel auto-closed (1h TTL)."})

    threading.Thread(target=_auto_close, daemon=True).start()
    _broadcast({"type": "system",
                "text": f"Remote help started: {url} (code: {code}) — expires in 1h"})
    return jsonify({"url": url, "code": code, "ttl_secs": REMOTE_SESSION_TTL})


@app.route("/api/remote-help/stop", methods=["POST"])
def remote_help_stop():
    _stop_remote_tunnel()
    _broadcast({"type": "system", "text": "Remote tunnel stopped."})
    return jsonify({"status": "stopped"})


@app.route("/api/remote-help/status")
def remote_help_status():
    with _remote_lock:
        active = bool(_remote.get("proc"))
        return jsonify({
            "active": active,
            "url": _remote.get("url"),
            "expires_at": _remote.get("expires_at", 0),
            "consumed": _remote.get("session_token") is not None,
        })


@app.route("/api/aria_mode")
def get_aria_mode():
    mode = _refresh_aria_mode()
    return jsonify({
        "mode": mode,
        "chime_in": _chime_in,
        "active_until": _active_until,
        "cooldown_until": _cooldown_until,
        "active_window_secs": ACTIVE_WINDOW_SECS,
        "cooldown_secs": COOLDOWN_SECS,
    })


@app.route("/api/dream", methods=["POST"])
def run_dream():
    if not _dreamer:
        return jsonify({"error": "Dream cycle not available"}), 400
    threading.Thread(target=_run_dream, args=(call_ai,), daemon=True).start()
    return jsonify({"status": "dreaming"})


@app.route("/api/mic/start", methods=["POST"])
def start_mic():
    data = request.json or {}
    device = data.get("device")
    if device is None:
        return jsonify({"error": "no device selected"}), 400
    _start_listening(int(device))
    return jsonify({"status": "listening", "device": device})


@app.route("/api/mic/stop", methods=["POST"])
def stop_mic():
    _stop_listening()
    return jsonify({"status": "stopped"})


@app.route("/api/toggle_chime", methods=["POST"])
def toggle_chime():
    global _chime_in
    _chime_in = not _chime_in
    mode = "Auto-respond" if _chime_in else "Wait for Hans"
    return jsonify({"chime_in": _chime_in, "mode": mode})


@app.route("/api/toggle_voice", methods=["POST"])
def toggle_voice():
    global _voice_enabled
    _voice_enabled = not _voice_enabled
    return jsonify({"voice_enabled": _voice_enabled})


@app.route("/api/brain", methods=["POST"])
def change_brain():
    data = request.json or {}
    model = data.get("model", "")
    if model:
        result = set_model(model)
        return jsonify({"result": result, "active": get_active_model()})
    return jsonify({"error": "no model specified"}), 400


@app.route("/api/status")
def get_status():
    with _status_lock:
        status = _aria_status
    info = _engine.status()
    return jsonify({
        "aria_status": status,
        "brain": get_active_model(),
        "voice": _voice_enabled,
        "chime_in": _chime_in,
        "listening": _listening,
        "mic_device": _listen_device,
        **info,
    })


@app.route("/api/end", methods=["POST"])
def end_episode():
    _stop_listening()
    summary = _engine.end_episode()
    return jsonify({"summary": summary})


@app.route("/api/episodes")
def list_episodes():
    return jsonify(_engine.list_episodes())


@app.route("/api/mics")
def list_mics():
    try:
        import sounddevice as sd
        mics = []
        for i, d in enumerate(sd.query_devices()):
            if d.get("max_input_channels", 0) > 0:
                mics.append({"index": i, "name": d["name"],
                             "channels": d["max_input_channels"]})
        return jsonify(mics)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/poll")
def poll_messages():
    with _pending_lock:
        msgs = list(_pending_messages)
        _pending_messages.clear()
    return jsonify(msgs)


# ── Main ──────────────────────────────────────────────────────────────────────

def _kill_existing():
    """Kill any existing cohost web/tts/whisper processes before starting."""
    import signal
    my_pid = os.getpid()
    targets = ("web\\app.py", "web/app.py", "tts_server.py", "whisper_server.py")
    try:
        import subprocess as _sp
        result = _sp.run(
            ["wmic", "process", "get", "ProcessId,CommandLine", "/format:csv"],
            capture_output=True, text=True, timeout=10
        )
        for line in result.stdout.splitlines():
            if not any(t in line for t in targets):
                continue
            parts = line.strip().split(",")
            try:
                pid = int(parts[-1])
                if pid != my_pid:
                    os.kill(pid, signal.SIGTERM)
                    log.info("Killed stale process %d", pid)
            except (ValueError, OSError):
                pass
    except Exception:
        pass


import os

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        handlers=[logging.StreamHandler()],
    )

    _kill_existing()
    time.sleep(1)

    _init_voice()
    _init_dream()
    _init_hotkey()
    _start_mode_refresher()

    # Auto-detect default mic
    try:
        import sounddevice as sd
        default_mic = int(sd.default.device[0])
        default_name = sd.query_devices(default_mic)["name"]
        print(f"  Default mic: [{default_mic}] {default_name}")
    except Exception:
        print("  Default mic: could not detect")

    # Pick the first free port in the 6500–6510 range so Hans gets a
    # predictable URL even if something else owns 6500.
    import socket as _socket

    def _free_port(start=6500, end=6510):
        for p in range(start, end + 1):
            with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
                try:
                    s.bind(("127.0.0.1", p))
                    return p
                except OSError:
                    continue
        return start  # let Flask raise if everything's taken

    port = _free_port()

    print("\n" + "=" * 50)
    print("  ARIA — Podcast Co-Host")
    print(f"  Brain:  {get_active_model()}")
    print(f"  Voice:  {'ON' if _voice_enabled else 'OFF'}")
    print(f"  Dream:  {'ON' if _dreamer else 'OFF'}")
    print(f"  Open:   http://localhost:{port}")
    print(f"  Hotkey: Ctrl+Alt+A invites Aria (90s window)")
    print("=" * 50 + "\n")

    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
