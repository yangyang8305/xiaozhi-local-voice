#include "wifi_board.h"
#include "codecs/usb_uac_audio_codec.h"
#include "application.h"
#include "button.h"
#include "config.h"

#include <esp_log.h>

#define TAG "FreenoveS3UsbUacBoard"

// Minimal WifiBoard for a bare Freenove ESP32-S3 WROOM Board: no display, no
// I2S codec, no I2C peripherals. Voice I/O is a USB-C UAC headset on USB-OTG.
// GetDisplay()/GetLed() fall back to NoDisplay/NoLed from Board.
class FreenoveS3UsbUacBoard : public WifiBoard {
private:
    Button boot_button_;

    void InitializeButtons() {
        boot_button_.OnClick([this]() {
            auto& app = Application::GetInstance();
            if (app.GetDeviceState() == kDeviceStateStarting) {
                EnterWifiConfigMode();
                return;
            }
            app.ToggleChatState();
        });
        boot_button_.OnPressDown([this]() {
            Application::GetInstance().StartListening();
        });
        boot_button_.OnPressUp([this]() {
            Application::GetInstance().StopListening();
        });
    }

public:
    FreenoveS3UsbUacBoard() : boot_button_(BOOT_BUTTON_GPIO) {
        InitializeButtons();
    }

    virtual AudioCodec* GetAudioCodec() override {
        static UsbUacAudioCodec audio_codec;
        return &audio_codec;
    }
};

DECLARE_BOARD(FreenoveS3UsbUacBoard);
