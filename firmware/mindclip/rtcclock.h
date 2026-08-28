// =============================================================================
// rtcclock.h — 時刻の保持とファイル名生成（SPEC §3.3 / §3.4）
//
// ・NTPは実装しない。時刻はサーバ GET /api/v1/time からのみ受け取る。
// ・valid フラグと boot_count は RTC_DATA_ATTR に置き、deep sleep をまたいで保持する。
// ・ファイル名は「ローカル時刻」で付ける（Phase0 の Daily Note がローカル日付で切られるため）。
//   RTC未同期のときは UNSYNC-<boot4>-<seq3>.wav（timeparse が日時と誤解釈しない形）。
// =============================================================================
#pragma once
#include "config.h"

void     clockBegin();                     // RTCメモリの整合確認（BOOTで1回）
bool     clockValid();
int32_t  clockTzOffsetMin();
void     clockSetFromServer(uint64_t serverEpoch, int32_t tzOffsetMin);
time_t   clockLocalNow();                  // ローカル時刻の epoch 相当
uint32_t clockBootId();                    // UNSYNC名の <boot>

// 録音開始時のファイル名（拡張子なしのステム）を out に書く。戻り値はUNSYNC名かどうか。
bool     clockMakeStem(char *out, size_t outLen);

// 同期セッション開始時に、settimeofday() を呼ぶ**前に**呼んで基準を保存する。
void     clockMarkPreSync();
// UNSYNC ファイルの経過msを推定する。負や7日超なら false（＝ヘッダを付けない）。
bool     clockUnsyncAgeMs(time_t fileMtime, uint64_t *ageMsOut);
