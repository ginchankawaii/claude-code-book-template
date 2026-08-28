// =============================================================================
// config.h — ピン割当・定数・設定(NVS)構造体の定義
//
// このファイルは「SPEC.md §1（ピン/クロック）・§3〜§5（録音/VAD/WAV）・§10（NVS）」
// の確定値を1か所に集めたもの。マジックナンバーを他のファイルに書かないこと。
// 秘密情報（SSID/パスフレーズ/鍵/証明書）は**絶対にここへ書かない**。すべてNVSから読む。
// =============================================================================
#pragma once
#include <Arduino.h>

// ---- ピン（SPEC §1。ハードウェア確定・変更不可）---------------------------
static const int PIN_SWITCH   = 2;   // D1 スライドスイッチ  ON=LOW=録音
static const int PIN_LED      = 4;   // D3 外付けLED(220Ω, 約5.9mA)
static const int PIN_PDM_CLK  = 42;  // PDMマイク CLK
static const int PIN_PDM_DATA = 41;  // PDMマイク DATA
static const int PIN_SD_SCK   = 7;
static const int PIN_SD_MISO  = 8;
static const int PIN_SD_MOSI  = 9;
static const int PIN_SD_CS    = 21;  // 内蔵LEDと共用。内蔵LEDは状態表示に使わない

// ---- クロック / SD ---------------------------------------------------------
static const uint32_t CPU_MHZ_RUN   = 80;        // SPEC §1: 常時 80MHz
static const uint32_t SD_SPI_HZ     = 20000000;  // 20MHz。不安定なら 10MHz へ
static const uint32_t SD_SPI_HZ_LOW = 10000000;

// ---- オーディオ ------------------------------------------------------------
static const uint32_t AUDIO_RATE      = 16000;   // Hz
static const uint32_t AUDIO_BYTES_SEC = 32000;   // 16bit mono
static const size_t   FRAME_SAMPLES   = 320;     // VAD 20ms フレーム
static const size_t   CHUNK_SAMPLES   = 1024;    // I2S 1回読み = 64ms
static const size_t   CHUNK_BYTES     = CHUNK_SAMPLES * 2;
static const uint32_t PREROLL_MS      = 500;     // SPEC §3.1 語頭欠け防止
static const uint32_t MIN_FILE_MS     = 2000;    // SPEC §3.2 最小長
static const uint64_t SD_FREE_MIN     = 50ULL * 1024 * 1024;  // E2 閾値 50MB

// ---- ファイル/ディレクトリ -------------------------------------------------
static const char REC_DIR[]      = "/rec";
static const char EXT_DONE[]     = ".wav";
static const char EXT_RECORDING[] = ".wav.rec";  // 録音中。Phase0 は拾わない

// ---- 通信（SPEC §6）--------------------------------------------------------
static const uint32_t HTTP_CONNECT_MS = 10000;
static const uint32_t HTTP_IO_MS      = 60000;
static const uint32_t SESSION_MAX_MS  = 15UL * 60UL * 1000UL;  // 15分
static const int      FILE_RETRY_MAX  = 3;
static const uint32_t RETRY_BACKOFF_MS[FILE_RETRY_MAX] = {1000, 3000, 9000};

// ---- スイッチのデバウンス（SPEC §2.2）--------------------------------------
static const uint32_t DEBOUNCE_STEP_MS = 20;
static const int      DEBOUNCE_COUNT   = 3;

// ---- NVS 設定値（SPEC §10.1）----------------------------------------------
// 秘密はここに既定値を持たない。空なら「未プロビジョニング」(E11)。
struct Settings {
  String   wifiSsid;      // wifi.ssid
  String   wifiPass;      // wifi.pass  （秘密）
  String   srvUrl;        // srv.url    https:// のみ許可
  String   devId;         // dev.id
  String   caPem;         // srv.ca
  String   devCrt;        // dev.crt
  String   devKey;        // dev.key    （秘密）
  uint8_t  hmacKey[32];   // hmac.key   （秘密）
  bool     hmacSet;

  uint8_t  ledDuty;       // cfg.led_duty   既定15 (10〜20)
  uint16_t splitSec;      // cfg.split_sec  既定600
  uint8_t  gapSec;        // cfg.gap_sec    既定3
  uint8_t  bufSec;        // cfg.buf_sec    既定60 (30〜60)
  uint8_t  vadMargin;     // cfg.vad_margin 既定9 dB
  uint16_t vadHang;       // cfg.vad_hang   既定800 ms
  uint8_t  vadHardclamp;  // cfg.vad_hardclamp 既定0(無効)
  uint8_t  wifiToS;       // cfg.wifi_to_s  既定30 秒

  uint64_t lastEpoch;     // clk.last_epoch
  uint32_t bootCount;     // st.boot_count
};

extern Settings g_cfg;    // settings.cpp が実体を持つ

// ---- ファーム全体の状態（SPEC §2）----------------------------------------
enum AppState {
  ST_BOOT = 0,
  ST_RECORDING,
  ST_FLUSHING,   // RECORDING の内部フェーズだが観測用に持つ
  ST_SYNCING,
  ST_SLEEP,
  ST_FAULT,
  ST_PROVISION
};

// FAULT の理由（LEDと復旧手順の分岐に使う）
enum FaultCause {
  FAULT_NONE = 0,
  FAULT_SD,      // E1/E2/E3
  FAULT_I2S      // E13
};

void logf(const char *fmt, ...);   // mindclip.ino が提供する簡易ログ
