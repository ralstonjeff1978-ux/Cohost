"""
TTS SERVER — Persistent Chatterbox process
==========================================
Runs in venv312. Loads the model ONCE, then serves requests via stdin/stdout.
Eliminates the 20-second model reload that causes inconsistent playback.

Protocol (line-based over stdin/stdout):
  stdin  <- text to speak  (one line)
  stdout -> path to WAV file (one line, absolute path)
  stdout -> ERROR: <message>  (on failure)

Launched automatically by tts_engine.py on first speak() call.
Do not run manually unless debugging.
"""

import sys
import os
import tempfile
import traceback
from pathlib import Path

def main():
    # Force UTF-8 on stdin/stdout so Unicode from the LLM doesn't break the pipe
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    # Suppress all non-essential output so stdout stays clean for IPC
    os.environ["PYTHONWARNINGS"] = "ignore"

    import warnings
    warnings.filterwarnings("ignore")

    import torch
    import torchaudio
    from chatterbox.tts import ChatterboxTTS

    # Read voice sample path from first stdin line
    voice_sample = sys.stdin.readline().strip()
    if not voice_sample or not Path(voice_sample).exists():
        voice_sample = "F:/cohost/voice/samples/aria_voice.wav"

    # GPU auto-detect: NVIDIA CUDA → CPU
    # AMD DirectML is not yet compatible (torch-directml needs torch 2.4, Chatterbox needs 2.6)
    if torch.cuda.is_available():
        device = "cuda"
        gpu_name = torch.cuda.get_device_name(0)
    else:
        device = "cpu"
        gpu_name = "CPU"
    print(f"LOADING device={device} gpu={gpu_name}", flush=True)

    try:
        model = ChatterboxTTS.from_pretrained(device=device)
        # Warm up with a short silent generation to pre-JIT everything
        _ = model.generate("Hello.", audio_prompt_path=voice_sample)
        print("READY", flush=True)  # signal that model is loaded and warm
    except Exception as e:
        print(f"ERROR: Failed to load model on {device}: {e}", flush=True)
        sys.exit(1)

    # Main request loop
    while True:
        try:
            line = sys.stdin.readline()
            if not line:          # stdin closed — parent process exited
                break
            text = line.strip()
            if not text:
                continue
            if text == "QUIT":
                break

            # Generate audio
            wav = model.generate(text, audio_prompt_path=voice_sample)

            # Save to a named temp file (delete=False so parent can play it)
            tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            tmp_path = tmp.name
            tmp.close()

            torchaudio.save(tmp_path, wav, model.sr)

            # Tell parent where the file is
            print(tmp_path, flush=True)

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"ERROR: {e}", flush=True)


if __name__ == "__main__":
    main()
