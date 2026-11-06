"""Emulates the headset board in realtime mode: speaks over the reply and times how fast the server stops talking."""
import asyncio
import io
import json
import sys
import time

import edge_tts
import opuslib_next
import websockets
from pydub import AudioSegment

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
HEADERS = {"Device-Id": "02:00:00:00:00:11", "Client-Id": "barge-test", "Protocol-Version": "1", "Authorization": "Bearer x"}
FRAME = 960


async def frames(text):
    buf = b""
    async for c in edge_tts.Communicate(text, "zh-CN-YunxiNeural").stream():
        if c["type"] == "audio":
            buf += c["data"]
    pcm = AudioSegment.from_file(io.BytesIO(buf)).set_frame_rate(16000).set_channels(1).set_sample_width(2).raw_data + b"\0" * 64000
    enc = opuslib_next.Encoder(16000, 1, opuslib_next.APPLICATION_VOIP)
    return [enc.encode(pcm[i:i + FRAME * 2], FRAME) for i in range(0, len(pcm) - FRAME * 2, FRAME * 2)]


async def main():
    question = await frames("给我讲一个很长很长的故事吧。")
    interrupt = await frames("等一下，先不要讲了，现在几点了？")
    silence = opuslib_next.Encoder(16000, 1, opuslib_next.APPLICATION_VOIP).encode(b"\0" * (FRAME * 2), FRAME)
    async with websockets.connect("ws://127.0.0.1:8000/xiaozhi/v1/", additional_headers=HEADERS) as ws:
        await ws.send(json.dumps({"type": "hello", "version": 1, "transport": "websocket",
                                  "audio_params": {"format": "opus", "sample_rate": 16000, "channels": 1, "frame_duration": 60}}))
        hello = json.loads(await asyncio.wait_for(ws.recv(), 10))
        await ws.send(json.dumps({"type": "listen", "session_id": hello.get("session_id"), "state": "start", "mode": "realtime"}))
        state = {"sentences": 0, "t_int": None, "stops": []}

        async def receive():
            async for m in ws:
                if isinstance(m, bytes):
                    continue
                j = json.loads(m)
                if j.get("type") == "stt":
                    print(f"STT: {j.get('text')}")
                elif j.get("type") == "tts":
                    if j.get("state") == "sentence_start":
                        state["sentences"] += 1
                        print(f"TTS: {j.get('text', '')[:30]}")
                    elif j.get("state") == "stop":
                        now = time.perf_counter()
                        state["stops"].append(now)
                        if state["t_int"]:
                            print(f"tts stop {now - state['t_int']:.2f}s after the interruption began")

        async def send():
            for f in question:
                await ws.send(f)
                await asyncio.sleep(0.06)
            while state["sentences"] == 0:  # silence stream, like a real mic, until she speaks
                await ws.send(silence)
                await asyncio.sleep(0.06)
            for _ in range(40):  # 2.4 s of quiet while she talks: must NOT interrupt her
                await ws.send(silence)
                await asyncio.sleep(0.06)
            print(f"quiet while speaking: stops so far={len(state['stops'])} (expected 0)")
            state["t_int"] = time.perf_counter()
            print("--- speaking over her ---")
            for f in interrupt:
                await ws.send(f)
                await asyncio.sleep(0.06)
            for _ in range(250):
                await ws.send(silence)
                await asyncio.sleep(0.06)

        r = asyncio.create_task(receive())
        try:
            await asyncio.wait_for(send(), 70)
        except asyncio.TimeoutError:
            print("send timed out")
        r.cancel()


asyncio.run(main())
