// app.cpp — 状態機械の本体（SPEC §2 の7状態）。setup()/loop() もここにある。
//   BOOT / RECORDING(LISTEN⇄CAPTURE) / FLUSHING / SYNCING / SLEEP / FAULT / PROVISION
// を「1状態=1関数」で実装する。loop() に巨大なif連鎖を作らないこと。
// .ino 側に関数を置かない理由は app.h のコメントを参照。
#include "app.h"
#include "config.h"
#include "settings.h"
#include "led.h"
#include "rtcclock.h"
#include "vad.h"
#include "recorder.h"
#include "syncer.h"
#include "provision.h"

#include <WiFi.h>
#include <esp_wifi.h>
#include <esp_sleep.h>
#include <driver/gpio.h>
#include <driver/rtc_io.h>
#include <SPI.h>
#include <stdarg.h>

// loopTask 既定8KBに対し syncRun() だけでフレーム約2.6KB。mbedTLS ハンドシェイクと
// FATFS の LFN バッファがこの上に乗るので、余裕を持たせておく（安い保険）。
SET_LOOP_TASK_STACK_SIZE(16384);

static AppState  s_state   = ST_BOOT;
static uint32_t  s_faultT  = 0;
static bool      s_psramOk = true;
static bool      s_bootDone = false;   // 誤ウェイク判定を初回BOOTだけに限るためのフラグ

void mcLogf(const char *fmt, ...) {
  char buf[256];   // [stat] 行（SPEC §4.2）が入る長さ
  va_list ap;
  va_start(ap, fmt);
  vsnprintf(buf, sizeof(buf), fmt, ap);
  va_end(ap);
  Serial.println(buf);
}

// ---------------------------------------------------------------------------
// スイッチ（SPEC §2.2: 20ms×3回一致のデバウンス。ON=LOW=録音）
// ---------------------------------------------------------------------------
static bool     s_swLow      = true;   // 現在信じている位置（true = LOW = 録音）
static int      s_swRaw      = -1;
static int      s_swAgree    = 0;
static uint32_t s_swLastMs   = 0;
static uint32_t s_swUnstable = 0;

// 20ms間隔で1サンプルずつ取り、3回一致で確定させる非ブロッキング版。
// RECORDING 中は録音ループ（1周=64ms）から呼ぶ。ここで delay() を挟むと
// I2S の DMA が溢れるので、**ブロッキング版を録音中に使わないこと**。
static void swPollNonBlocking() {
  uint32_t now = millis();
  if (now - s_swLastMs < DEBOUNCE_STEP_MS) return;
  s_swLastMs = now;
  int v = digitalRead(PIN_SWITCH);
  if (v == s_swRaw) {
    if (++s_swAgree >= DEBOUNCE_COUNT) {
      s_swAgree = DEBOUNCE_COUNT;
      s_swLow = (v == LOW);
      s_swUnstable = 0;
    }
  } else {
    s_swRaw = v;
    s_swAgree = 1;
    if (s_swUnstable == 0) s_swUnstable = now;
  }
  // E14: 5秒デバウンス不成立 → 安全側（録音継続）に倒す
  if (s_swUnstable && now - s_swUnstable > 5000) s_swLow = true;
}

// BOOT / FAULT / 同期のファイル境界など、40ms止まっても支障のない場所で使う版
static bool swReadBlocking() {
  int a = digitalRead(PIN_SWITCH); delay(DEBOUNCE_STEP_MS);
  int b = digitalRead(PIN_SWITCH); delay(DEBOUNCE_STEP_MS);
  int c = digitalRead(PIN_SWITCH);
  if (a == b && b == c) { s_swLow = (a == LOW); s_swUnstable = 0; s_swAgree = DEBOUNCE_COUNT; s_swRaw = a; }
  else if (s_swUnstable == 0) s_swUnstable = millis();
  return s_swLow;
}

static bool syncAbortCb() { return swReadBlocking(); }   // E8: スイッチONで中断

// ---------------------------------------------------------------------------
// SLEEP（SPEC §9。順序を守ること）
// ---------------------------------------------------------------------------
static void goToDeepSleep() {
  s_state = ST_SLEEP;

  // 1) SD を安全に切り離し、CS を HIGH に固定したままホールドする
  recorderUnmountSD();
  SPI.end();
  pinMode(PIN_SD_CS, OUTPUT);
  digitalWrite(PIN_SD_CS, HIGH);
  gpio_hold_en((gpio_num_t)PIN_SD_CS);

  // 2) 無線を確実に落とす
  WiFi.disconnect(true);
  WiFi.mode(WIFI_OFF);
  esp_wifi_stop();
  btStop();

  // 3) LED を消し、CS と同じくホールドする（GPIO4 をフロートさせない）
  ledOffHard();                    // ledcDetach → OUTPUT/LOW まで済ませる
  gpio_hold_en((gpio_num_t)PIN_LED);

  // 4) ホールドを deep sleep 中も維持する。**gpio_hold_en だけでは足りない**:
  //    driver/gpio.h の gpio_hold_en 注記3 のとおり、ESP32-S3 では digital GPIO の
  //    状態は deep sleep 中に保持されず、gpio_deep_sleep_hold_en() が要る。
  gpio_deep_sleep_hold_en();

  // 5) SPI の SCK/MOSI/MISO は pinMode(INPUT_PULLDOWN) を掛けても deep sleep 中に
  //    設定が失われてフロートし、SDカード側の入力バッファが中間電位でシュートスルーする
  //    （ELECTRICAL §2.2 が CS について書いた事象と同じことが3本にも起きる）。
  //    sleep 予算は9時間で27mAh しかないので、RTCドメインごと切り離して黙らせる。
  rtc_gpio_isolate((gpio_num_t)PIN_SD_SCK);
  rtc_gpio_isolate((gpio_num_t)PIN_SD_MOSI);
  rtc_gpio_isolate((gpio_num_t)PIN_SD_MISO);

  // 6) ウェイク要因: EXT0 = GPIO2 が LOW。RTCドメインのプルアップを明示的に有効化する
  rtc_gpio_pullup_en((gpio_num_t)PIN_SWITCH);
  rtc_gpio_pulldown_dis((gpio_num_t)PIN_SWITCH);
  esp_sleep_enable_ext0_wakeup((gpio_num_t)PIN_SWITCH, 0);

  Serial.flush();
  esp_deep_sleep_start();   // ここから戻らない
}

// エラー種別に応じて sleep 前に10秒だけ理由を点滅で示す（SPEC §7）
static void blinkThenSleep(LedPattern p) {
  ledSetPattern(p);
  uint32_t t0 = millis();
  while (millis() - t0 < 10000) { ledTick(); delay(10); }
  goToDeepSleep();
}

// ---------------------------------------------------------------------------
// 状態: BOOT
// ---------------------------------------------------------------------------
static void stateBoot() {
  bool low = swReadBlocking();

  // SPEC §9: EXT0 で起きたのにスイッチが OFF に戻っていたら誤ウェイク。何もせず寝る。
  if (!low && esp_sleep_get_wakeup_cause() == ESP_SLEEP_WAKEUP_EXT0 && !s_bootDone) {
    mcLogf("[BOOT] spurious EXT0 wake -> sleep");
    goToDeepSleep();
    return;
  }
  s_bootDone = true;

  if (!recorderMountSD()) {                        // E1
    mcLogf("[BOOT] SD mount failed");
    s_state = ST_FAULT; s_faultT = millis();
    return;
  }
  recorderRecoverRecFiles();                       // SPEC §5.3

  if (!recorderInitI2S()) {                        // E13
    mcLogf("[BOOT] I2S init failed");
    s_state = ST_FAULT; s_faultT = millis();
    return;
  }

  if (low) {
    recorderEnterRecording();
    s_state = ST_RECORDING;
    mcLogf("[BOOT] -> RECORDING (buf=%lus psram=%d rtc_valid=%d)",
         (unsigned long)recorderBufferSeconds(), (int)s_psramOk, (int)clockValid());
  } else if (recorderHasPendingFiles() || settingsIsProvisioned()) {
    recorderDeinitI2S();                 // 同期中にPDMクロック/DMAを回したままにしない
    recorderFreeBuffers();
    s_state = ST_SYNCING;
    mcLogf("[BOOT] -> SYNCING");
  } else {
    recorderDeinitI2S();
    goToDeepSleep();
  }
}

// ---------------------------------------------------------------------------
// 状態: RECORDING（内部で LISTEN⇄CAPTURE、書込中は FLUSHING 相当）
// ---------------------------------------------------------------------------
static void stateRecording() {
  // 表示: CAPTURE=連続微灯 / LISTEN=4秒ごとのパルス。
  // RTC未同期(E9)のときは10秒ごとに2回点滅を割り込ませる。
  bool unsyncHint = !clockValid() && ((millis() % 10000) < 900);
  ledSetPattern(unsyncHint ? LEDP_ERR2 : (recorderIsCapturing() ? LEDP_CAPTURE : LEDP_LISTEN));

  recorderPump();          // ここで i2s_read がブロックし、CPUは WFI に入る

  // SPEC §4.2 の必須計器。README §8.6 で 28mA を落としたとき、原因が I_idle なのか
  // D_capture なのかをこの1行だけで切り分ける（§8.4 の結論は「成否は I_idle で決まる」）。
  //   D_spi        … 累積SPI書込時間 ÷ 経過時間（電力式の D_spi そのもの）
  //   flush_ms_max … 1バーストの最大所要ms。DMA(90ms)を溢れさせていないかの唯一の証拠
  //   cpu_busy     … 1 - i2s_read でブロックしていた割合。I_idle の代理指標
  static uint32_t s_telemetryMs = 0;
  if (millis() - s_telemetryMs >= 60000) {
    s_telemetryMs = millis();
    double elUs = (double)recorderStatElapsedMs() * 1000.0;
    if (elUs < 1.0) elUs = 1.0;
    double dSpi = (double)recorderSpiBusyUs() / elUs;
    double busy = 1.0 - (double)recorderI2sWaitUs() / elUs;
    if (busy < 0.0) busy = 0.0;
    mcLogf("[stat] up=%lus D_cap=%.3f D_spi=%.3f cpu_busy=%.3f buf=%lus floor=%.1fdB "
           "margin=%u wrote=%.1fMB files=%lu flush_ms_max=%lu drops=%luB",
           (unsigned long)(millis() / 1000), (double)vadDutyCapture(), dSpi, busy,
           (unsigned long)recorderBufferSeconds(), (double)vadFloorDb(), vadMarginDb(),
           (double)recorderWrittenBytes() / 1048576.0,
           (unsigned long)recorderFileCount(), (unsigned long)recorderFlushMsMax(),
           (unsigned long)recorderOverflowDrops());
  }

  if (vadTakeWarn())
    mcLogf("[VAD] WARN margin at max for 10min (騒音下 or マイク開口が塞がっている可能性)");

  if (recorderFaultCause() != FAULT_NONE) {
    recorderFinishAndClose();
    s_state = ST_FAULT; s_faultT = millis();
    mcLogf("[REC] -> FAULT");
    return;
  }

  swPollNonBlocking();
  if (!s_swLow) {                              // E7: スイッチOFF
    ledSetPattern(LEDP_SYNC);
    recorderFinishAndClose();                  // 最終フラッシュ→ヘッダ更新→クローズ→.wav
    recorderDeinitI2S();
    recorderFreeBuffers();                     // 縮退構成(バッファがDRAM)でのmbedTLS圧迫を避ける
    s_state = ST_SYNCING;
    mcLogf("[REC] -> SYNCING");
  }
}

// ---------------------------------------------------------------------------
// 状態: SYNCING
// ---------------------------------------------------------------------------
static void stateSyncing() {
  ledSetPattern(LEDP_SYNC);
  SyncResult r = syncRun(syncAbortCb);
  recorderRefreshFreeSpace();
  mcLogf("[SYNC] %s sent=%d carry=%d", syncResultName(r), syncSentCount(), syncCarryCount());

  switch (r) {
    case SYNC_ABORT_SWITCH:                        // E8: 録音へ復帰
      recorderAllocBuffers();                      // SYNCING 前に返したぶんを取り直す
      if (recorderBufferSeconds() == 0 || !recorderInitI2S()) {
        s_state = ST_FAULT; s_faultT = millis(); return;
      }
      recorderEnterRecording();
      s_state = ST_RECORDING;
      return;
    case SYNC_AUTH_FAIL:                           // E6
      blinkThenSleep(LEDP_ERR5);
      return;
    case SYNC_NO_WIFI:                             // E4
    case SYNC_SERVER_FAIL:                         // E5
    case SYNC_CARRY_OVER:
      blinkThenSleep(LEDP_ERR2);
      return;
    case SYNC_SD_FAIL:                             // /rec が読めない = E1相当。無警告に寝ない
      blinkThenSleep(LEDP_FAULT);
      return;
    case SYNC_NOT_PROVISIONED:                     // E11
      blinkThenSleep(LEDP_ERR5);
      return;
    case SYNC_OK:
    default:
      goToDeepSleep();
      return;
  }
}

// ---------------------------------------------------------------------------
// 状態: FAULT（SPEC §7 E1/E2/E3/E13）
// 録音は止めるが、同期経路（スイッチOFF）は必ず生かす。
// ---------------------------------------------------------------------------
static void stateFault() {
  ledSetPattern(LEDP_FAULT);
  ledTick();

  if (!swReadBlocking()) { recorderDeinitI2S(); s_state = ST_SYNCING; return; }

  if (millis() - s_faultT >= 30000) {              // 30秒ごとに再マウント/再初期化
    s_faultT = millis();
    FaultCause c = recorderFaultCause();
    if (c == FAULT_MEM) {                        // E12: バッファ再確保に賭ける
      if (!recorderAllocBuffers() && recorderBufferSeconds() == 0) {
        mcLogf("[FAULT] buffer alloc still failing");
        delay(20);
        return;
      }
      recorderClearFault();
    }
    recorderUnmountSD();
    recorderClearFault();
    const char *why = "sd-mount";
    bool ok = recorderMountSD();
    if (ok && recorderFreeBytes() < SD_FREE_MIN) { why = "free<50MB"; ok = false; }
    if (ok) {
      recorderRecoverRecFiles();
      if (c == FAULT_I2S) recorderDeinitI2S();
      if (recorderInitI2S()) {
        recorderEnterRecording();
        s_state = ST_RECORDING;
        mcLogf("[FAULT] recovered -> RECORDING");
        return;
      }
      why = "i2s-init";
    }
    // 復帰できなかったので FAULT に留まる。判定前に recorderClearFault() を通っている以上
    // recorderFaultCause() は 0 に見えうるので、**元の原因 c と失敗箇所 why** を必ず出す。
    mcLogf("[FAULT] retry failed (cause=%d now=%d why=%s)",
           (int)c, (int)recorderFaultCause(), why);
  }
  delay(20);
}

// ---------------------------------------------------------------------------
void setup() {
  // ウェイク直後のホールド解除（これを忘れると SD の CS を制御できない）
  gpio_deep_sleep_hold_dis();
  gpio_hold_dis((gpio_num_t)PIN_SD_CS);
  gpio_hold_dis((gpio_num_t)PIN_LED);

  setCpuFrequencyMhz(CPU_MHZ_RUN);        // SPEC §1: 常時 80MHz。以降上げない
  btStop();                               // BLE を明示的に落とす
  WiFi.mode(WIFI_OFF);                    // 日中は無線完全オフ

  Serial.begin(115200);
  pinMode(PIN_SWITCH, INPUT_PULLUP);

  settingsLoad();
  clockBegin();
  ledBegin(g_cfg.ledDuty);
  ledBlinkBlocking(1, 200, 0);            // BOOT: 0.2s×1回

  s_psramOk = recorderAllocBuffers();
  if (!s_psramOk) { mcLogf("[BOOT] buffer degraded -> %lus", (unsigned long)recorderBufferSeconds());
                    ledBlinkBlocking(4, 120, 120); }        // E12
  if (!settingsIsProvisioned()) ledBlinkBlocking(5, 120, 120);  // E11

  // PROVISION: 起動後3秒以内にUSBシリアル受信があればCLIへ。
  // ただし EXT0（スイッチON）で起きたときは待たない — 待つと毎回3秒ぶん録り逃す。
  uint32_t provWin = (esp_sleep_get_wakeup_cause() == ESP_SLEEP_WAKEUP_EXT0) ? 0 : 3000;
  if (provisionShouldEnter(provWin)) provisionRun();        // reboot するまで戻らない

  s_state = ST_BOOT;
  stateBoot();
}

void loop() {
  ledTick();
  switch (s_state) {
    case ST_RECORDING: stateRecording(); break;
    case ST_SYNCING:   stateSyncing();   break;
    case ST_FAULT:     stateFault();     break;
    case ST_BOOT:      stateBoot();      break;
    case ST_FLUSHING:  s_state = ST_RECORDING; break;   // 書込は recorderPump 内で完結する
    case ST_SLEEP:     goToDeepSleep();  break;
    case ST_PROVISION: provisionRun();   break;
  }
}
