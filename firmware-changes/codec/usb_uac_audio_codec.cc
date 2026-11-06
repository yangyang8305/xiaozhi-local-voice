#include "usb_uac_audio_codec.h"

#include <esp_err.h>
#include <esp_intr_alloc.h>
#include <esp_log.h>
#include <esp_timer.h>
#include <usb/usb_host.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>

#define TAG "UsbUacAudioCodec"

namespace {

// Formats read from the headset's UAC 1.0 Format Type I descriptors.
constexpr uint32_t kDeviceSampleRate = 48000;
constexpr uint8_t kBitResolution = 16;
constexpr uint8_t kMicChannels = 1;
constexpr uint8_t kSpkChannels = 2;

constexpr uint32_t kMicBufferSize = 16 * 1024;
// 48 kHz stereo 16-bit is 192 KB/s, so this absorbs about 166 ms of stall.
constexpr uint32_t kSpkBufferSize = 32 * 1024;
constexpr uint32_t kStreamThreshold = 2 * 1024;
// Isochronous transfers must be refilled before their packets run out, so the
// USB tasks have to preempt the audio and application tasks.
constexpr UBaseType_t kUsbTaskPriority = 10;
constexpr int64_t kLowBufferLogIntervalUs = 1000 * 1000;
constexpr uint32_t kIoTimeoutMs = 200;

// uac_host_device_write() expects bytes; keep single USB frame chunks small
// enough to be copied without holding the mutex for a long time.
constexpr int kMaxChunkSamples = 960;

}  // namespace

UsbUacAudioCodec::UsbUacAudioCodec() {
    // Both directions can run at the same time; there is no hardware AEC
    // reference channel, so input_reference_ stays false.
    duplex_ = true;
    input_sample_rate_ = kDeviceSampleRate;
    output_sample_rate_ = kDeviceSampleRate;
    input_channels_ = kMicChannels;
    // AudioService always produces mono PCM. Write() expands it to stereo.
    output_channels_ = 1;

    event_queue_ = xQueueCreate(8, sizeof(ConnectEvent));
    if (event_queue_ == nullptr) {
        ESP_LOGE(TAG, "Failed to create event queue");
        return;
    }

    // The UAC class driver handles usb_host_client_handle_events() in its own
    // background task, but usb_host_lib_handle_events() still needs a task of
    // its own. usb_host_install() must be called before uac_host_install().
    usb_host_config_t host_cfg = {};
    host_cfg.skip_phy_setup = false;
    host_cfg.root_port_unpowered = false;
    host_cfg.intr_flags = ESP_INTR_FLAG_LEVEL1;
    host_cfg.enum_filter_cb = nullptr;
    esp_err_t err = usb_host_install(&host_cfg);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "usb_host_install failed: 0x%X", (unsigned)err);
        return;
    }
    if (xTaskCreate(UsbHostLibTask, "uac_usb_lib", 4096, nullptr, kUsbTaskPriority, &lib_task_) != pdPASS) {
        ESP_LOGE(TAG, "Failed to create USB host library task");
        return;
    }

    uac_host_driver_config_t drv_cfg = {};
    drv_cfg.create_background_task = true;
    drv_cfg.task_priority = kUsbTaskPriority;
    drv_cfg.stack_size = 4096;
    drv_cfg.callback = DriverEventCb;
    drv_cfg.callback_arg = this;
    err = uac_host_install(&drv_cfg);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "uac_host_install failed: 0x%X", (unsigned)err);
        return;
    }

    // Opening a device and calling uac_host_device_start() issues control
    // transfers, so do it outside the driver event callback.
    if (xTaskCreate(UsbUacTask, "uac_ctrl", 4096, this, 5, &uac_task_) != pdPASS) {
        ESP_LOGE(TAG, "Failed to create UAC control task");
        return;
    }
    ESP_LOGI(TAG, "USB UAC host installed, waiting for headset on USB-OTG");
}

UsbUacAudioCodec::~UsbUacAudioCodec() {
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (mic_dev_ != nullptr) uac_host_device_close(mic_dev_);
        if (spk_dev_ != nullptr) uac_host_device_close(spk_dev_);
        mic_dev_ = nullptr;
        spk_dev_ = nullptr;
    }
    mic_ready_ = false;
    spk_ready_ = false;
    uac_host_uninstall();
    // usb_host is intentionally left installed: the firmware never tears down
    // the USB host stack during its lifetime, and uninstalling requires all
    // devices to be freed first.
    if (uac_task_ != nullptr) vTaskDelete(uac_task_);
    if (lib_task_ != nullptr) vTaskDelete(lib_task_);
    if (event_queue_ != nullptr) vQueueDelete(event_queue_);
}

void UsbUacAudioCodec::Start() {
    AudioCodec::Start();
    ESP_LOGI(TAG, "USB UAC codec started: 48000 Hz, mic mono / speaker stereo");
}

void UsbUacAudioCodec::UsbHostLibTask(void* arg) {
    while (true) {
        uint32_t event_flags = 0;
        usb_host_lib_handle_events(portMAX_DELAY, &event_flags);
    }
}

void UsbUacAudioCodec::UsbUacTask(void* arg) {
    auto* self = static_cast<UsbUacAudioCodec*>(arg);
    ConnectEvent evt;
    while (true) {
        if (xQueueReceive(self->event_queue_, &evt, portMAX_DELAY) == pdTRUE) {
            self->HandleConnect(evt);
        }
    }
}

void UsbUacAudioCodec::DriverEventCb(uint8_t addr, uint8_t iface_num,
                                     const uac_host_driver_event_t event, void* arg) {
    auto* self = static_cast<UsbUacAudioCodec*>(arg);
    if (self == nullptr || self->event_queue_ == nullptr) return;
    ConnectEvent evt = {addr, iface_num, event};
    xQueueSend(self->event_queue_, &evt, 0);
}

void UsbUacAudioCodec::DeviceEventCb(uac_host_device_handle_t handle,
                                     const uac_host_device_event_t event, void* arg) {
    auto* self = static_cast<UsbUacAudioCodec*>(arg);
    if (self == nullptr) return;
    if (event == UAC_HOST_DRIVER_EVENT_DISCONNECTED) {
        ESP_LOGW(TAG, "UAC device disconnected");
        self->HandleDisconnect(handle);
    } else if (event == UAC_HOST_DEVICE_EVENT_TX_DONE) {
        self->spk_low_buffer_events_.fetch_add(1, std::memory_order_relaxed);
    } else if (event == UAC_HOST_DEVICE_EVENT_TRANSFER_ERROR) {
        ESP_LOGW(TAG, "UAC transfer error");
    }
}

void UsbUacAudioCodec::HandleDisconnect(uac_host_device_handle_t handle) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (handle == mic_dev_) {
        mic_dev_ = nullptr;
        mic_ready_ = false;
    } else if (handle == spk_dev_) {
        spk_dev_ = nullptr;
        spk_ready_ = false;
    }
    uac_host_device_close(handle);
}

void UsbUacAudioCodec::HandleConnect(const ConnectEvent& evt) {
    const bool is_mic = (evt.event == UAC_HOST_DRIVER_EVENT_RX_CONNECTED);

    uac_host_device_config_t dev_cfg = {};
    dev_cfg.addr = evt.addr;
    dev_cfg.iface_num = evt.iface_num;
    dev_cfg.buffer_size = is_mic ? kMicBufferSize : kSpkBufferSize;
    dev_cfg.buffer_threshold = kStreamThreshold;
    dev_cfg.callback = DeviceEventCb;
    dev_cfg.callback_arg = this;

    uac_host_device_handle_t handle = nullptr;
    esp_err_t err = uac_host_device_open(&dev_cfg, &handle);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "uac_host_device_open(addr=%u, iface=%u) failed: 0x%X",
                 evt.addr, evt.iface_num, (unsigned)err);
        return;
    }

    uac_host_dev_info_t info = {};
    if (uac_host_get_device_info(handle, &info) == ESP_OK) {
        ESP_LOGI(TAG, "UAC %s connected: addr=%u iface=%u VID=0x%04X PID=0x%04X",
                 is_mic ? "microphone" : "speaker", evt.addr, evt.iface_num,
                 (unsigned)info.VID, (unsigned)info.PID);
    }

    // Select alt1 (16-bit PCM / 48000 Hz) on both streaming interfaces.
    // The driver performs SET_INTERFACE and the UAC1.0 SET_CUR sampling
    // frequency control transfers internally.
    uac_host_stream_config_t stream_cfg = {};
    stream_cfg.channels = is_mic ? kMicChannels : kSpkChannels;
    stream_cfg.bit_resolution = kBitResolution;
    stream_cfg.sample_freq = kDeviceSampleRate;
    err = uac_host_device_start(handle, &stream_cfg);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "uac_host_device_start(%s, %u Hz, %u ch, %u bit) failed: 0x%X",
                 is_mic ? "mic" : "spk", (unsigned)kDeviceSampleRate,
                 (unsigned)stream_cfg.channels, (unsigned)kBitResolution, (unsigned)err);
        uac_host_device_close(handle);
        return;
    }

    bool enable_stream = false;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (is_mic) {
            mic_dev_ = handle;
            mic_ready_ = true;
            enable_stream = input_requested_;
        } else {
            spk_dev_ = handle;
            spk_ready_ = true;
            enable_stream = output_requested_;
        }
    }
    // uac_host_device_start() already starts transfers. Suspend only if the
    // application has not asked for this direction yet.
    if (!enable_stream) {
        uac_host_device_suspend(handle);
    }
    ESP_LOGI(TAG, "UAC %s stream ready", is_mic ? "microphone" : "speaker");
}

void UsbUacAudioCodec::EnableInput(bool enable) {
    AudioCodec::EnableInput(enable);
    uac_host_device_handle_t handle = nullptr;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        input_requested_ = enable;
        handle = mic_dev_;
    }
    if (handle == nullptr) return;
    if (enable) {
        uac_host_device_resume(handle);
    } else {
        uac_host_device_suspend(handle);
    }
}

void UsbUacAudioCodec::EnableOutput(bool enable) {
    AudioCodec::EnableOutput(enable);
    uac_host_device_handle_t handle = nullptr;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        output_requested_ = enable;
        handle = spk_dev_;
    }
    if (handle == nullptr) return;
    if (enable) {
        uac_host_device_resume(handle);
    } else {
        uac_host_device_suspend(handle);
    }
}

int UsbUacAudioCodec::Read(int16_t* dest, int samples) {
    if (dest == nullptr || samples <= 0) return 0;

    uac_host_device_handle_t handle = nullptr;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        handle = mic_dev_;
    }
    if (handle == nullptr || !mic_ready_.load()) {
        vTaskDelay(pdMS_TO_TICKS(10));
        return 0;
    }

    // Microphone is 16-bit mono: USB little-endian matches the Xtensa layout.
    const uint32_t wanted = static_cast<uint32_t>(samples) * sizeof(int16_t);
    uint32_t bytes_read = 0;
    esp_err_t err = uac_host_device_read(handle, reinterpret_cast<uint8_t*>(dest), wanted,
                                         &bytes_read, pdMS_TO_TICKS(kIoTimeoutMs));
    if (err != ESP_OK || bytes_read < sizeof(int16_t)) return 0;

    int count = static_cast<int>(bytes_read / sizeof(int16_t));
    if (input_gain_ > 0) {
        const int gain_factor = static_cast<int>(input_gain_);
        for (int i = 0; i < count; ++i) {
            int32_t amplified = static_cast<int32_t>(dest[i]) * gain_factor;
            dest[i] = static_cast<int16_t>(std::clamp(amplified,
                                                      static_cast<int32_t>(-INT16_MAX),
                                                      static_cast<int32_t>(INT16_MAX)));
        }
    }
    return count;
}

int UsbUacAudioCodec::Write(const int16_t* data, int samples) {
    if (data == nullptr || samples <= 0) return 0;

    uac_host_device_handle_t handle = nullptr;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        handle = spk_dev_;
    }
    if (handle == nullptr || !spk_ready_.load()) return 0;

    // Fired when the speaker buffer falls to its threshold or runs dry while
    // playing, so a rising count during speech points at a USB underrun.
    const int64_t now_us = esp_timer_get_time();
    if (now_us - last_low_buffer_log_us_ >= kLowBufferLogIntervalUs) {
        const uint32_t events = spk_low_buffer_events_.exchange(0, std::memory_order_relaxed);
        if (events > 0) {
            ESP_LOGW(TAG, "Speaker buffer low %u times", (unsigned)events);
        }
        last_low_buffer_log_us_ = now_us;
    }

    // Same software volume curve as NoAudioCodec: (volume/100)^2 * 65536.
    const int32_t volume_factor = static_cast<int32_t>(
        std::pow(static_cast<double>(output_volume_) / 100.0, 2) * 65536.0);

    int written = 0;
    while (written < samples) {
        const int chunk = std::min(kMaxChunkSamples, samples - written);
        const size_t stereo_samples = static_cast<size_t>(chunk) * kSpkChannels;
        stereo_buffer_.resize(stereo_samples);
        for (int i = 0; i < chunk; ++i) {
            const int64_t temp = static_cast<int64_t>(data[written + i]) * volume_factor;
            const int32_t scaled = static_cast<int32_t>(
                std::clamp<int64_t>(temp / 65536, -INT16_MAX, INT16_MAX));
            const int16_t value = static_cast<int16_t>(scaled);
            stereo_buffer_[2 * i] = value;
            stereo_buffer_[2 * i + 1] = value;
        }

        const uint32_t bytes = static_cast<uint32_t>(stereo_samples * sizeof(int16_t));
        esp_err_t err = uac_host_device_write(handle,
                                              reinterpret_cast<uint8_t*>(stereo_buffer_.data()),
                                              bytes, pdMS_TO_TICKS(kIoTimeoutMs));
        if (err != ESP_OK) {
            ESP_LOGW(TAG, "uac_host_device_write failed: 0x%X", (unsigned)err);
            break;
        }
        written += chunk;
    }
    return written;
}
