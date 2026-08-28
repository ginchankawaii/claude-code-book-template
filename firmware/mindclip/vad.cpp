// vad.cpp — エネルギー閾値VADとデューティ・ガバナ。詳細は vad.h を参照。
#include "vad.h"
#include <math.h>

static const int   WIN_SEC       = 600;      // ガバナのスライディング窓
static const int   FRAMES_PER_SEC = 50;      // 20ms フレーム
static const int   ONSET_FRAMES  = 3;        // 60ms 連続超過で CAPTURE
static const float THR_MIN_DB    = -50.0f;   // 絶対クランプ
static const float THR_MAX_DB    = -25.0f;

static float    s_floorDb;
static uint8_t  s_baseMargin;
static int8_t   s_delta;          // ガバナによる margin 補正 (-3 .. +12)
static int      s_onset;
static bool     s_speech;
static uint32_t s_silenceMs;
static bool     s_clamped;
static bool     s_warn;

// 直近600秒の 1秒バケット（採用フレーム数 / 総フレーム数）
static uint8_t  s_bucket[WIN_SEC];
static uint16_t s_bucketIdx;
static uint16_t s_bucketFill;
static uint32_t s_sumSpeech;
static int      s_frameInSec;
static int      s_speechInSec;
static int      s_secSinceAdjust;
static int      s_secAtMax;

void vadBegin() {
  s_floorDb    = -60.0f;
  s_baseMargin = g_cfg.vadMargin;
  s_delta      = 0;
  s_onset      = 0;
  s_speech     = false;
  s_silenceMs  = 0;
  s_clamped    = false;
  s_warn       = false;
  memset(s_bucket, 0, sizeof(s_bucket));
  s_bucketIdx = 0; s_bucketFill = 0; s_sumSpeech = 0;
  s_frameInSec = 0; s_speechInSec = 0; s_secSinceAdjust = 0; s_secAtMax = 0;
}

uint8_t vadMarginDb() {
  int m = (int)s_baseMargin + s_delta;
  int hi = (int)s_baseMargin + 12;
  if (m < 6)  m = 6;
  if (m > hi) m = hi;
  return (uint8_t)m;
}

float vadFloorDb()      { return s_floorDb; }
bool  vadIsSpeech()     { return s_speech; }
uint32_t vadSilenceMs() { return s_silenceMs; }
bool  vadClamped()      { return s_clamped; }

float vadDutyCapture() {
  uint32_t total = (uint32_t)s_bucketFill * FRAMES_PER_SEC;
  if (total == 0) return 0.0f;
  return (float)s_sumSpeech / (float)total;
}

bool vadTakeWarn() { bool w = s_warn; s_warn = false; return w; }

// 1秒ぶんのフレームを積んだところで窓を1つ進め、ガバナを回す
static void advanceSecond() {
  if (s_bucketFill == WIN_SEC) s_sumSpeech -= s_bucket[s_bucketIdx];
  else                          s_bucketFill++;
  s_bucket[s_bucketIdx] = (uint8_t)s_speechInSec;
  s_sumSpeech += (uint32_t)s_speechInSec;
  s_bucketIdx = (uint16_t)((s_bucketIdx + 1) % WIN_SEC);
  s_speechInSec = 0;

  float d = vadDutyCapture();

  // ハードクランプ（既定 無効。cfg.vad_hardclamp=1 のときのみ）
  if (g_cfg.vadHardclamp) {
    if (!s_clamped && d > 0.50f)      s_clamped = true;
    else if (s_clamped && d < 0.50f)  s_clamped = false;
  } else {
    s_clamped = false;
  }

  s_secSinceAdjust++;
  if (s_secSinceAdjust >= 30 && s_bucketFill >= 60) {   // 最低1分ぶん貯まってから
    s_secSinceAdjust = 0;
    if      (d > 0.35f && s_delta < 12) s_delta++;
    else if (d < 0.15f && s_delta > -3) s_delta--;
  }
  // margin が上限に10分張り付いたら WARN（常時騒音下 or マイク開口が塞がっている）
  if (s_delta >= 12) { if (++s_secAtMax >= 600) { s_warn = true; s_secAtMax = 0; } }
  else                 s_secAtMax = 0;
}

bool vadFeedFrame(const int16_t *frame, size_t n) {
  if (n == 0) return s_speech;

  uint32_t acc = 0;
  for (size_t i = 0; i < n; i++) { int v = frame[i]; acc += (uint32_t)(v < 0 ? -v : v); }
  float meanAbs = (float)acc / (float)n;
  float db = 20.0f * log10f((meanAbs < 1.0f ? 1.0f : meanAbs) / 32768.0f);

  // 非対称IIR: 下降 α=0.05（静かになったら素早く追従）/ 上昇 α=0.0005
  float a = (db < s_floorDb) ? 0.05f : 0.0005f;
  s_floorDb += a * (db - s_floorDb);

  float thr = s_floorDb + (float)vadMarginDb();
  if (thr < THR_MIN_DB) thr = THR_MIN_DB;
  if (thr > THR_MAX_DB) thr = THR_MAX_DB;

  bool over = (db > thr) && !s_clamped;

  if (s_speech) {
    if (over) { s_silenceMs = 0; }
    else {
      s_silenceMs += 20;
      if (s_silenceMs >= g_cfg.vadHang) { s_speech = false; s_onset = 0; }
    }
  } else {
    if (over) {
      if (++s_onset >= ONSET_FRAMES) { s_speech = true; s_silenceMs = 0; }
      else                            s_silenceMs += 20;
    } else {
      s_onset = 0;
      s_silenceMs += 20;
    }
  }

  if (s_speech) s_speechInSec++;
  if (++s_frameInSec >= FRAMES_PER_SEC) { s_frameInSec = 0; advanceSecond(); }
  return s_speech;
}
