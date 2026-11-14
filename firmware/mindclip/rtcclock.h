// =============================================================================
// rtcclock.h — 時刻の保持とファイル名生成（SPEC §3.3 / §3.4）
//
// ・NTPは実装しない。時刻はサーバ GET /api/v1/time からのみ受け取る。
// ・valid フラグと boot_count は RTC_DATA_ATTR に置き、deep sleep をまたいで保持する。
//   どちらも deep sleep 復帰以外の起動（電池切れ・リセット）では失われ、boot_count が進む。
// ・起動番号ごとの「時計の基準」は NVS の clk.segs に残す。持ち越した UNSYNC ファイルの
//   経過時間を、時計を合わせた後・電池が切れた後のセッションでも正しく出すため（SPEC §3.4）。
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

// UNSYNC ファイル（name = "UNSYNC-<boot>-<seq>..."）の mtime から「今」までの経過msを出す。
// その起動番号の時刻基準が分からない・負・7日超なら false（＝ヘッダを付けない。
// 誤った経過時間を送るより、サーバに「不明」と伝えるほうが安全。SPEC §3.4）。
bool     clockUnsyncAgeMs(const String &name, time_t fileMtime, uint64_t *ageMsOut);
