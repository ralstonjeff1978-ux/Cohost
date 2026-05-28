"""Quick mic test — run with venv312 python, speak during each device test."""
import sounddevice as sd
import numpy as np
import time

TEST_DEVICES = [
    (9,  "DualSense headset mic"),
    (10, "onn gaming headset mic"),
    (25, "Realtek HD Audio mic"),
    (None, "System default"),
]

for dev_id, dev_name in TEST_DEVICES:
    label = f"device {dev_id}" if dev_id is not None else "default"
    print(f"--- {dev_name} ({label}) --- SPEAK NOW for 3 seconds ---")
    samples = []

    def cb(indata, frames, t, status):
        samples.append(float(np.sqrt(np.mean(indata ** 2))))

    try:
        with sd.InputStream(
            samplerate=16000, channels=1, dtype="float32",
            blocksize=3200, device=dev_id, callback=cb
        ):
            time.sleep(3)

        if samples:
            peak = max(samples)
            avg  = sum(samples) / len(samples)
            working = peak > 0.001
            print(f"  Peak RMS : {peak:.5f}")
            print(f"  Avg  RMS : {avg:.5f}")
            print(f"  Status   : {'WORKING' if working else 'NO SIGNAL'}")
            if working:
                suggested = max(0.0005, avg * 2)
                print(f"  Suggested threshold: {suggested:.4f}")
        else:
            print("  No data captured.")
    except Exception as e:
        print(f"  Error: {e}")
    print()
