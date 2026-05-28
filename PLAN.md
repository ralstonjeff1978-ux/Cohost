# COHOST v2 — Plan

## Context

Cohost is a podcast AI co-host being built for Hans (the host). Aria is the co-host — she **listens, doesn't drive**. She speaks only when Hans turns to her (by name or invitation), with optional chime-in modes for looser segments.

Current state: working voice loop (Whisper STT → Ollama LLM → Chatterbox TTS) but designed as a 1-on-1 conversation. She responds to every utterance, which is wrong for a podcast. This plan adds the host-controlled behavior, a web UI for control, a Windows installer, and remote support.

Target deployment: Hans's PC (RTX 3090, 128GB RAM, Windows). Dev/test on cypherstone's PC (AMD RX 7900 XTX — slower but functionally identical).

---

## Decisions locked

| Decision | Value |
|---|---|
| LLM | `qwen3-coder:480b-cloud` via Ollama (cloud, no local LLM) |
| TTS | Chatterbox XTTS, Aria's cloned voice (`aria_voice.wav`) |
| STT | faster-whisper (`tiny` model for speed) |
| VAD | Silero VAD (already installed) |
| Wake word | "Aria" (case-insensitive, fuzzy match for Whisper variants) |
| Invitation phrases | "what do you think", "your take", "weigh in", "your turn", + configurable list |
| Hotkey | Right Ctrl (configurable) |
| Default mode | `invited` |
| Mode: invited | Only speaks when wake/invitation/hotkey triggered |
| Mode: engaged | + chime-in allowed, 180s cooldown |
| Mode: active | + chime-in allowed, 90s cooldown |
| `/mute` and `/unmute` | Included |
| Mute bypasses everything | Even hotkey can't make her speak while muted |
| Web UI framework | FastAPI + vanilla HTML/JS + WebSocket |
| Web UI port | 6500 (auto-increment on collision) |
| Auto-open browser | Yes, on startup |
| Frontend in installer | Yes, fully offline |
| Web UI replaces terminal | Yes — terminal becomes debug-only |
| GPU support | Auto-detect CUDA → CPU fallback |
| Remote access | Hans-initiated only, reverse SSH to cypherstone's VPS |
| Remote ports | 6500 + auto-increment as needed |
| Remote tunnel lifetime | Auto-close after 1 hour |
| Distribution | Inno Setup installer (single `.exe`) |

---

## Architecture

```
┌──────────────── Hans's machine ─────────────────┐
│                                                  │
│  ┌─── Web Browser (auto-opened) ───┐             │
│  │  Cohost UI @ localhost:6500     │             │
│  └────────────┬────────────────────┘             │
│               │ WebSocket + HTTP                 │
│  ┌────────────▼────────────────────────────┐     │
│  │  FastAPI Server                         │     │
│  │  - /ws (transcript stream, status)      │     │
│  │  - /api/mode, /api/mute, /api/ask, ...  │     │
│  └────────────┬────────────────────────────┘     │
│               │                                  │
│  ┌────────────▼────────────────────────────┐     │
│  │  Conversation Engine (background)       │     │
│  │  - Mic listener (Silero VAD)            │     │
│  │  - Trigger detector                     │     │
│  │  - Mode + cooldown manager              │     │
│  │  - Chime-in evaluator                   │     │
│  │  - Hotkey listener (global)             │     │
│  └─┬──────────┬──────────┬─────────────────┘     │
│    │          │          │                       │
│  ┌─▼──┐   ┌──▼───┐   ┌──▼──────┐                 │
│  │STT │   │ LLM  │   │  TTS    │                 │
│  │svc │   │bridge│   │ server  │                 │
│  └────┘   └──┬───┘   └─────────┘                 │
│              │                                   │
└──────────────┼───────────────────────────────────┘
               │
               ▼
          Ollama Cloud (qwen3-coder:480b-cloud)


  Remote support (when Hans requests):
  Hans's machine ──reverse SSH──▶ cypherstone VPS ◀── cypherstone connects
```

---

## File / module structure

```
F:\cohost\
├── cohost.py                     # CLI entry — launches web mode by default
├── core/
│   ├── ai_bridge.py              # (existing) Ollama streaming
│   ├── config.yaml               # (existing) + new sections: web, modes, remote
│   ├── agent_core.py             # (existing)
│   ├── task_ledger.py            # (existing)
│   ├── tool_registry.py          # (existing)
│   └── verification_engine.py    # (existing)
├── conversation/
│   ├── interview_engine.py       # (existing) + voice_mode awareness
│   ├── trigger_detector.py       # NEW — wake word + invitation matching
│   ├── mode_manager.py           # NEW — invited/engaged/active + cooldown
│   └── chime_in_evaluator.py     # NEW — LLM "should you chime in?" check
├── voice/
│   ├── tts_engine.py             # (existing) + CUDA auto-detect
│   ├── tts_server.py             # (existing) + CUDA device param
│   ├── voice_input.py            # (existing, Silero VAD)
│   ├── whisper_server.py         # (existing)
│   ├── samples/aria_voice.wav    # (existing)
│   └── hotkey_listener.py        # NEW — Right Ctrl global hotkey
├── memory/                       # (existing) memory/learning/dreaming
├── infrastructure/
│   ├── self_evolution.py         # (existing)
│   └── remote_support.py         # NEW — reverse SSH tunnel mgmt
├── web/
│   ├── server.py                 # NEW — FastAPI app
│   ├── routes.py                 # NEW — HTTP endpoints
│   ├── websocket.py              # NEW — WS protocol handler
│   ├── events.py                 # NEW — internal event bus (engine ↔ web)
│   └── static/
│       ├── index.html            # NEW — single-page UI
│       ├── app.js                # NEW — UI logic + WS client
│       └── style.css             # NEW — styling
├── installer/
│   ├── cohost.iss                # NEW — Inno Setup script
│   ├── post_install.ps1          # NEW — first-run setup, Ollama check
│   └── icon.ico                  # NEW
├── data/                         # (existing) runtime data
└── PLAN.md                       # this file
```

---

## Behavior spec

### Trigger detection (`conversation/trigger_detector.py`)

Every transcript is checked against:

1. **Wake word** — literal "Aria" anywhere in the transcript (case-insensitive). Also matches common Whisper mistranscriptions: "Maria", "area", "ariah".
2. **Invitation phrases** — configurable list, default:
   - "what do you think"
   - "your take"
   - "weigh in"
   - "your turn"
   - "what's your opinion"
   - "what would you say"
3. Match returns `(triggered: bool, reason: str)` — UI shows the reason.

### Mode manager (`conversation/mode_manager.py`)

- Tracks current mode: `invited` | `engaged` | `active`
- Tracks last-spoke timestamp for cooldown
- `can_chime_in()` returns True only if mode allows + cooldown expired
- Mode changes via web UI or `/mode` CLI command — broadcast over event bus

### Chime-in evaluator (`conversation/chime_in_evaluator.py`)

Only runs in `engaged` / `active` modes for transcripts that didn't trigger.

Single LLM call:
```
prompt: "Conversation so far: ...\nLast turn: ...\nWould Aria naturally want to chime in here? Answer YES or NO and a 5-word reason."
```

Fast (yes/no), cloud handles it in <1s. If YES → generate full response, mark cooldown. If NO → log decision to event bus (web UI shows "considered, stayed quiet"), move on.

### Hotkey listener (`voice/hotkey_listener.py`)

- Library: `keyboard` (pip install) — works on Windows without admin in most cases
- Default key: Right Ctrl
- On press: emit `force_respond` event
- Configurable in config.yaml

### Web events the UI receives over WebSocket

```
{type: "status",       data: "listening" | "thinking" | "speaking" | "muted"}
{type: "transcript",   data: {speaker: "host"|"guest", text: "...", timestamp: ...}}
{type: "aria_response",data: {text: "...", trigger: "wake_word"|"hotkey"|"chime_in"|...}}
{type: "chime_check",  data: {decision: "YES"|"NO", reason: "..."}}
{type: "cooldown",     data: {remaining_secs: 47}}
{type: "mode_changed", data: "invited"}
{type: "error",        data: "..."}
```

### Web API endpoints

```
GET  /                      → serves index.html
GET  /api/status            → current mode, episode, mute state
POST /api/mode              → {mode: "invited"|"engaged"|"active"}
POST /api/mute              → mute her
POST /api/unmute            → unmute her
POST /api/ask               → force-respond now (same as hotkey)
POST /api/episode/start     → {title, guest_name}
POST /api/episode/end       → end + save transcript
GET  /api/transcript        → full session transcript (for export)
POST /api/remote/request    → start reverse SSH tunnel, returns code
POST /api/remote/end        → close tunnel
WS   /ws                    → real-time events
```

### Remote support (`infrastructure/remote_support.py`)

When Hans clicks "Request Remote Support":

1. Generate one-time code (e.g., 6-digit numeric)
2. Open reverse SSH tunnel from Hans's machine → `cypherstone-VPS:RANDOMPORT`
   - Uses paramiko or `ssh.exe` (built into Windows 10+)
   - Tunnels: Hans's port 6500 → VPS RANDOMPORT
   - More ports get tunneled on-demand if needed (6501, 6502, ...)
3. Display code to Hans, he sends it to cypherstone
4. Auto-close after 1 hour or when Hans clicks "End Session"

Cypherstone side: SSH into VPS, look up the active code/port, connect through.

---

## CUDA auto-detect

In `voice/tts_server.py`:

```python
import torch
device = "cuda" if torch.cuda.is_available() else "cpu"
model = ChatterboxTTS.from_pretrained(device=device)
```

That's the whole change. On Hans's 3090 → CUDA, fast. On cypherstone's AMD → CPU, slow but functional for testing.

---

## Installer (`installer/cohost.iss`)

Inno Setup script bundles:

- Python 3.12 embeddable distribution (~30MB)
- All Python dependencies pre-installed (frozen wheels)
- Chatterbox model weights (`~/.cache/huggingface/...`) — pre-downloaded into the bundle, copied to user's cache on install
- Aria voice sample
- Frontend (HTML/JS/CSS)
- Launcher `Cohost.exe` that runs `cohost.py`
- Start menu shortcut
- Desktop shortcut (optional)

Estimated installer size: 3-5 GB.

Post-install script (`post_install.ps1`):
- Check for Ollama → prompt to install if missing (link to https://ollama.com)
- Pull `qwen3-coder:480b-cloud` model
- Check CUDA → log GPU detected
- Test mic access
- Open browser to localhost:6500

---

## Dependencies (additions over current)

Main env (Python 3.14):
- `fastapi`, `uvicorn[standard]`, `websockets`
- `keyboard` (hotkey)
- `paramiko` (reverse SSH tunnel — already in stack)

Voice env (Python 3.12, existing venv312):
- No new deps — Chatterbox, Whisper, sounddevice already there

---

## Implementation phases

Each phase ends with a manual verification step. I don't move to the next until cypherstone signs off.

### Phase 1 — Trigger + Mode behavior (no UI yet)

- Build `trigger_detector.py`, `mode_manager.py`, `chime_in_evaluator.py`
- Update `cohost.py` voice loop to check triggers + modes
- Add `/mode`, `/mute`, `/unmute` CLI commands
- **Verify:** run `python cohost.py --voice`, confirm she ignores you until you say "Aria" or invitation phrase, mute works, mode switches work

### Phase 2 — CUDA auto-detect

- Update `tts_server.py` for device auto-detection
- **Verify:** on cypherstone's machine stays on CPU (already known); add log line `[Aria] TTS running on: cpu` or `cuda`

### Phase 3 — Web UI (FastAPI + WebSocket + frontend)

- Build `web/server.py`, `web/routes.py`, `web/websocket.py`, `web/events.py`
- Build `web/static/index.html`, `app.js`, `style.css`
- Wire event bus between conversation engine and WS
- Update `cohost.py` to launch FastAPI by default, auto-open browser
- **Verify:** browser opens to localhost:6500, controls work, live transcript streams, mode switch from UI changes behavior

### Phase 4 — Hotkey listener

- `voice/hotkey_listener.py` — global Right Ctrl listener in background thread
- Wired to force-respond event
- **Verify:** press Right Ctrl, Aria responds to whatever was just said

### Phase 5 — Remote support

- `infrastructure/remote_support.py` — reverse SSH tunnel
- Web UI panel for "Request Remote Support" / "End Session"
- VPS-side helper (small script on cypherstone's VPS to look up active tunnels by code)
- **Verify:** Hans clicks request, gets a code; cypherstone connects from VPS via code; tunnel closes after 1 hour

### Phase 6 — Inno Setup installer

- Pre-download model weights into bundle
- Write `cohost.iss` script
- Build single `.exe` installer
- **Verify:** install on a clean Windows VM or second machine, app launches and works without manual Python install

---

## Risks / open questions for cypherstone

1. **Chatterbox CUDA compatibility on RTX 3090** — should work, but not verified. First Hans-machine test will confirm.
2. **`keyboard` library on Windows** — may flag with antivirus. If so, fallback to `pynput`.
3. **Inno Setup bundle size** — model weights make it 3-5GB. Dropbox limit is 350GB for files but personal accounts vary. Acceptable?
4. **VPS for remote support** — uses existing `178.105.121.57`. Need to make sure that VPS stays alive (Hans's support depends on it being reachable).
5. **Chime-in LLM call cost** — every non-trigger transcript in engaged/active mode = one extra cloud LLM call. Could add up over a long recording session. Monitor and revisit if needed.

---

## Verification (full system)

When everything is built and ready for Hans:

1. Fresh install on cypherstone's machine using the Inno installer
2. Web UI auto-opens, status green
3. Start episode, talk normally — Aria stays silent
4. Say "Aria, what do you think?" — she responds
5. Switch to engaged mode — let conversation run, observe chime-in behavior
6. Press Right Ctrl mid-conversation — she responds immediately
7. Hit mute — she goes silent regardless of triggers
8. Request remote support — confirm tunnel opens, code shown
9. From VPS, connect via the code, verify access
10. End remote session — tunnel closes
11. End episode → transcript saved
12. Reboot, confirm app persists session data
