import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import sounddevice as sd
from voice.voice_input import _device_params, DEFAULT_DEVICE

print("Input devices (main Python env):")
for i, d in enumerate(sd.query_devices()):
    if d["max_input_channels"] > 0:
        name = d["name"][:45]
        ch = d["max_input_channels"]
        sr = int(d["default_samplerate"])
        print(f"  [{i:2d}] {name:<45} ch={ch} sr={sr}")

print()
ch, sr = _device_params(DEFAULT_DEVICE)
print(f"Default device {DEFAULT_DEVICE}: channels={ch} samplerate={sr}")
