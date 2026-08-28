// =============================================================================
// syncer.h — WiFi同期（SPEC §6）
//
// スイッチOFFで一度だけ走る。WiFi接続(30s) → GET /api/v1/time で時刻を受け取り →
// /rec の .wav を古い順に POST /api/v1/ingest → 200かつsha256一致でのみSDから削除 →
// deep sleep。TLSは1本を keep-alive で使い回す。認証は mTLS ＋ 共有秘密HMAC の二重。
// NTPは使わない。認証情報はすべてNVS（g_cfg）から読む。
// =============================================================================
#pragma once
#include "config.h"

enum SyncResult {
  SYNC_OK = 0,          // 全件送信 or 送るものが無かった
  SYNC_NOT_PROVISIONED, // E11: NVS未設定
  SYNC_NO_WIFI,         // E4: 30秒で繋がらない
  SYNC_AUTH_FAIL,       // E6: 401/403
  SYNC_SERVER_FAIL,     // E5: 5xx/タイムアウト/507
  SYNC_CARRY_OVER,      // 一部持越し（リトライ上限・セッション15分超過）
  SYNC_ABORT_SWITCH,    // E8: 同期中にスイッチON
  SYNC_SD_FAIL          // /rec を開けない（送信対象の有無すら確認できない）
};

// abortCb: ファイル境界ごとに呼ばれ、true を返すと中断して SYNC_ABORT_SWITCH を返す。
SyncResult syncRun(bool (*abortCb)());
const char *syncResultName(SyncResult r);
int  syncSentCount();
int  syncCarryCount();
