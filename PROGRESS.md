# COHOST — Session Progress Log

**Last update:** 2026-05-23
**Goal:** Ship an installable cohost build to Hans (NVIDIA RTX 3090, Windows).

---

## What landed in this session

### 1. Diagnosis of the original 120 s lag

Added `[TIMING]` instrumentation. Confirmed via real timing data that the lag was **Chatterbox TTS running on CPU**, not the LLM or STT.

- `voice/voice_input.py` — logs `vad=…s stt=…s`, bumped Whisper timeout 15→30 s, explicit `WHISPER TIMEOUT` warning instead of silent empty return.
- `core/ai_bridge.py` — logs `llm_request_start`, `llm_ttft`, `llm_first_sentence`, `llm_total` with token + sentence counts.
- `cohost.py` (`speak_streaming`) — logs `turn_first_audio`, `tts_sentence` per sentence, `turn_total`.

### 2. ROCm-on-Windows attempt (rolled back)

Installed AMD nightly ROCm 7.10 alpha wheels for testing on the local 7900 XTX. Hit a series of known bugs:
- SDPA attention deadlock (filed against AMD)
- MIOpen workspace allocation issues
- Kernel cache corruption on `==` comparison after first inference call (AMD bug #5834 territory)
- Triggered Adrenalin driver-event popups during process kills

**Rollback complete.** venv312 is back on CPU torch 2.6.0. Chatterbox patch reverted to upstream.

Detailed research summary: ROCm on Windows is not production-ready for transformer-style TTS workloads as of May 2026. Linux ROCm is mature; community wrapper `devnen/Chatterbox-TTS-Server` explicitly states "ROCm only supports Linux — use CPU mode on Windows with AMD GPUs."

**Local-dev fast-TTS option still on the table:** WSL2 + Ubuntu + ROCm Linux. Saved for a later session.

### 3. GPU auto-detect in `voice/tts_server.py`

Same code works on NVIDIA CUDA AND AMD ROCm — ROCm-built PyTorch exposes HIP under the `torch.cuda.*` namespace. The line is:

```python
device = "cuda" if torch.cuda.is_available() else "cpu"
```

Parent process (`voice/tts_engine.py`) now reads the device name out of the `LOADING device=… gpu=…` line and logs it.

### 4. Brain selector — full Ollama Cloud menu

`core/config.yaml` `brain_selector.available` now lists 18 Ollama Cloud models grouped by purpose:

- **General chat (best for podcast)** — `gpt-oss:120b-cloud` (default), `gpt-oss:20b-cloud`, `gemma4:cloud`
- **Reasoning + smart** — `deepseek-v4-flash:cloud`, `deepseek-v4-pro:cloud`, `deepseek-v3.2:cloud`, `gemini-3-flash-preview:cloud`
- **Multimodal / huge context** — `kimi-k2.6:cloud`, `qwen3.5:cloud`
- **Agentic / flagship** — `glm-5.1:cloud`, `glm-5:cloud`, `minimax-m2.7:cloud`
- **Coding (for tech guests)** — `qwen3-coder:480b-cloud`, `qwen3-coder-next:cloud`, `glm-4.7:cloud`, `devstral-small-2:cloud`
- **Light + fast** — `ministral-3:cloud`, `nemotron-3-nano:cloud`, `nemotron-3-super:cloud`
- **Local fallback** — three abliterated local models

`core/ai_bridge.py:set_model()` was relaxed: the curated list is a menu, not a hard whitelist. Hans can `/brain <any-name>` and use models Ollama hasn't released yet without editing config.

### 5. Hans-ready installer (NEW)

Built a `.zip`-able deliverable inside `F:\cohost\`:

| File | What it does |
|---|---|
| `INSTALL.bat` | Hans double-clicks first — wraps install.ps1 with proper execution policy |
| `SELFTEST.bat` | Hans double-clicks after install — produces selftest_report.txt for Hans to email back |
| `Cohost.bat` | Hans double-clicks to run Aria in voice mode |
| `install/install.ps1` | Idempotent installer — verifies Python 3.12, creates `.venv` + `voice/venv312`, installs CUDA-built torch on NVIDIA hardware (CPU fallback otherwise), installs chatterbox-tts with `--no-deps` + all transitive deps, pre-downloads Chatterbox weights, pulls the default Ollama model |
| `install/selftest.ps1` | 7-section self-test: hardware → venvs → torch+CUDA → Ollama → Chatterbox load + timed generation → mic devices → done |
| `install/README_HANS.md` | Hans's installation + usage guide |

**PowerShell-5.1 compatibility verified.** Initial scripts had LF line endings which broke PS 5.1's here-string terminator parsing. Converted to CRLF and confirmed both scripts parse and run.

**Selftest dress-rehearsed on cypherstone's machine.** Sections 1–4 produce correct output (hardware, venvs, torch=2.6.0+cpu, Ollama with all models listed). Section 5 successfully loads Chatterbox and starts generation (ran at 12 it/s on CPU — Hans's CUDA will do the same at 100+ it/s). Section 6 microphone enumeration verified to use the same robust subprocess pattern.

### 6. Cleanup

Removed all `_smoketest_*.py`, `_smoketest_out*.txt`, `check_pipecat*.py` diagnostic files from earlier in the session. cohost root is clean and ready to zip.

---

## Hans's workflow (what we'll tell him)

1. **Prereqs (one-time, 5 min):**
   - Install Python 3.12 from python.org — check "Add to PATH"
   - Install Ollama from ollama.com/download/windows, then `ollama signin` once
   - NVIDIA driver should be current
2. **Drop the `cohost` folder somewhere with 15 GB free.**
3. **Double-click `INSTALL.bat`** — 10–20 min, downloads ~5 GB of model + library bundles.
4. **Double-click `SELFTEST.bat`** — produces `install\selftest_report.txt`. Hans emails the file to cypherstone.
5. **cypherstone reviews the report**, confirms `cuda.is_available = True`, `cuda.device_name = NVIDIA GeForce RTX 3090`, `first_generate_secs ≈ 1–3`, `second_generate_secs` similar. If all green:
6. **Double-click `Cohost.bat`** — Aria runs on the 3090.

---

## What's still pending

- [ ] Phase 1 from PLAN.md — trigger detector, mode manager, chime-in evaluator. Right now Aria responds to every utterance. For Hans's actual podcast use case she needs to wait for "Aria, …" or invitation phrases. Next session.
- [ ] Phase 3 — Web UI (FastAPI + WS).
- [ ] Phase 4 — Right-Ctrl hotkey.
- [ ] Phase 5 — Reverse SSH remote support (would let cypherstone connect into Hans's running cohost over the VPS).
- [ ] Phase 6 — Inno Setup `.exe` wrapper (we currently ship a `.zip` + `INSTALL.bat`, which works fine but `.exe` is more polished).
- [ ] WSL2 + ROCm Linux for fast local-dev TTS on cypherstone's 7900 XTX (separate side-quest, doesn't block Hans).

---

## Quick re-entry checklist

1. Read this file.
2. To package for Hans: zip the entire `F:\cohost\` folder (exclude `data/` runtime outputs if you want a clean send).
3. To test installer locally on a fresh Windows machine / VM: run `INSTALL.bat`, then `SELFTEST.bat`, check `install\selftest_report.txt`.
4. To pick up Phase 1 work: see PLAN.md sections "Trigger detection" and "Mode manager".
