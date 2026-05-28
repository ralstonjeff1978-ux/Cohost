"""
VOICE DESIGNS — Pre-built ElevenLabs Voice Design descriptions
==============================================================
Run any of these to generate a brand-new synthetic voice with those
characteristics. No real person is cloned. Each generation creates a
unique voice — run it multiple times to get variations.

Usage:
    python voice/voice_designs.py --generate demo
    python voice/voice_designs.py --generate custom "your description here"
    python voice/voice_designs.py --list
"""

import os
import sys
from pathlib import Path

# Add parent to path so we can import tts_engine
sys.path.insert(0, str(Path(__file__).parent.parent))

from voice.tts_engine import design_voice

# ── Pre-built voice profiles ──────────────────────────────────────────────────

VOICE_DESIGNS = {

    "demo": {
        "name": "aria_demo",
        "preview": "Hey, welcome to the show. I am so excited you're here — "
                   "I've been looking forward to this conversation all week.",
        "description": (
            "Young American female voice, early to mid twenties. "
            "Warm and earnest — sounds like she genuinely means everything she says. "
            "Clear, articulate speech with natural rhythm, never rushed but energetic. "
            "Soft but confident, with a slight musical lilt. "
            "Emotionally expressive — you can hear her smile when she's excited "
            "and her sincerity when she's serious. "
            "Intelligent and relatable. "
            "Perfect for interviewing guests — sounds like she's truly listening "
            "and engaged with every answer."
        ),
    },

    "quirky": {
        "name": "aria_quirky",
        "preview": "Okay so this is going to sound weird but I have been obsessed "
                   "with this topic for like three weeks and I cannot wait to dig in.",
        "description": (
            "Young American female, mid twenties, fast-talking and energetic. "
            "Quirky, a little nerdy, enthusiastic about everything. "
            "Warm and funny, sounds like the smartest person in the room "
            "who is also the most fun at a party. "
            "Slightly husky voice, very conversational, "
            "like she's always about to share a secret with you."
        ),
    },

    "warm": {
        "name": "aria_warm",
        "preview": "I just want to say, I really appreciate you being here today. "
                   "The work you're doing — it matters, and I think people need to hear this.",
        "description": (
            "American female, late twenties, deep warm voice. "
            "Sounds like a trusted friend who also happens to be brilliant. "
            "Calm, confident, unhurried. "
            "Slight huskiness in the lower register. "
            "The kind of voice that makes guests feel safe opening up. "
            "Podcast host energy — professional but personal."
        ),
    },

}


def list_designs():
    print("\nAvailable voice designs:")
    for key, v in VOICE_DESIGNS.items():
        print(f"\n  [{key}]  → saves as: {v['name']}")
        # Print first two sentences of description
        desc_preview = ". ".join(v["description"].split(". ")[:2]) + "..."
        print(f"  {desc_preview}")


def generate(key: str = "demo", custom_desc: str = ""):
    if custom_desc:
        design_voice(
            description=custom_desc,
            voice_name="aria_custom",
            preview_text="Hey, welcome to the show. I am so excited you're here today.",
        )
        return

    if key not in VOICE_DESIGNS:
        print(f"Unknown design '{key}'. Run --list to see options.")
        return

    v = VOICE_DESIGNS[key]
    print(f"\nGenerating voice design: {key}")
    design_voice(
        description=v["description"],
        voice_name=v["name"],
        preview_text=v["preview"],
    )


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate ElevenLabs voice designs")
    parser.add_argument("--generate", metavar="DESIGN", default="demo",
                        help="Design key to generate (default: demo)")
    parser.add_argument("--custom", metavar="DESC", default="",
                        help="Custom voice description (overrides --generate)")
    parser.add_argument("--list", action="store_true", help="List available designs")
    args = parser.parse_args()

    if args.list:
        list_designs()
    else:
        generate(args.generate, args.custom)
