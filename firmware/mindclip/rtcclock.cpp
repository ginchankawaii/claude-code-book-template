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

static const time_t EPOCH_SANE = 1600000000L;    // これ未満のシステム時刻は「時計を失っている」

// ---------------------------------------------------------------------------
// 時刻基準の区間表（SPEC §3.4。UNSYNC ファイルの Age-Ms 算出用）
//
// UNSYNC ファイルの mtime は「録音した時点の未同期クロック」で刻まれている。サーバ時刻で
// 時計を合わせた後や、電池切れで時計を失った後は、今の時計と基準が違うので単純に
// 引き算できない（引くと「電池が切れていた時間」がそのまま経過時間に乗る）。
// そこで「どの起動番号がどの基準で動いていたか」と「その基準→真の時刻の差」を NVS に残す。
// RAM や RTC メモリに置かないのは、持ち越したファイルを送るのが deep sleep や電池切れを
// またいだ後のセッションになるからである。
// ---------------------------------------------------------------------------
static void segAppend(uint32_t firstBoot, bool known, int64_t offSec) {
  int n = g_cfg.clkSegN;
  // 同期時に予告しておいた「次の起動からの区間」は、実際の起動が来たらそれで置き換える
  while (n > 0 && g_cfg.clkSeg[n - 1].firstBoot >= firstBoot) n--;
  if (n == CLK_SEG_MAX) {              // 最古を捨てる。該当ファイルは Age-Ms 無しで送られる
    memmove(&g_cfg.clkSeg[0], &g_cfg.clkSeg[1], sizeof(ClockSeg) * (CLK_SEG_MAX - 1));
    n--;
  }
  g_cfg.clkSeg[n].offSec    = offSec;
  g_cfg.clkSeg[n].firstBoot = firstBoot;
  g_cfg.clkSeg[n].known     = known ? 1 : 0;
  g_cfg.clkSegN = (uint8_t)(n + 1);
}

void clockBegin() {
  if (s_magic != RTC_MAGIC) {          // deep sleep 復帰以外のすべての起動（電池切れ・リセット）
    s_magic     = RTC_MAGIC;
    s_valid     = 0;
    s_tzMin     = 0;
    s_unsyncSeq = 0;
    s_bootId    = settingsBumpBootCount() & 0x0FFF;   // 4桁に収める
    // システム時刻はソフトリセットやブラウンアウトでは進み続け、電源断でだけ失われる。
    // 失われたときだけ新しい基準が始まる（残っていれば前の起動と同じ区間のまま）。
    if (time(nullptr) < EPOCH_SANE || g_cfg.clkSegN == 0) {
      segAppend(g_cfg.bootCount, false, 0);
      settingsPutClockSegs();
    }
  }
  // RTC未同期でも「前回同期した時刻」をシステムクロックに入れておく。
  // これをやらないと FatFs の get_fattime() が 1980 にクランプされ、
  // ファイルの mtime と time(nullptr)（起動からの秒数）が比較不能になり、
  // UNSYNC ファイルの X-MindClip-Age-Ms が一度も送られなくなる（E9）。
  if (!s_valid && g_cfg.lastEpoch > 1600000000ULL && time(nullptr) < EPOCH_SANE) {
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
  if (!s_valid) {
    // 時計を書き換える**前に**、いままでの未同期基準と真の時刻の差を確定させる。
    // 以後の起動は（次に時計を失うまで）真の時刻で動くので、差 0 の区間を予告しておく。
    if (g_cfg.clkSegN == 0) segAppend(g_cfg.bootCount, false, 0);   // erase 直後など
    ClockSeg &cur = g_cfg.clkSeg[g_cfg.clkSegN - 1];
    cur.offSec = (int64_t)serverEpoch - (int64_t)time(nullptr);
    cur.known  = 1;
    segAppend(g_cfg.bootCount + 1, true, 0);
    settingsPutClockSegs();
  }
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

bool clockUnsyncAgeMs(const String &name, time_t fileMtime, uint64_t *ageMsOut) {
  // 1980クランプされた mtime（FatFsの既定）は比較の意味が無いので採用しない
  if (fileMtime < 1000000000L) return false;
  if (!name.startsWith("UNSYNC-") || name.length() < 11) return false;

  // 名前の <boot> は st.boot_count の下位12bit。現在値以下でいちばん近い起動番号に戻す。
  // 負になる（NVS を erase した後に残っていた古いファイル等）なら該当区間なし。
  int64_t cur  = (int64_t)g_cfg.bootCount;
  int64_t boot = cur - ((cur - (int64_t)name.substring(7, 11).toInt()) & 0x0FFF);
  int idx = -1;
  for (int i = 0; i < g_cfg.clkSegN; i++) {
    if ((int64_t)g_cfg.clkSeg[i].firstBoot <= boot) idx = i;
  }
  if (idx < 0) return false;

  int64_t mtime = (int64_t)fileMtime;
  if (!s_valid) {
    // 時計がまだ未同期。同じ基準（＝最新の区間）で刻まれた mtime とだけ差を取れる
    if (idx != g_cfg.clkSegN - 1) return false;
  } else {
    if (!g_cfg.clkSeg[idx].known) return false;   // 同期できないまま終わった基準。復元不能
    mtime += g_cfg.clkSeg[idx].offSec;
  }
  int64_t ageSec = (int64_t)time(nullptr) - mtime;
  if (ageSec < 0 || ageSec > 7LL * 24 * 3600) return false;   // 異常値はヘッダを付けない
  *ageMsOut = (uint64_t)ageSec * 1000ULL;
  return true;
}
