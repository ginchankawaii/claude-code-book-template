// =============================================================================
// mindclip.ino - MindClip DIY Phase 1 firmware (Seeed XIAO ESP32S3 Sense)
//
// This file is intentionally code-free. setup() / loop() and the whole state
// machine live in app.cpp, because the Arduino .ino prototype generator (ctags)
// rewrites .ino files and mangles both multi-byte comments and return types.
// Keeping every function in .cpp/.h files makes the build reproducible and lets
// the sources carry Japanese documentation comments.
//
//   app.cpp / app.h        state machine  BOOT / RECORDING / FLUSHING /
//                          SYNCING / SLEEP / FAULT / PROVISION  (SPEC 2)
//   config.h               pins, constants, NVS-backed Settings   (SPEC 1, 10)
//   settings.cpp           NVS (Preferences) access               (SPEC 10.1)
//   led.cpp                dim LED patterns via LEDC PWM          (SPEC 2.1)
//   rtcclock.cpp           RTC + filename generation              (SPEC 3.3-3.4)
//   vad.cpp                energy VAD + write-duty governor       (SPEC 4)
//   recorder.cpp           PDM -> VAD -> PSRAM buffer -> WAV/SD   (SPEC 3, 5)
//   syncer.cpp             WiFi + mTLS + HMAC + POST + delete     (SPEC 6)
//   provision.cpp          USB serial provisioning CLI            (SPEC 10.2)
//
// Build:
//   arduino-cli compile --fqbn esp32:esp32:XIAO_ESP32S3 firmware/mindclip
//   real hardware: --fqbn esp32:esp32:XIAO_ESP32S3:PSRAM=opi (60 s PSRAM buffer)
//
// No credentials anywhere in this tree: SSID, passphrase, CA, client cert,
// client key and the HMAC secret are stored in NVS only.  See SPEC.md 10.2.
// =============================================================================
#include "app.h"
