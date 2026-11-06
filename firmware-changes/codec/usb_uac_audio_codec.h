#ifndef _USB_UAC_AUDIO_CODEC_H
#define _USB_UAC_AUDIO_CODEC_H

#include "audio_codec.h"

#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/task.h>
#include <usb/uac_host.h>

#include <atomic>
#include <mutex>
#include <vector>

// AudioCodec backed by a USB UAC 1.0 headset on the ESP32-S3 USB-OTG port.
//
// Verified descriptors of HUAWEI USB-C HEADSET (VID 0x12D1 / PID 0x3A07):
//   mic / UAC_STREAM_RX : 48000 Hz, 16-bit, mono,   isoch IN  EP 0x81, mps 96
//   spk / UAC_STREAM_TX : 48000 Hz, 16-bit, stereo, isoch OUT EP 0x01, mps 384 (alt1)
//
// This codec therefore declares the device's native 48 kHz. AudioService owns
// the resampling (esp_ae_rate_cvt: 48 kHz -> 16 kHz for ASR/Opus) and configures
// the Opus decoder at output_sample_rate(). Write() only duplicates mono PCM
// into the stereo interleaved stream the headset expects.
class UsbUacAudioCodec : public AudioCodec {
public:
    UsbUacAudioCodec();
    virtual ~UsbUacAudioCodec();

    void Start() override;
    void EnableInput(bool enable) override;
    void EnableOutput(bool enable) override;

protected:
    int Read(int16_t* dest, int samples) override;
    int Write(const int16_t* data, int samples) override;

private:
    struct ConnectEvent {
        uint8_t addr;
        uint8_t iface_num;
        uac_host_driver_event_t event;
    };

    static void UsbHostLibTask(void* arg);
    static void UsbUacTask(void* arg);
    static void DriverEventCb(uint8_t addr, uint8_t iface_num,
                              const uac_host_driver_event_t event, void* arg);
    static void DeviceEventCb(uac_host_device_handle_t handle,
                              const uac_host_device_event_t event, void* arg);

    void HandleConnect(const ConnectEvent& evt);
    void HandleDisconnect(uac_host_device_handle_t handle);

    // UAC_STREAM_RX (microphone) and UAC_STREAM_TX (speaker) are two distinct
    // logical devices for one physical headset.
    uac_host_device_handle_t mic_dev_ = nullptr;
    uac_host_device_handle_t spk_dev_ = nullptr;

    QueueHandle_t event_queue_ = nullptr;
    TaskHandle_t lib_task_ = nullptr;
    TaskHandle_t uac_task_ = nullptr;

    std::mutex mutex_;
    std::vector<int16_t> stereo_buffer_;
    std::atomic<bool> mic_ready_{false};
    std::atomic<bool> spk_ready_{false};
    std::atomic<uint32_t> spk_low_buffer_events_{0};
    int64_t last_low_buffer_log_us_ = 0;
    bool input_requested_ = false;
    bool output_requested_ = false;
};

#endif // _USB_UAC_AUDIO_CODEC_H
