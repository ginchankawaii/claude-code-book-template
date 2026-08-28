// rtcclock.cpp — 時刻保持とファイル名生成。詳細は rtcclock.h を参照。
#include "rtcclock.h"
#include "settings.h"
#include <sys/time.h>

static const uint32_t RTC_MAGIC = 0x4D43C10Bu;   // 'MC' + clock

// deep sleep をまたいで保持される領域（ESP32-S3 の RTC タイマは sleep 中も動く）
RTC_DATA_ATTR static uint32_t s_magic     = 0;
RTC_DATA_ATTR static uint8_t  s_valid     = 0;
RTC_DATA_ATTR static int32_t  s_tzMin     = 0;
RTC_DATA_ATTR static uint32_t s_bootId    = 0;
RTC_DATA_ATTR static uint16_t s_unsyncSeq = 0;

// 同期セッション開始時に保存する「未同期クロック」の基準（§3.3 のAge-Ms算出用）
static time_t   s_preSyncTime  = 0;
static uint32_t s_preSyncMs    = 0;
static bool     s_preSyncTaken = false;

void clockBegin() {
  if (s_magic != RTC_MAGIC) {          // 電池が完全に切れた／初回書込
    s_magic     = RTC_MAGIC;
    s_valid     = 0;
    s_tzMin     = 0;
    s_unsyncSeq = 0;
    s_bootId    = settingsBumpBootCount() & 0x0FFF;   // 4桁に収める
  }
  // RTC未同期でも「前回同期した時刻」をシステムクロックに入れておく。
  // これをやらないと FatFs の get_fattime() が 1980 にクランプされ、
  // ファイルの mtime と time(nullptr)（起動からの秒数）が比較不能になり、
  // UNSYNC ファイルの X-MindClip-Age-Ms が一度も送られなくなる（E9）。
  if (!s_valid && g_cfg.lastEpoch > 1600000000ULL && time(nullptr) < 1600000000L) {
    struct timeval tv;
    tv.tv_sec  = (time_t)g_cfg.lastEpoch;
    tv.tv_usec = 0;
    settimeofday(&tv, nullptr);      // valid=false のまま。ファイル名は UNSYNC- を使い続ける
  }
}

bool    clockValid()        { return s_valid != 0; }
int32_t clockTzOffsetMin()  { return s_tzMin; }
uint32_t clockBootId()      { return s_bootId; }

void clockSetFromServer(uint64_t serverEpoch, int32_t tzOffsetMin) {
  struct timeval tv;
  tv.tv_sec  = (time_t)serverEpoch;
  tv.tv_usec = 0;
  settimeofday(&tv, nullptr);
  s_tzMin = tzOffsetMin;
  s_valid = 1;
  settingsPutEpoch(serverEpoch);
}

time_t clockLocalNow() {
  time_t utc = time(nullptr);
  return utc + (time_t)s_tzMin * 60;
}

bool clockMakeStem(char *out, size_t outLen) {
  if (!clockValid()) {
    if (s_unsyncSeq >= 999) s_unsyncSeq = 0;
    s_unsyncSeq++;
    snprintf(out, outLen, "UNSYNC-%04u-%03u", (unsigned)(s_bootId % 10000), (unsigned)s_unsyncSeq);
    return true;
  }
  time_t lt = clockLocalNow();
  struct tm tmv;
  gmtime_r(&lt, &tmv);               // lt は既にローカルへずらしてあるので gmtime で整形する
  snprintf(out, outLen, "%04d%02d%02d_%02d%02d%02d",
           tmv.tm_year + 1900, tmv.tm_mon + 1, tmv.tm_mday,
           tmv.tm_hour, tmv.tm_min, tmv.tm_sec);
  return false;
}

void clockMarkPreSync() {
  s_preSyncTime  = time(nullptr);
  s_preSyncMs    = millis();
  s_preSyncTaken = true;
}

bool clockUnsyncAgeMs(time_t fileMtime, uint64_t *ageMsOut) {
  // 1980クランプされた mtime（FatFsの既定）は比較の意味が無いので採用しない
  if (!s_preSyncTaken || fileMtime < 1000000000L) return false;
  int64_t nowUnsynced = (int64_t)s_preSyncTime + (int64_t)(millis() - s_preSyncMs) / 1000;
  int64_t ageSec = nowUnsynced - (int64_t)fileMtime;
  if (ageSec < 0 || ageSec > 7LL * 24 * 3600) return false;   // 異常値はヘッダを付けない
  *ageMsOut = (uint64_t)ageSec * 1000ULL;
  return true;
}
