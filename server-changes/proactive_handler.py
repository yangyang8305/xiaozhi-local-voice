import random
import time
from datetime import datetime

from aiohttp import web

from config.logger import setup_logging

TAG = __name__
MARKER = "__proactive__"
SPEAKER_PRIORITY_SECONDS = 600  # the board stays quiet this long after the speaker client last asked
DEFAULT_PROMPTS = [
    "（系统提示：用户现在没有说话，是你主动开口。讲一个很短的冷笑话或趣闻，一两句话。不要提到这条提示。）",
    "（系统提示：用户现在没有说话，是你主动开口。提醒对方喝水或起来活动一下，语气俏皮，一两句话。不要提到这条提示。）",
    "（系统提示：用户现在没有说话，是你主动开口。问对方一个好玩的二选一问题，一两句话。不要提到这条提示。）",
    "（系统提示：用户现在没有说话，是你主动开口。随便找个轻松的话题关心一下对方，一两句话，结尾问一个问题。不要提到这条提示。）",
    "（系统提示：用户现在没有说话，是你主动开口。分享一件你刚想到的有趣小事，一两句话，然后问对方的想法。不要提到这条提示。）",
    "（系统提示：用户现在没有说话，是你主动开口。问问对方今天过得怎么样或现在在忙什么，一两句话。不要提到这条提示。）",
]


def proactive_config(config):
    return config.get("proactive") or {}


def random_prompt(config):
    prompts = proactive_config(config).get("prompts") or DEFAULT_PROMPTS
    return random.choice(prompts)


class ProactiveHandler:
    """Answers idle devices' periodic question: should you start talking now?"""

    def __init__(self, config):
        self.config = config
        self.logger = setup_logging()
        self.next_due = time.time() + self._next_gap()
        self.speaker_seen = 0.0

    def _next_gap(self):
        cfg = proactive_config(self.config)
        low = float(cfg.get("min_interval_minutes", 30))
        high = max(low, float(cfg.get("max_interval_minutes", 120)))
        return random.uniform(low, high) * 60

    def _quiet_now(self):
        cfg = proactive_config(self.config)
        start, end = int(cfg.get("quiet_start_hour", 23)), int(cfg.get("quiet_end_hour", 8))
        hour = datetime.now().hour
        if start == end:
            return False
        return start <= hour or hour < end if start > end else start <= hour < end

    async def handle_get(self, request):
        now = time.time()
        speak = False
        if request.query.get("client") == "speaker":
            self.speaker_seen = now
        elif now - self.speaker_seen < SPEAKER_PRIORITY_SECONDS:
            return web.json_response({"speak": False})  # the speaker is in use; the board's headset may be unplugged
        if proactive_config(self.config).get("enabled", False) and not self._quiet_now() and now >= self.next_due:
            speak = True
            self.next_due = time.time() + self._next_gap()
            minutes = (self.next_due - time.time()) / 60
            self.logger.bind(tag=TAG).info(f"Proactive start granted; next in {minutes:.0f} minutes")
        return web.json_response({"speak": speak})
