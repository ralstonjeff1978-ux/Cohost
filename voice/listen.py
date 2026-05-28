"""
LISTEN — Microphone capture + Whisper transcription
====================================================
Runs inside the venv312 environment where faster-whisper and sounddevice live.
Called as a subprocess by voice_input.py.

Outputs the transcribed text to stdout — one line, then exits.

Usage (direct):
    F:/cohost/voice/venv312/Scripts/python.exe F:/cohost/voice/listen.py
    F:/cohost/voice/venv312/Scripts/python.exe F:/cohost/voice/listen.py --device 9
    F:/cohost/voice/venv312/Scripts/python.exe F:/cohost/voice/listen.py --model medium
"""

import argparse
import sys
import tempfile
import threading
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf

# ── Config ────────────────────────────────────────────────────────────────────

SAMPLE_RATE   = 48000     # device 15 native rate
CHANNELS      = 2         # device 15 stereo (downmix to mono in processing)
DTYPE         = "float32"
CHUNK_SECS    = 0.1       # process audio in 100ms chunks
SILENCE_SECS  = 1.8       # stop after this many seconds of silence
MAX_RECORD_SECS = 30      # hard cap on recording length
ENERGY_THRESHOLD = 0.0017 # calibrated for onn headset device 15
WARMUP_CHUNKS = 3         # ignore the first N chunks (mic init noise)


def rms(chunk: np.ndarray) -> float:
    return float(np.sqrt(np.mean(chunk ** 2)))


def record_until_silence(device: int = None, threshold: float = ENERGY_THRESHOLD) -> np.ndarray:
    """
    Record from mic until the user stops talking.
    Returns a numpy float32 array at 16kHz.
    """
    frames = []
    silence_start = None
    speech_started = False
    chunk_samples = int(SAMPLE_RATE * CHUNK_SECS)
    warmup = WARMUP_CHUNKS
    start_time = time.time()

    print("Listening...", file=sys.stderr, flush=True)

    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype=DTYPE,
        blocksize=chunk_samples,
        device=device,
    ) as stream:
        while True:
            chunk, _ = stream.read(chunk_samples)
            chunk = chunk[:, 0] if chunk.ndim > 1 else chunk

            if warmup > 0:
                warmup -= 1
                continue

            energy = rms(chunk)

            if energy > threshold:
                if not speech_started:
                    print("Speech detected...", file=sys.stderr, flush=True)
                    speech_started = True
                silence_start = None
                frames.append(chunk)
            else:
                if speech_started:
                    frames.append(chunk)  # keep trailing silence
                    if silence_start is None:
                        silence_start = time.time()
                    elif time.time() - silence_start > SILENCE_SECS:
                        print("Silence — done recording.", file=sys.stderr, flush=True)
                        break

            if time.time() - start_time > MAX_RECORD_SECS:
                print("Max recording time reached.", file=sys.stderr, flush=True)
                break

    if not frames:
        return np.array([], dtype=np.float32)

    return np.concatenate(frames)


def transcribe(audio: np.ndarray, model_size: str = "base") -> str:
    """
    Transcribe audio array using faster-whisper.
    Downloads model on first use (~75MB for 'base', ~500MB for 'medium').
    """
    from faster_whisper import WhisperModel

    if len(audio) < SAMPLE_RATE * 0.3:   # less than 0.3s — too short
        return ""

    # Resample to 16kHz if needed (48kHz → 16kHz = 3:1 decimation)
    WHISPER_SR = 16000
    if SAMPLE_RATE != WHISPER_SR:
        step = SAMPLE_RATE // WHISPER_SR
        if step > 1:
            audio = audio[::step]

    # Save to temp file (faster-whisper wants a file path)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        sf.write(tmp_path, audio, WHISPER_SR)

        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        segments, info = model.transcribe(
            tmp_path,
            language="en",
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        return text
    finally:
        try:
            Path(tmp_path).unlink()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description="Record mic and transcribe speech")
    parser.add_argument("--device", type=int, default=15,
                        help="Sounddevice input device index (default: 15 = onn headset)")
    parser.add_argument("--model", default="base",
                        choices=["tiny", "base", "small", "medium", "large-v3"],
                        help="Whisper model size (default: base)")
    parser.add_argument("--threshold", type=float, default=ENERGY_THRESHOLD,
                        help="RMS energy threshold for speech detection")
    parser.add_argument("--list-devices", action="store_true",
                        help="List available input devices and exit")
    args = parser.parse_args()

    if args.list_devices:
        devices = sd.query_devices()
        for i, d in enumerate(devices):
            if d["max_input_channels"] > 0:
                print(f"  [{i:2d}] {d['name']}")
        sys.exit(0)

    audio = record_until_silence(device=args.device, threshold=args.threshold)
    if len(audio) == 0:
        print("", flush=True)   # empty line = nothing heard
        sys.exit(0)

    text = transcribe(audio, model_size=args.model)
    print(text, flush=True)     # transcript goes to stdout for parent process


if __name__ == "__main__":
    main()
