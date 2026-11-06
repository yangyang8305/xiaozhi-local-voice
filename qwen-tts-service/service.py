"""Local streaming TTS service: POST /tts {"text": ...} returns raw 24 kHz mono s16le PCM as it is generated."""
import json
import logging
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
from faster_qwen3_tts import FasterQwen3TTS

MODEL_DIR = Path(r"C:\AI\ESP32\tts-eval\qwen3\0.6B-Base")
REFERENCE = Path(__file__).parent / "voice" / "reference-serena.wav"  # fixes the speaker for every sentence
HOST, PORT = "127.0.0.1", 8765
LANGUAGE = "chinese"
CHUNK_SIZE = 6  # codec frames per chunk; about 0.45s to first audio in testing


def spoken_chars(text):
    return len(re.sub(r"[，。？！、\s]", "", text))


def frame_limit(text):
    """Stops runaway generation (a 5-character clause once produced 12s): 12 frames/s, rarely under 2 chars/s."""
    return 24 + 6 * spoken_chars(text)


def frame_minimum(text):
    """Stops early end-of-speech, which produced empty or cut-off sentences: rarely over 6 chars/s."""
    return max(2, 2 * spoken_chars(text))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("tts")


class Engine:
    """One generation at a time; a newer request cancels the one in progress."""

    def __init__(self):
        self.model = FasterQwen3TTS.from_pretrained(str(MODEL_DIR), local_files_only=True)
        self.model.warmup()
        for _ in self._generate("你好呀，我准备好了。"):  # extracts the voiceprint now, not on the first reply
            pass
        self.lock = threading.Lock()
        self.latest = 0
        self.latest_guard = threading.Lock()

    def _generate(self, text):
        return self.model.generate_voice_clone_streaming(
            text=text,
            language=LANGUAGE,
            ref_audio=str(REFERENCE),
            xvec_only=True,  # voiceprint only, reported steadier across sentences than reference-audio context
            non_streaming_mode=True,  # avoids the reported pace drift of step-by-step text feeding
            chunk_size=CHUNK_SIZE,
            max_new_tokens=frame_limit(text),
            min_new_tokens=frame_minimum(text),
        )

    def stream(self, text):
        with self.latest_guard:
            self.latest += 1
            request_id = self.latest
        with self.lock:
            for audio, _sr, _timing in self._generate(text):
                if request_id != self.latest:
                    return
                pcm = np.clip(np.asarray(audio).flatten(), -1.0, 1.0)
                yield (pcm * 32767).astype("<i2").tobytes()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    engine = None

    def do_POST(self):
        if self.path != "/tts":
            self.send_error(404)
            return
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            text = str(body["text"]).strip()
        except (ValueError, KeyError, TypeError):
            self.send_error(400, "expected JSON with text")
            return
        if not text:
            self.send_error(400, "empty text")
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        started = time.perf_counter()
        first, size = None, 0
        try:
            for pcm in self.engine.stream(text):
                if first is None:
                    first = time.perf_counter() - started
                size += len(pcm)
                self.wfile.write(b"%x\r\n%s\r\n" % (len(pcm), pcm))
                self.wfile.flush()
            self.wfile.write(b"0\r\n\r\n")
            log.info("first=%.2fs total=%.2fs audio=%.2fs", first or 0, time.perf_counter() - started, size / 48000)
        except (BrokenPipeError, ConnectionError):
            self.close_connection = True  # client interrupted playback

    def log_message(self, *_):
        pass  # request lines would add noise; text is never logged


if __name__ == "__main__":
    Handler.engine = Engine()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    log.info("ready on %s:%d", HOST, PORT)
    server.serve_forever()
