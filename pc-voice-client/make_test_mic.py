"""Builds a fake microphone recording: noise-free speech for the wake word and two questions, with pauses."""
import io
import json
import sys
import urllib.request
import wave

import numpy as np
from pydub import AudioSegment

SR = 16000


def speak(text):
    req = urllib.request.Request("http://127.0.0.1:8765/tts", json.dumps({"text": text}).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        seg = AudioSegment(r.read(), sample_width=2, frame_rate=24000, channels=1)
    return seg.set_frame_rate(SR).raw_data


def silence(seconds):
    return b"\0" * (int(SR * seconds) * 2)


parts = [silence(2), speak("今天的会议真的好长。"), silence(3)]  # must not wake: not the keyword
parts += [speak("你好翠花"), silence(2), speak("为什么天空是蓝色的？"), silence(16)]
parts += [speak("你最喜欢吃什么？"), silence(12)]
with wave.open(sys.argv[1], "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(b"".join(parts))
print("seconds", sum(len(p) for p in parts) / SR / 2)
