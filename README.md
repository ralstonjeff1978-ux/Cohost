# Cohost — Aria

A podcast co-host AI. Aria listens during your show, waits to be invited,
then chimes in with her take. Brain runs on Ollama (local or cloud), voice
is a Chatterbox XTTS clone driven by a custom sample.

## For Hans

Read [`install/README_HANS.md`](install/README_HANS.md) — it's the install
guide. The three things you need:

1. Install **Python 3.12** (check "Add to PATH" during install)
2. Install **Ollama for Windows** and run `ollama signin`
3. Download this repo as a ZIP, extract, double-click `INSTALL.bat`

When INSTALL finishes, double-click `SELFTEST.bat` and email the
`install/selftest_report.txt` back. After it's green-lit, run `CohostWeb.bat`
to open Aria in your browser.

## What Aria does

- **Listens passively.** She doesn't interrupt — she waits to be invited.
- **Wake word:** say "Aria" or "Hey Aria" and she opens a 90-second window
  where she'll chime in freely. After that, a 180-second cooldown.
- **Hotkey:** `Ctrl+Alt+A` from anywhere also invites her.
- **Free chime mode:** toggle in the sidebar if you want her to reply to
  everything you say (useful for solo recordings).
- **Brain picker:** dropdown shows what you have installed locally on Ollama
  plus the curated cloud-model list. Switch on the fly.
- **Remote help:** one click opens a 1-hour Cloudflare tunnel + one-time
  code so cypherstone can troubleshoot remotely.

## Architecture (for anyone reading the code)

```
cohost.py               CLI entry (legacy / direct-to-shell mode)
web/app.py              Flask app on first free of 6500-6510
web/templates/index.html  UI
core/
  paths.py              COHOST_HOME resolver + config loader
  ai_bridge.py          LLM router (Ollama, OpenAI, Anthropic)
  config.yaml           Config — paths use {COHOST_HOME} placeholders
voice/
  tts_engine.py         TTS dispatcher (Chatterbox XTTS by default)
  tts_server.py         Persistent Chatterbox subprocess in voice/venv312
  voice_input.py        Mic + Whisper STT pipeline (Silero VAD)
  whisper_server.py     Persistent Whisper subprocess
  samples/aria_voice.wav  The voice clone source
conversation/           Interview engine, guest registry, episode tracking
memory/                 Long-term memory, learning, dream cycle
infrastructure/         Self-evolution engine
install/
  install.ps1           Installer (provisions both venvs, pulls models, sets COHOST_HOME)
  selftest.ps1          Hans-facing self-test (writes selftest_report.txt)
```

## Latency notes

LLM TTFT is fast (~3s with `gpt-oss:120b-cloud`). Chatterbox TTS on CUDA is
~1-2s per sentence; on CPU it's ~30s per sentence — which means **Aria needs
a CUDA GPU to be usable in real time**. The installer asks Hans which GPU
his box has and installs the matching torch wheel. The pipeline in
`web/app.py` decouples LLM streaming from TTS playback so sentence N+1 is
generated while N is being spoken.

## Private repo

This repo is private because `voice/samples/aria_voice.wav` is a custom
voice we don't want scraped. Don't flip visibility without removing that
file first.
