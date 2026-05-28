"""Find the right mic device. SPEAK during each window."""
import sounddevice as sd
import numpy as np
import time

candidates = [
    (1,  1, 44100),
    (7,  1, 44100),
    (15, 2, 48000),
    (23, 1, 48000),
]

best_device = None
best_peak = 0

for dev_id, ch, sr in candidates:
    samples = []
    def cb(indata, frames, t, status):
        mono = indata[:, 0] if indata.ndim > 1 else indata.flatten()
        samples.append(float(np.sqrt(np.mean(mono**2))))
    print(f"Device {dev_id} — SPEAK NOW (2s):")
    try:
        with sd.InputStream(samplerate=sr, channels=ch, dtype="float32",
                            blocksize=int(sr*0.1), device=dev_id, callback=cb):
            time.sleep(2)
        peak = max(samples) if samples else 0
        noise = sum(sorted(samples)[:len(samples)//3]) / max(len(samples)//3, 1)
        print(f"  peak={peak:.6f}  noise={noise:.6f}  {'<<< SPEECH DETECTED' if peak > 0.002 else ('low signal' if peak > 0.0003 else 'NO SIGNAL')}")
        if peak > best_peak:
            best_peak = peak
            best_device = (dev_id, ch, sr, noise)
    except Exception as e:
        print(f"  error: {e}")

print()
if best_device:
    dev_id, ch, sr, noise = best_device
    threshold = max(noise * 4, 0.0003)
    print(f"BEST DEVICE: {dev_id} | channels={ch} | samplerate={sr}")
    print(f"RECOMMENDED THRESHOLD: {threshold:.6f}")
    print(f"\nTo use this mic:")
    print(f"  python cohost.py --voice --mic {dev_id}")
else:
    print("No working mic found — check Windows mic settings.")
