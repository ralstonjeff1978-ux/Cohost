VOICE SAMPLES — for Coqui XTTS free voice cloning
===================================================
To clone a voice (free, offline, same method as the Jason Asano voice):

1. Find a 10-30 second clean audio clip of the female American voice you want.
   - No background music
   - No crowd noise
   - Just clear speech
   Good sources: audiobook samples, YouTube clips, podcast intros

2. Save it here as:  cohost_voice.wav  (WAV preferred, MP3 also works)

3. In config.yaml, set:
     voice:
       backend: coqui-xtts
       xtts_voice_sample: F:/cohost/voice/samples/cohost_voice.wav

4. Install Coqui if you haven't:  pip install TTS
   (downloads ~2GB of model weights on first run — offline after that)

5. Test it:
     python voice/tts_engine.py --preview

The model will clone the voice characteristics and speak in that style.
This is exactly how the Jason Asano (He Who Fights With Monsters) voice was built.
