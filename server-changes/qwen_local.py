import io
import re
import wave

import requests

from config.logger import setup_logging
from core.providers.tts.base import TTSProviderBase
from core.providers.tts.dto.dto import SentenceType
from core.utils.tts import MarkdownCleaner

TAG = __name__
logger = setup_logging()

SERVICE_RATE = 24000
BYTES_PER_SAMPLE = 2
# Generation can barely outrun playback while the LLM shares the GPU, which caused audible dropouts one to two
# seconds into a sentence. Start sending only once this much audio is ready, or the sentence has ended.
HOLD_BYTES = int(SERVICE_RATE * BYTES_PER_SAMPLE * 0.96)
EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍]")


class TTSProvider(TTSProviderBase):
    """Client for the local Qwen3-TTS service, which streams 24 kHz mono PCM."""

    def __init__(self, config, delete_audio_file):
        super().__init__(config, delete_audio_file)
        self.api_url = config.get("api_url", "http://127.0.0.1:8765/tts")
        self.connect_timeout = float(config.get("connect_timeout", 2))
        # Each call is an independent generation, so short comma-split clauses sound unstable: cut at sentence ends only.
        self.first_sentence_punctuations = self.punctuations

    async def open_audio_channels(self, conn):
        if conn.sample_rate != SERVICE_RATE:
            raise ValueError(f"QwenLocal TTS 输出 {SERVICE_RATE}Hz，但连接采样率为 {conn.sample_rate}Hz")
        await super().open_audio_channels(conn)

    def _prepare(self, text):
        text = EMOJI.sub("", MarkdownCleaner.clean_markdown(text))
        if self._correct_words_pattern:
            text = self._correct_words_pattern.sub(lambda m: self.correct_words[m.group(0)], text)
        return text

    def _post(self, text):
        resp = requests.post(self.api_url, json={"text": text}, stream=True, timeout=(self.connect_timeout, self.tts_timeout))
        if resp.status_code != 200:
            resp.close()
            raise Exception(f"QwenLocal TTS 请求失败: {resp.status_code}")
        return resp

    def to_tts_stream(self, text, opus_handler=None):
        original_text = text
        sentence_id = getattr(self, "current_sentence_id", None)
        frame_bytes = SERVICE_RATE * BYTES_PER_SAMPLE * self.opus_encoder.frame_size_ms // 1000
        buffer = bytearray()
        started = False

        def announce():
            self.tts_audio_queue.put((SentenceType.FIRST, None, original_text, sentence_id))

        try:
            with self._post(self._prepare(text)) as resp:
                for chunk in resp.iter_content(chunk_size=None):
                    if self.conn.client_abort:
                        return None
                    buffer.extend(chunk)
                    if not started:
                        if len(buffer) < HOLD_BYTES:
                            continue
                        announce()
                        started = True
                    while len(buffer) >= frame_bytes:
                        frame = bytes(buffer[:frame_bytes])
                        del buffer[:frame_bytes]
                        self.opus_encoder.encode_pcm_to_opus_stream(frame, end_of_stream=False, callback=opus_handler)
            if not started:
                if not buffer:
                    return None
                announce()
            self.opus_encoder.encode_pcm_to_opus_stream(bytes(buffer), end_of_stream=True, callback=opus_handler)
        except Exception as e:
            logger.bind(tag=TAG).error(f"语音生成失败: {original_text}，错误: {e}")
        return None

    async def text_to_speak(self, text, output_file):
        """Whole-sentence path, used for cached prompts and wake-up replies."""
        with self._post(text) as resp:
            pcm = b"".join(resp.iter_content(chunk_size=None))
        wav = io.BytesIO()
        with wave.open(wav, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(BYTES_PER_SAMPLE)
            w.setframerate(SERVICE_RATE)
            w.writeframes(pcm)
        if output_file:
            with open(output_file, "wb") as f:
                f.write(wav.getvalue())
            return None
        return wav.getvalue()
