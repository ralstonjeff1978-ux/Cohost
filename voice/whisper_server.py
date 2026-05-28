"""
WHISPER SERVER — Persistent STT process
========================================
Runs in venv312. Loads Whisper once, serves transcription requests via stdin/stdout.

Protocol:
  stdin  <- audio file path (one line)
  stdout -> transcript text (one line)
  stdout -> ERROR: <msg>  on failure
"""
import sys
import os
import warnings
warnings.filterwarnings("ignore")
os.environ["PYTHONWARNINGS"] = "ignore"

def main():
    from faster_whisper import WhisperModel
    import soundfile as sf
    import numpy as np

    model_size = sys.stdin.readline().strip() or "tiny"
    print("LOADING", flush=True)

    try:
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        print("READY", flush=True)
    except Exception as e:
        print(f"ERROR: {e}", flush=True)
        sys.exit(1)

    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
            path = line.strip()
            if path == "QUIT":
                break
            if not path or not os.path.exists(path):
                print("ERROR: file not found", flush=True)
                continue

            segments, _ = model.transcribe(
                path,
                language="en",
                beam_size=3,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 400},
            )
            text = " ".join(s.text.strip() for s in segments).strip()
            print(text or " ", flush=True)

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"ERROR: {e}", flush=True)

if __name__ == "__main__":
    main()
