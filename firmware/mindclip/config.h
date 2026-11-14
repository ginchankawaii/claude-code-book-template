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
// I2S 1回読み。**必ず FRAME_SAMPLES の整数倍**にすること。倍数でないと
// recorderPump の frames = got/(FRAME_SAMPLES*2) が端数を取りこぼす。
// 960 = 3フレーム = 60ms（DMA 90ms より短く、書込32KB=約32msと合わせても余裕がある）
static const size_t   CHUNK_SAMPLES   = 960;
static const size_t   CHUNK_BYTES     = CHUNK_SAMPLES * 2;
static_assert(CHUNK_SAMPLES % FRAME_SAMPLES == 0, "CHUNK_SAMPLES must be a multiple of FRAME_SAMPLES");
static const uint32_t PREROLL_MS      = 500;     // SPEC §3.1 語頭欠け防止
// E15: readBytes() が 0 を返し続けたら I2S を死んだとみなすまでの時間（SPEC §7 = 5秒）
static const uint32_t I2S_STALL_MS    = 5000;
static const uint32_t MIN_FILE_MS     = 2000;    // SPEC §3.2 最小長
// SPEC §5.3: 電源断から復旧した .wav.rec を残す最小長。MIN_FILE_MS より短くしてあるのは、
// 復旧対象が「物音の誤検出」ではなく「電源断で途中まで書けた発話」だからである。
static const uint32_t RECOVER_MIN_MS  = 1000;
// SPEC §5.2 規定1: ドレイン中に flush＋ヘッダ更新を挟む間隔。1回のコストは 32KB 書込 1回と
// 同程度（seek 2往復＋fsync 2回）なので、チャンクごとではなく時間で間引く。
static const uint32_t HDR_CHECKPOINT_MS = 1000;
static const uint64_t SD_FREE_MIN     = 50ULL * 1024 * 1024;  // E2 閾値 50MB

// ---- ファイル/ディレクトリ -------------------------------------------------
static const char REC_DIR[]      = "/rec";
static const char EXT_DONE[]     = ".wav";
static const char EXT_RECORDING[] = ".wav.rec";  // 録音中。Phase0 は拾わない
// E16（SPEC §6.3）: 「3セッション連続400」のカウントはSD上のファイル名で持つ。
// .b1/.b2 は送信対象（次セッションで再挑戦）、.bad は列挙から外す。いずれも削除しない。
static const char EXT_BAD1[]     = ".wav.b1";
static const char EXT_BAD2[]     = ".wav.b2";
static const char EXT_BAD[]      = ".wav.bad";

// 送信対象のファイル名か（.wav / .wav.b1 / .wav.b2。.wav.bad と .wav.rec は除く）
static inline bool isSendableName(const String &n) {
  return n.endsWith(EXT_DONE) || n.endsWith(EXT_BAD1) || n.endsWith(EXT_BAD2);
}

// ---- 通信（SPEC §6）--------------------------------------------------------
static const uint32_t HTTP_CONNECT_MS = 10000;
static const uint32_t HTTP_IO_MS      = 60000;
static const uint32_t SESSION_MAX_MS  = 15UL * 60UL * 1000UL;  // 15分
// SPEC §6.3 / §7 E5: ファイル単位で3回試し、試行間の待ちは 0 / 1s / 3s（合計4秒）。
// 添字は attempt そのもの（[attempt-1] にすると末尾の値が一度も使われない）。
static const int      FILE_RETRY_MAX  = 3;
static const uint32_t RETRY_BACKOFF_MS[FILE_RETRY_MAX] = {0, 1000, 3000};

// ---- スイッチのデバウンス（SPEC §2.2）--------------------------------------
static const uint32_t DEBOUNCE_STEP_MS = 20;
static const int      DEBOUNCE_COUNT   = 3;
// SYNCING に入ってから無線を起こすまでの猶予。この間にスイッチが ON に戻れば WiFi を一切
// 使わずに録音へ戻る（E8）。「OFF→ON で録音中か確認する」操作と誤操作の両方を救う。
static const uint32_t SYNC_GRACE_MS = 1500;
// cfg.led_mode: dark = 録音中は完全消灯（既定）/ normal = SPEC §2.1 の全パターンを表示
static const uint8_t LED_MODE_DARK   = 0;
static const uint8_t LED_MODE_NORMAL = 1;
// 同期失敗の理由を sleep 前に点滅で示す時間（SPEC §7）。この間もスイッチ ON は見る（E8）。
static const uint32_t ERR_BLINK_MS = 10000;
// PROVISION の無入力タイムアウト（SPEC §10.2）。USB の先のホストが起動直後に勝手に何か
// 送ってきただけ、という場合に録音しないまま居座らないための上限。
static const uint32_t PROVISION_IDLE_MS = 5UL * 60UL * 1000UL;

// ---- 未同期クロックの「時刻基準の区間」（SPEC §3.4）-------------------------
// st.boot_count が firstBoot 以降（次の区間の手前まで）の起動は同じ時計の基準を共有する。
// known なら「その基準の時刻 + offSec = 真の時刻」。UNSYNC ファイルの Age-Ms 算出に使う。
// NVS に blob のまま置くので、詰め物が入らない並び（8+4+4）を崩さないこと。
static const int CLK_SEG_MAX = 6;
struct ClockSeg {
  int64_t  offSec;
  uint32_t firstBoot;
  uint32_t known;
};
static_assert(sizeof(ClockSeg) == 16, "ClockSeg is stored as a raw NVS blob");

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
  uint8_t  ledMode;       // cfg.led_mode   既定 dark (LED_MODE_DARK / LED_MODE_NORMAL)
  uint16_t splitSec;      // cfg.split_sec  既定600
  uint8_t  gapSec;        // cfg.gap_sec    既定3
  uint8_t  bufSec;        // cfg.buf_sec    既定60 (30〜60)
  uint8_t  vadMargin;     // cfg.vad_margin 既定9 dB
  uint16_t vadHang;       // cfg.vad_hang   既定800 ms
  uint8_t  vadHardclamp;  // cfg.vad_hardclamp 既定0(無効)
  uint8_t  wifiToS;       // cfg.wifi_to_s  既定30 秒

  uint64_t lastEpoch;     // clk.last_epoch
  ClockSeg clkSeg[CLK_SEG_MAX];  // clk.segs  古い順
  uint8_t  clkSegN;
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
  FAULT_I2S,     // E13
  FAULT_MEM      // E12: 書込バッファが1バイトも確保できない（録音不能）
};

// 簡易ログ（実体は app.cpp）。標準の logf(float) と名前衝突させないため mcLogf。
void mcLogf(const char *fmt, ...);
