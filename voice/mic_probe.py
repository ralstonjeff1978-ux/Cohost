"""Probe mic devices and find speech levels. Run with venv312 python. SPEAK while it runs."""
import sounddevice as sd
import numpy as np
import time
import sys

# --- Part 1: device info ---
print("=== DEVICE INFO ===")
for dev_id in [9, 10, 25, 29, 31]:
    try:
        info = sd.query_devices(dev_id)
        ch = info["max_input_channels"]
        sr = int(info["default_samplerate"])
        print(f"  [{dev_id}] {info['name'][:40]} | channels={ch} sr={sr}")
    except Exception as e:
        print(f"  [{dev_id}] error: {e}")

# --- Part 2: live level test on each working device ---
print("\n=== LIVE LEVELS (SPEAK NOW) ===")
for dev_id in [9, 10, 25]:
    try:
        info = sd.query_devices(dev_id)
        ch = min(info["max_input_channels"], 1)
        if ch == 0:
            continue
        sr = int(info["default_samplerate"])
        samples = []

        def cb(indata, frames, t, status):
            mono = indata[:, 0] if indata.ndim > 1 else indata.flatten()
            samples.append(float(np.sqrt(np.mean(mono**2))))

        print(f"\n  Device {dev_id} — SPEAK for 4 seconds:")
        with sd.InputStream(samplerate=sr, channels=ch, dtype="float32",
                            blocksize=int(sr*0.1), device=dev_id, callback=cb):
            time.sleep(4)

        if samples:
            peak = max(samples)
            noise = sorted(samples)[:len(samples)//3]
            noise_floor = sum(noise)/len(noise) if noise else 0
            suggested = max(noise_floor * 4, 0.0003)
            print(f"  Peak: {peak:.6f} | Noise floor: {noise_floor:.6f} | Suggested threshold: {suggested:.6f}")
            print(f"  Status: {'WORKING - picking up audio' if peak > 0.001 else 'LOW - mic may be muted or too quiet'}")
    except Exception as e:
        print(f"  Device {dev_id} failed: {e}")
