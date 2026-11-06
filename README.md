# 小智 AI 全本地语音助手

让 ESP32-S3（小智固件）或蓝牙音箱连接自己电脑上的服务端：语音识别、大模型、语音合成全部在本机运行。

```
耳机模式：USB-C 耳机 ─ ESP32-S3 板子 ─ Wi-Fi ┐
                                             ├─ 服务端 ─ SenseVoice（识别）
音箱模式：SoundCore 2 ─ 蓝牙 ─ 电脑语音客户端 ┘         ├ LM Studio（大模型）
                                                       └ Qwen3-TTS（合成）
```

## 日常使用

桌面上有三个快捷方式：

| 快捷方式 | 用途 | 怎么说话 |
|---|---|---|
| **小智-耳机模式** | USB-C 耳机插在板子的 OTG 口 | 说 **你好翠花**，**她说话时可以直接开口打断** |
| **小智-音箱模式** | 蓝牙音箱 SoundCore 2 | 说 **你好翠花**，要等她说完再说 |
| **小智-全部停止** | 关闭全部服务，释放显存 | 不用时点一下 |

**她会主动找你说话**：白天每隔 30–120 分钟随机开口一次，说完打开麦克风听你回答；30 秒没人回应就安静结束。23 点到 8 点不开口。改频率或关闭，见下面的“主动说话设置”。

- 启动约需 1 分钟。服务窗口要一直开着。
- 第一句可能要等 5–15 秒（模型冷启动），之后通常 2–4 秒开口。
- 耳机和音箱不要同时对话：语音合成同一时间只处理一路，后来的请求会切断前一路。
- 快捷方式丢了：运行 `launch\create-shortcuts.ps1`。

## 这台电脑的配置

| 项目 | 内容 |
|---|---|
| 显卡 | RTX 3090 24GB（大模型约 15GB，语音合成约 2.5GB） |
| 板子 | Freenove ESP32-S3 WROOM，COM3 |
| 耳机 | 华为 USB-C 耳机（48kHz，UAC 1.0） |
| 音箱 | Anker SoundCore 2，已和电脑配对 |
| 大模型 | LM Studio `qwen3.8-27b-humanlike-chat`，端口 1235，一路并发，关闭思考 |
| 语音合成 | Qwen3-TTS 0.6B Base，固定声纹（参考音频 Serena），`faster-qwen3-tts` |
| 语音识别 | SenseVoiceSmall（CPU） |
| 端口 | 8000（WebSocket）、8003（OTA）、8765（TTS）、1235（LM Studio） |

本机路径都在 `C:\AI\ESP32`：

| 目录 | 内容 |
|---|---|
| `launch` | 启动和停止脚本 |
| `xiaozhi-server` | 服务端（已打补丁），配置在 `main\xiaozhi-server\data\.config.yaml` |
| `qwen-tts-service` | 语音合成服务，声音由 `voice\reference-serena.wav` 决定 |
| `pc-voice-client` | 音箱模式的电脑客户端 |
| `tts-eval\qwen3\0.6B-Base` | 语音合成模型 |
| `xiaozhi-esp32` | 固件源码 |
| `xiaozhi-backup` | 固件备份 |

## 常见问题

**板子连不上（电脑 IP 变了）**
板子固件里写死了 `192.168.151.230`。启动时如果 IP 不同，窗口会显示警告。最好在路由器上给电脑固定这个 IP。否则要改 `firmware-changes\board\config.json` 和服务端配置里的地址，再重新编译烧录（见下文）。

**板子没声音、听不到**
确认耳机插在 OTG 口（不是 UART 口），再给板子重新上电。声音小就说“把声音调大”。

**音箱模式报错找不到设备**
打开音箱并连接电脑。设备名不同时，运行 `pc-voice-client\start-voice-client.ps1 --list` 查看，再用 `--input`、`--output` 指定。

**音箱模式音质差**
蓝牙麦克风走通话模式，音质会下降，这是蓝牙协议的限制。

**她答错或听错**
大模型可能答错，语音识别也可能听错专有名词。这不是故障。

**耳机模式被杂音打断**
灵敏度由服务端 `core\handle\receiveAudioHandle.py` 的 `BARGE_IN_FRAMES` 决定，默认 4 帧（约 240 毫秒），调大就更不容易被打断。

**主动说话设置**
改 `.config.yaml` 的 `proactive` 段，然后重启（不用烧录）：

| 配置项 | 含义 |
|---|---|
| `enabled` | `false` 就是关闭 |
| `min_interval_minutes`、`max_interval_minutes` | 随机间隔范围（分钟） |
| `quiet_start_hour`、`quiet_end_hour` | 不开口的时段 |
| `no_reply_seconds` | 开口后多久没人回应就结束 |
| `prompts` | 可选，主动开口时给大模型的提示，一个列表 |

板子每 5 分钟问一次服务端，所以实际开口时间会有最多 5 分钟误差。电脑关着时，板子不会报错。

**“你好翠花”不灵敏或总误唤醒**
板子：`firmware-changes\board\config.json` 里的 `CONFIG_CUSTOM_WAKE_WORD_THRESHOLD`（默认 20，越小越灵敏），改完要重新编译烧录。
音箱：`client.py` 里的 `keywords_threshold`（默认 0.25，越小越灵敏）和 `keywords_score`，重启客户端生效。

**换人设**
改 `.config.yaml` 里的 `prompt`，然后重启（全部停止，再启动）。

**换声音**
替换 `qwen-tts-service\voice\reference-serena.wav`（干净人声，几秒到几十秒，请用你有权使用的声音），然后重启。

**退回官方小智云端**
用 esptool 把备份写回应用分区和资源分区（唤醒词模型在资源分区里，要一起写）：

```
%USERPROFILE%\.platformio\packages\tool-esptool\esptool.exe --chip esp32s3 --port COM3 --baud 921600 write-flash 0x20000 C:\AI\ESP32\xiaozhi-backup\xiaozhi-cloud-2.5.3-usbfix.bin 0x800000 C:\AI\ESP32\xiaozhi-backup\assets-hiesp.bin
```

切回本地：同样的命令，换成同目录的 `xiaozhi-local-2.5.3.bin` 和 `assets-cuihua.bin`。

## 已知限制

- 音箱模式不能中途打断：没有回声消除，音箱的声音会被麦克风收进去。
- 声线和爆音已明显改善，但没有可靠的自动指标，主要靠试听判断。
- 板子不能直接连蓝牙音箱：ESP32-S3 没有经典蓝牙，软件无法解决。
- 官方小智的音色（湾湾小何）在海外个人账号无法开通（BytePlus 要求企业认证）。
- 还没接入私域知识库。

## 从零部署

这个仓库只包含自己写的部分和补丁。模型和上游代码要自行下载。

**1. 服务端**：克隆 [xiaozhi-esp32-server](https://github.com/xinnan-tech/xiaozhi-esp32-server)，检出 `4f6e9ec`。

```
git apply server-changes\server.patch
```

- 把 `qwen_local.py` 放进 `main/xiaozhi-server/core/providers/tts/`，把 `proactive_handler.py` 放进 `main/xiaozhi-server/core/api/`。
- 把 `config.example.yaml` 复制为 `main/xiaozhi-server/data/.config.yaml`，改 IP。
- 把 `start-server.ps1` 放在仓库根目录。
- 建 conda 环境 `xiaozhi-server`（Python 3.10，`libopus`、`ffmpeg`），安装 `requirements.txt` 和 `sounddevice`。
- 下载 SenseVoiceSmall 的 `model.pt` 到 `models/SenseVoiceSmall/`。

**2. 语音合成**：建 conda 环境 `qwen3-tts`（Python 3.12）。

```
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128
pip install faster-qwen3-tts "transformers==5.15.1"
modelscope download --model Qwen/Qwen3-TTS-12Hz-0.6B-Base --local_dir tts-eval\qwen3\0.6B-Base
```

不要同时装官方的 `qwen-tts`，也不要用更新的 `transformers`（模型加载会报错）。

**3. 音箱客户端**：下载 `sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01` 模型到 `pc-voice-client\models\`。

**4. 固件**：克隆 [xiaozhi-esp32](https://github.com/78/xiaozhi-esp32)，检出 `a78ca19`，安装 ESP-IDF 6.1。

```
git apply firmware-changes\firmware.patch
```

把 `firmware-changes\codec\*` 放进 `main/audio/codecs/`，把 `firmware-changes\board\` 放到 `main/boards/freenove-s3-usb-uac/`。然后编译（`--language` 必须写，否则会编成英文）：

```
$env:CCACHE_DISABLE='1'; & C:\AI\esp-idf-v6.1\export.ps1
python scripts/build.py freenove-s3-usb-uac --name freenove-s3-usb-uac-local --language zh-CN --wake-word custom
```

写应用和资源分区，不会丢 Wi-Fi 设置：

```
esptool --chip esp32s3 --port COM3 --baud 921600 write-flash 0x20000 build\xiaozhi.bin 0x800000 build\generated_assets.bin
```

## 致谢

基于 [78/xiaozhi-esp32](https://github.com/78/xiaozhi-esp32)、[xinnan-tech/xiaozhi-esp32-server](https://github.com/xinnan-tech/xiaozhi-esp32-server)、[Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS)、[faster-qwen3-tts](https://github.com/andimarafioti/faster-qwen3-tts)、[sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx)。
