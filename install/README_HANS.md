# Cohost — Hans's Install Guide

Welcome. This is Aria — your podcast co-host. Three steps from zero to running.

---

## Prerequisites (one-time, ~5 min)

You need these installed on your PC before running the installer:

1. **Python 3.12** — https://www.python.org/downloads/release/python-3120/
   - During install: **check the box "Add python.exe to PATH"** (important).
2. **Ollama for Windows** — https://ollama.com/download/windows
   - After install, sign in once: open a PowerShell and run `ollama signin`. This connects you to Ollama Cloud so you can use the cloud models.
   - The $20/month Cloud plan unlocks the bigger brains. Free tier works too with lower limits.
3. **NVIDIA driver** — already installed if you can play games. If Aria runs slow later, update from https://www.nvidia.com/Download/index.aspx

---

## Install (one-time, ~15 min)

1. Make sure this whole folder is somewhere with at least **15 GB free** (downloads + model weights).
2. Double-click **`INSTALL.bat`**.
3. A window opens and shows progress. Don't close it — wait for "Install complete."
4. If anything failed, send back `install\install_log.txt`.

---

## Self-test (one-time after install, ~2 min)

1. Double-click **`SELFTEST.bat`**.
2. It loads Aria, generates a test sentence, lists your microphones.
3. When done, **email `install\selftest_report.txt`** back to cypherstone.
4. He'll green-light it before you record an episode for real.

---

## Run

**Web mode (recommended):** double-click **`CohostWeb.bat`**. Your browser
opens to `http://localhost:6500` (first free port in 6500–6510) with the
full visual interface. Use this 99% of the time.

**CLI mode:** double-click **`Cohost.bat`** for the terminal-only version.

### How Aria behaves

- **She doesn't interrupt.** By default she's passive — she records what
  you say but doesn't respond unless invited.
- **Wake word:** say **"Aria"** or **"Hey Aria"** and she opens a 90-second
  window where she chimes in freely.
- **Hotkey:** `Ctrl+Alt+A` from anywhere invites her too (works even when
  the browser isn't focused).
- **Cooldown:** after the 90-second window closes she enters a 180-second
  cooldown. Only a wake word reopens the window during cooldown.
- **Free chime mode:** toggle in the sidebar if you want her to reply to
  every turn (useful for solo recordings).
- **"Aria, chime in"** button forces an immediate response.

### Sidebar controls (Web mode)

- **Brain dropdown** — grouped as `Local (installed)` and `Cloud`. Switch
  on the fly. Local list comes from `ollama list`; cloud list is curated.
- **Voice output** toggle — mute Aria's voice but keep her text.
- **Mic selector** — pick which mic she listens on.
- **Dream / Reflect** — end-of-session reflection.
- **Remote help** — opens a 1-hour Cloudflare tunnel + one-time code so
  cypherstone can log in and troubleshoot. Code is single-use; tunnel
  auto-closes after 1 hour or when you click "Stop remote".
- **End Episode** — saves and closes.

### CLI slash commands (Cohost.bat only)

- `/brain` — show the brain menu, pick a different LLM
- `/voice` — list voice options
- `/mic` — list mics, `/mic 5` to switch
- `/status` — what's loaded
- `/help` — full command list
- `/quit` — exit

---

## Brain menu (which LLM Aria uses)

Default is **`gpt-oss:120b-cloud`** — best balance of smart + snappy for podcast chat. The `/brain` command shows the full menu. You can also paste in any Ollama model identifier — the menu is just a curated shortlist, not a lock.

Picks if you want different vibes:
- `gpt-oss:120b-cloud` — recommended default
- `gpt-oss:20b-cloud` — much faster, slightly less smart
- `deepseek-v4-pro:cloud` — biggest, deepest reasoning (slower)
- `kimi-k2.6:cloud` — multimodal, 256K context
- `qwen3-coder:480b-cloud` — only for very technical guests

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Python 3.12 was not detected on PATH" | Install Python 3.12 and check the PATH box during install. Re-run INSTALL.bat. |
| "Ollama not found" | Install from https://ollama.com/download/windows, then run `ollama signin`. |
| "torch.cuda.is_available() is False" but you have NVIDIA | Update your NVIDIA driver. Re-run INSTALL.bat. |
| Aria takes 30+ seconds to respond | TTS fell back to CPU. Check selftest_report.txt — should say `device = cuda`. If not, fix driver. |
| Mic not picking up | In the web UI: change the mic in the sidebar selector. CLI: `/mic` to list, `/mic <number>` to pick. |
| Aria never responds | She's passive by default — say "Aria" or press Ctrl+Alt+A to invite her. Or toggle "Free chime mode" in the sidebar. |
| Remote help button errors | Install cloudflared (`winget install Cloudflare.cloudflared`) and try again. |
| Nothing else | Click "Remote help" in the sidebar and send cypherstone the URL + code. |

---

## What's where

```
INSTALL.bat                ← run me first
SELFTEST.bat               ← run me second, send the .txt back
Cohost.bat                 ← run me to use Aria
install/
  install.ps1              install logic
  selftest.ps1             self-test logic
  install_log.txt          (created at install time)
  selftest_report.txt      (created at self-test time)
  README_HANS.md           this file
cohost.py                  main program
core/                      LLM bridge, config
voice/                     STT + TTS + voice sample
conversation/              interview engine
memory/                    long-term memory
data/                      runtime data (logs, sessions, audio)
```
