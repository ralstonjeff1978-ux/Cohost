# Feedback from Hans — Live Tester Log

Hans is the live tester on the NVIDIA build of Cohost v1.0. This file is the
running list of every request he sends in. Cypherstone (Jeff) reviews and works
through it.

Format: append a new section per feedback round. Mark items `[ ]` open, `[~]`
in progress, `[x]` done. Include date received and source (email, call, remote
help session).

---

## Triage status

- **Open:** new items waiting to be looked at
- **Planned:** scoped, ready to implement
- **In progress:** being worked on
- **Done:** shipped — note the version it shipped in

---

## v1.0 known limitations (cypherstone-aware, pre-seeded)

- [ ] **Selftest does not yet cover wake-word and remote-help paths.** `install/selftest.ps1` still tests Chatterbox load + mic enumeration; doesn't yet verify the new `/api/aria_mode`, `/api/invite`, `cloudflared` presence, or port-6500 binding. Hans's report may pass even if those pieces are subtly broken.
- [ ] **Cloudflared install can fail silently on some Windows configs.** Installer attempts `winget install Cloudflare.cloudflared` but if winget isn't set up the user gets a warning, not an error. Remote-help button then errors with "cloudflared not found."
- [ ] **Ctrl+Alt+A hotkey registration is best-effort.** On some Windows installs the `keyboard` package needs admin privileges. Falls back gracefully (wake-word and chime button still work) but Hans may report "hotkey doesn't fire."
- [ ] **Voice-to-voice latency on CUDA not yet measured end-to-end on Hans's box.** Selftest measures Chatterbox model-load + single-sentence generate; doesn't measure full mic→Whisper→LLM→TTS→speaker round-trip. Will only know once Hans runs a real episode.
- [ ] **`web/app.py` Flask dev server warning.** Werkzeug prints "do not use this in production" on every boot. Functionally fine for Hans's local box but the warning may scare him. Optional: silence via `WERKZEUG_RUN_MAIN` or migrate to `waitress` for v1.1.

---

## Feedback rounds

### Round 1 — pending

_Awaiting Hans's first selftest report and first-episode feedback._

Expected items to ask about explicitly when he reports back:
- Did `device = cuda` in selftest? What were `first_generate_secs` and `second_generate_secs`?
- Did Aria respond to the wake-word "Aria"?
- Did Ctrl+Alt+A invite her from a non-focused window?
- Did the brain dropdown show his local Ollama models in the "Local (installed)" group?
- Voice quality — does Aria still sound like the locked Nina-modeled sample?
- Anything in the UI that felt clunky or missing.

---

## Process

When Hans sends feedback:

1. Append a new `### Round N — <date>` section here with each item verbatim
2. Triage each item: open / planned / in progress / done
3. For non-trivial items, also create a tracked task (TaskCreate) in the working session
4. Cypherstone closes items by marking `[x]` + noting the version shipped (e.g. `[x] Fixed in v1.1`)
5. Email Hans a one-line "here's what changed since you last reported" with each new build
