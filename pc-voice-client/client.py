"""Voice client for this PC: a Bluetooth speaker's mic and speaker stand in for the ESP32 board.

Listens locally for the wake word, then speaks the xiaozhi WebSocket protocol to the self-hosted server.
--mic-file / --out-file replace the sound devices so the whole path can be tested without audio hardware.
"""
import argparse
import asyncio
import json
import queue
import sys
import threading
import time
import urllib.request
import wave
from pathlib import Path

import numpy as np
import opuslib_next
import sherpa_onnx
import websockets

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
HERE = Path(__file__).parent
KWS_DIR = HERE / "models" / "sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01"
KEYWORDS = HERE / "keywords.txt"
OTA_URL = "http://127.0.0.1:8003/xiaozhi/ota/"
PROACTIVE_URL = "http://127.0.0.1:8003/xiaozhi/proactive?client=speaker"
PROACTIVE_MARKER = "__proactive__"
HEADERS = {"Device-Id": "02:00:00:00:00:10", "Client-Id": "pc-voice-client", "Protocol-Version": "1", "Authorization": "Bearer pc"}
MIC_RATE = 16000
FRAME_MS = 60
FRAME_SAMPLES = MIC_RATE * FRAME_MS // 1000
IDLE_END_S = 20  # back to waiting for the wake word after this long without the user speaking
MIC_RESUME_S = 0.4  # keep the mic muted a little after playback, or the speaker's tail reaches the server
MIC_STALL_S = 5  # a fresh Bluetooth mic can take a few seconds to deliver its first block


def log(message):
    print(f"{time.strftime('%H:%M:%S')} {message}")


class Mic:
    """Pushes 60 ms blocks of 16 kHz mono PCM to a queue from the sound device or a WAV file."""

    def __init__(self, device, mic_file):
        self.blocks = queue.Queue()
        self.finished = threading.Event()
        if mic_file:
            threading.Thread(target=self._read_file, args=(mic_file,), daemon=True).start()
        else:
            self.device = device
            self._open()
            threading.Thread(target=self._watch, daemon=True).start()

    def _open(self):
        import sounddevice as sd

        def on_block(data, _n, _t, _s):
            self.last_block = time.monotonic()
            self.blocks.put(bytes(data))

        self.last_block = time.monotonic()
        self.stream = sd.RawInputStream(samplerate=MIC_RATE, channels=1, dtype="int16", blocksize=FRAME_SAMPLES, device=self.device,
                                        callback=on_block)
        self.stream.start()

    def _watch(self):
        """A dropped Bluetooth link stops the callbacks without any error, so reopen when they stop."""
        while True:
            time.sleep(1)
            if time.monotonic() - self.last_block < MIC_STALL_S:
                continue
            log("麦克风没有数据，重新打开")
            threading.Thread(target=self.stream.close, daemon=True).start()  # closing a dead stream can hang
            try:
                self._open()
            except Exception as err:  # the speaker may be off; keep trying until it returns
                self.last_block = time.monotonic()
                log(f"麦克风打开失败: {err}")

    def _read_file(self, path):
        with wave.open(path) as w:
            assert w.getframerate() == MIC_RATE and w.getnchannels() == 1, "mic file must be 16 kHz mono"
            start = time.perf_counter()
            for i, data in enumerate(iter(lambda: w.readframes(FRAME_SAMPLES), b"")):
                if len(data) < FRAME_SAMPLES * 2:
                    break
                self.blocks.put(data)
                time.sleep(max(0, start + (i + 1) * FRAME_MS / 1000 - time.perf_counter()))
        self.finished.set()


class Player:
    """Plays decoded PCM on its own thread and reports when it has gone quiet, so the mic can reopen."""

    def __init__(self, device, out_file):
        self.device, self.out_file = device, out_file
        self.items = queue.Queue()
        self.last_audio = 0.0
        self.captured = bytearray()
        self.rate = None
        threading.Thread(target=self._run, daemon=True).start()

    def play(self, pcm, rate):
        self.last_audio = time.monotonic()
        self.items.put((pcm, rate))

    def beep(self):
        t = np.arange(int(0.12 * 24000)) / 24000
        tone = 0.2 * np.sin(2 * np.pi * 880 * t) * np.hanning(len(t))
        self.play((tone * 32767).astype("<i2").tobytes(), 24000)

    def quiet(self):
        return self.items.empty() and time.monotonic() - self.last_audio > MIC_RESUME_S

    def _run(self):
        stream = None
        while True:
            pcm, rate = self.items.get()
            if self.out_file:
                self.captured += pcm
                time.sleep(len(pcm) / 2 / rate)  # real-time pacing, so muting behaves as it does on a speaker
            else:
                if rate != self.rate:
                    import sounddevice as sd

                    if stream:
                        stream.close()
                    stream = sd.RawOutputStream(samplerate=rate, channels=1, dtype="int16", device=self.device)
                    stream.start()
                    self.rate = rate
                stream.write(pcm)
            self.last_audio = time.monotonic()

    def save(self):
        if self.out_file:
            with wave.open(self.out_file, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(24000)
                w.writeframes(bytes(self.captured))


class WakeWord:
    def __init__(self):
        stem = "epoch-12-avg-2-chunk-16-left-64.int8.onnx"
        self.spotter = sherpa_onnx.KeywordSpotter(
            tokens=str(KWS_DIR / "tokens.txt"), encoder=str(KWS_DIR / f"encoder-{stem}"), decoder=str(KWS_DIR / f"decoder-{stem}"),
            joiner=str(KWS_DIR / f"joiner-{stem}"), keywords_file=str(KEYWORDS), num_threads=2, provider="cpu",
            keywords_threshold=0.25, keywords_score=1.5)
        self.stream = self.spotter.create_stream()

    def hit(self, pcm):
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
        self.stream.accept_waveform(MIC_RATE, samples)
        while self.spotter.is_ready(self.stream):
            self.spotter.decode_stream(self.stream)
        word = self.spotter.get_result(self.stream)
        if word:
            self.spotter.reset_stream(self.stream)
        return word

    def reset(self):
        self.stream = self.spotter.create_stream()


def websocket_url():
    body = json.dumps({"application": {"version": "2.5.3"}, "board": {"type": "pc-voice-client"}}).encode()
    request = urllib.request.Request(OTA_URL, body, {**HEADERS, "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)["websocket"]["url"]


async def next_block(mic):
    """Next mic block; None once a test file has run out."""
    while True:
        try:
            return mic.blocks.get_nowait()
        except queue.Empty:
            if mic.finished.is_set():
                return None
            await asyncio.sleep(0.01)


def proactive_due():
    """Asks the server whether to start talking; a stopped server just means no."""
    try:
        with urllib.request.urlopen(PROACTIVE_URL, timeout=3) as response:
            return json.load(response).get("speak", False)
    except (OSError, ValueError):
        return False


async def converse(mic, player, proactive=False):
    async with websockets.connect(websocket_url(), additional_headers=HEADERS, max_size=None) as ws:
        await ws.send(json.dumps({"type": "hello", "version": 1, "transport": "websocket", "features": {"mcp": False},
                                  "audio_params": {"format": "opus", "sample_rate": MIC_RATE, "channels": 1, "frame_duration": FRAME_MS}}))
        hello = json.loads(await asyncio.wait_for(ws.recv(), 10))
        rate = hello["audio_params"]["sample_rate"]
        if proactive:
            await ws.send(json.dumps({"type": "listen", "session_id": hello.get("session_id"), "state": "detect", "text": PROACTIVE_MARKER}))
        await ws.send(json.dumps({"type": "listen", "session_id": hello.get("session_id"), "state": "start", "mode": "auto"}))
        encoder = opuslib_next.Encoder(MIC_RATE, 1, opuslib_next.APPLICATION_VOIP)
        decoder = opuslib_next.Decoder(rate, 1)
        state = {"speaking": False, "last_turn": time.monotonic()}

        async def receive():
            async for message in ws:
                if isinstance(message, bytes):
                    player.play(decoder.decode(message, rate * FRAME_MS // 1000), rate)
                    continue
                data = json.loads(message)
                if data.get("type") == "stt":
                    if not str(data.get("text", "")).startswith("（系统提示"):
                        log(f"你: {data.get('text')}")
                    state["last_turn"] = time.monotonic()
                elif data.get("type") == "tts":
                    if data.get("state") == "start":
                        state["speaking"] = True
                    elif data.get("state") == "stop":
                        state["speaking"] = False
                        state["last_turn"] = time.monotonic()
                    elif data.get("state") == "sentence_start":
                        log(f"她: {data.get('text')}")

        async def send():
            while True:
                block = await next_block(mic)
                if block is None:
                    while state["speaking"] or not player.quiet():
                        await asyncio.sleep(0.1)
                    return
                busy = state["speaking"] or not player.quiet()
                if busy:
                    state["last_turn"] = time.monotonic()
                    continue  # no echo cancellation: drop the mic while the speaker talks
                if time.monotonic() - state["last_turn"] > IDLE_END_S:
                    return
                await ws.send(encoder.encode(block, FRAME_SAMPLES))

        tasks = [asyncio.create_task(receive()), asyncio.create_task(send())]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in done:
            task.result()


async def main(args):
    wake = WakeWord()
    mic = Mic(args.input, args.mic_file)
    player = Player(args.output, args.out_file)
    log("等待唤醒词：你好翠花")
    loop = asyncio.get_running_loop()
    check = None
    next_check = time.monotonic() + args.proactive_every
    while True:
        block = await next_block(mic)
        if block is None:
            break
        word = wake.hit(block)
        proactive = False
        if check is None and time.monotonic() >= next_check:
            check = loop.run_in_executor(None, proactive_due)
        if check is not None and check.done():
            proactive = check.result()
            check = None
            next_check = time.monotonic() + args.proactive_every
        if not word and not proactive:
            continue
        log(f"已唤醒: {word}" if word else "她主动开口")
        if word:
            player.beep()
        try:
            await converse(mic, player, proactive=not word)
        except (OSError, TimeoutError, asyncio.TimeoutError, websockets.exceptions.WebSocketException) as err:
            log(f"连接中断: {type(err).__name__}: {err}")
        wake.reset()
        log("等待唤醒词：你好翠花")
    player.save()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="list sound devices and exit")
    parser.add_argument("--input", default="ヘッドセット SoundCore MME", help="microphone: words from the name and host API in --list")
    parser.add_argument("--output", default="ヘッドホン SoundCore MME", help="speaker: words from the name and host API in --list")
    parser.add_argument("--proactive-every", type=float, default=60, help="seconds between asking the server whether to start talking")
    parser.add_argument("--mic-file", help="test: 16 kHz mono WAV used instead of the microphone")
    parser.add_argument("--out-file", help="test: write the reply to this WAV instead of the speaker")
    arguments = parser.parse_args()
    if arguments.list:
        import sounddevice

        print(sounddevice.query_devices())
    else:
        try:
            asyncio.run(main(arguments))
        except KeyboardInterrupt:
            pass
