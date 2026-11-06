#ifndef _FREENOVE_S3_USB_UAC_CONFIG_H
#define _FREENOVE_S3_USB_UAC_CONFIG_H

#include <driver/gpio.h>

// Freenove ESP32-S3 WROOM Board (ESP32-S3-WROOM-1 N16R8).
// The BOOT button is GPIO0; the on-board WS2812 RGB LED is GPIO48 and is not
// driven by this board profile (Board::GetLed() returns NoLed).
#define BOOT_BUTTON_GPIO GPIO_NUM_0

// Audio comes from a USB UAC 1.0 headset on the native USB-OTG Type-C port
// (GPIO19 = D-, GPIO20 = D+). The USB-UART Type-C port (CH343) is used for
// flashing and the serial monitor only.
#define USB_UAC_INPUT_SAMPLE_RATE 48000
#define USB_UAC_OUTPUT_SAMPLE_RATE 48000

#endif // _FREENOVE_S3_USB_UAC_CONFIG_H
