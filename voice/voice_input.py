"""
VOICE INPUT — Persistent mic + Whisper pipeline
================================================
Loads Whisper once at startup. Each listen() call records mic → saves WAV → transcribes.
No cold-start penalty after the first call.
"""
import logging
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd
import soundfile as sf

log = logging.getLogger("voice_input")

_VENV_PYTHON     = str(Path(__file__).parent / "venv312" / "Scripts" / "python.exe")
_WHISPER_SERVER  = str(Path(__file__).parent / "whisper_server.py")

# Auto-detect default input device from the OS
def _default_input_device() -> int:
    try:
        return int(sd.default.device[0])
    except Exception:
        return 0

DEFAULT_DEVICE    = _default_input_device()
DEFAULT_MODEL     = "tiny"
DEFAULT_THRESHOLD = 0.0017


def _device_params(device: int) -> tuple[int, int]:
    """Return (channels, samplerate) for a device, capped at what actually works."""
    try:
        info = sd.query_devices(device)
        ch = min(int(info["max_input_channels"]), 2)
        sr = int(info["default_samplerate"])
        return ch, sr
    except Exception:
        return 1, 44100

SILENCE_SECS     = 1.5
MAX_RECORD_SECS  = 25
WARMUP_CHUNKS    = 3

_whisper_proc: Optional[subprocess.Popen] = None


def _get_whisper_server(model: str = DEFAULT_MODEL) -> subprocess.Popen:
    global _whisper_proc
    if _whisper_proc and _whisper_proc.poll() is None:
        return _whisper_proc

    log.info("Starting Whisper server (model=%s)...", model)
    print(f"[Aria] Loading speech recognition ({model} model)...", flush=True)

    _whisper_proc = subprocess.Popen(
        [_VENV_PYTHON, _WHISPER_SERVER],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True, bufsize=1,
    )
    _whisper_proc.stdin.write(model + "\n")
    _whisper_proc.stdin.flush()

    deadline = time.time() + 60
    while time.time() < deadline:
        line = _whisper_proc.stdout.readline().strip()
        if line == "READY":
            print("[Aria] Speech recognition ready.", flush=True)
            return _whisper_proc
        if line.startswith("ERROR"):
            raise RuntimeError(f"Whisper server failed: {line}")
    raise TimeoutError("Whisper server did not start in 60s")


_silero_model = None
_silero_utils = None

def _get_silero():
    """Load Silero VAD model once and cache it."""
    global _silero_model, _silero_utils
    if _silero_model is None:
        from silero_vad import load_silero_vad, get_speech_timestamps
        import torch
        _silero_model = load_silero_vad()
        _silero_utils = get_speech_timestamps
    return _silero_model, _silero_utils


_on_mic_event = None

def set_mic_callback(fn):
    """Set a callback fn(event: str) for mic state changes: 'listening', 'heard', 'silence'."""
    global _on_mic_event
    _on_mic_event = fn

def _mic_event(event: str):
    if _on_mic_event:
        try:
            _on_mic_event(event)
        except Exception:
            pass

def _record_until_silence(device: int, threshold: float,
                           sr: int, channels: int) -> Optional[np.ndarray]:
    """
    Record from mic using Silero VAD for end-of-speech detection.
    Much more accurate than energy threshold — won't cut off mid-sentence.
    """
    import torch

    block_sr = 16000
    block_size = 512        # Silero requires EXACTLY 512 samples at 16kHz
    block_ms = int(block_size / block_sr * 1000)   # = 32ms

    frames_16k = []
    raw_frames = []         # keep native SR for recording quality
    silence_chunks = 0
    speech_started = False
    warmup = WARMUP_CHUNKS
    t_start = time.time()

    # Load Silero once
    model, _ = _get_silero()

    print("\n[Listening...]", flush=True)
    _mic_event("listening")

    # Record at native SR, downsample chunks for VAD
    with sd.InputStream(samplerate=sr, channels=channels, dtype="float32",
                        blocksize=int(sr * block_ms / 1000), device=device) as stream:
        while True:
            chunk, _ = stream.read(int(sr * block_ms / 1000))
            mono = chunk[:, 0] if chunk.ndim > 1 else chunk.flatten()

            if warmup > 0:
                warmup -= 1
                continue

            raw_frames.append(mono)

            # Downsample to exactly 512 samples at 16kHz for Silero
            step = sr // block_sr
            mono_16k = mono[::step] if step > 1 else mono
            mono_16k = mono_16k[:block_size]
            if len(mono_16k) < block_size:
                mono_16k = np.pad(mono_16k, (0, block_size - len(mono_16k)))

            t = torch.FloatTensor(mono_16k)
            speech_prob = float(model(t, block_sr).item())

            is_speech = speech_prob > 0.5

            if is_speech:
                if not speech_started:
                    print("[Got you]", flush=True)
                    _mic_event("heard")
                    speech_started = True
                silence_chunks = 0
            else:
                if speech_started:
                    silence_chunks += 1
                    # ~800ms of silence = end of turn (more natural than 1.5s energy)
                    if silence_chunks > int(800 / block_ms):
                        break

            if time.time() - t_start > MAX_RECORD_SECS:
                break

    if not raw_frames or not speech_started:
        return None
    return np.concatenate(raw_frames)


def listen(device: int = DEFAULT_DEVICE, model: str = DEFAULT_MODEL,
           threshold: float = DEFAULT_THRESHOLD) -> str:
    """Record mic, transcribe with Whisper, return text. Blocking."""
    channels, sr = _device_params(device)

    t_vad_start = time.time()
    audio = _record_until_silence(device, threshold, sr, channels)
    t_vad = time.time() - t_vad_start

    if audio is None or len(audio) < sr * 0.3:
        log.info("[TIMING] no_audio vad=%.2fs", t_vad)
        return ""

    # Resample to 16kHz for Whisper (48kHz → 16kHz = exactly 3:1 decimation)
    WHISPER_SR = 16000
    if sr != WHISPER_SR:
        step = sr // WHISPER_SR
        if step > 1:
            audio = audio[::step]   # simple decimation — good enough for speech
        sr = WHISPER_SR

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        sf.write(tmp_path, audio, sr)
        proc = _get_whisper_server(model)

        t_stt_start = time.time()
        proc.stdin.write(tmp_path + "\n")
        proc.stdin.flush()

        # Generous timeout — we WANT to see real Whisper time, not a silent timeout
        deadline = t_stt_start + 30
        while time.time() < deadline:
            line = proc.stdout.readline().strip()
            if line and not line.startswith("ERROR"):
                t_stt = time.time() - t_stt_start
                log.info("[TIMING] vad=%.2fs stt=%.2fs text=%r",
                         t_vad, t_stt, line[:80])
                return line
            if line.startswith("ERROR"):
                log.warning("Whisper error: %s", line)
                return ""
        log.warning("[TIMING] WHISPER TIMEOUT after %.1fs (vad=%.2fs) — returning empty",
                    time.time() - t_stt_start, t_vad)
        return ""
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


def shutdown_whisper_server():
    global _whisper_proc
    if _whisper_proc and _whisper_proc.poll() is None:
        try:
            _whisper_proc.stdin.write("QUIT\n")
            _whisper_proc.stdin.flush()
            _whisper_proc.wait(timeout=5)
        except Exception:
            _whisper_proc.kill()
    _whisper_proc = None


class VoiceInput:
    def __init__(self, device=DEFAULT_DEVICE, model=DEFAULT_MODEL,
                 threshold=DEFAULT_THRESHOLD):
        self.device = device
        self.model = model
        self.threshold = threshold
        # Pre-warm Whisper server now so first listen() is instant
        _get_whisper_server(model)

    def listen(self, timeout: int = 30) -> str:
        return listen(device=self.device, model=self.model, threshold=self.threshold)

    def set_device(self, d: int): self.device = d
    def set_model(self, m: str): self.model = m


def list_devices() -> list:
    result = subprocess.run(
        [_VENV_PYTHON, "-c",
         "import sounddevice as sd\n"
         "devs=sd.query_devices()\n"
         "[print(f'  [{i}] {d[\"name\"]} ch={d[\"max_input_channels\"]}') "
         "for i,d in enumerate(devs) if d['max_input_channels']>0]"],
        capture_output=True, text=True, timeout=10
    )
    return [l.strip() for l in result.stdout.splitlines() if l.strip()]
