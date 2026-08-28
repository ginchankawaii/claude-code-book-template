// =============================================================================
// settings.h — NVS(Preferences) からの設定読み書き
//
// SPEC §10.1 の19項目を扱う。ソースに認証情報を持たないための唯一の入口。
// namespace は "mindclip"。書込は provision.cpp（シリアルCLI）からのみ行う。
// =============================================================================
#pragma once
#include "config.h"

void     settingsLoad();                       // NVS→g_cfg（範囲外はクランプ）
bool     settingsSetString(const String &key, const String &val);
bool     settingsSetBlob(const String &key, const uint8_t *data, size_t len);
bool     settingsCommit();                     // g_cfg の cfg.* を NVS へ書戻し
void     settingsEraseAll();
void     settingsPutEpoch(uint64_t epoch);     // clk.last_epoch
uint32_t settingsBumpBootCount();              // st.boot_count を +1 して返す
String   settingsMask(const String &secret);   // 末尾4文字だけ見せる
bool     settingsIsProvisioned();              // wifi.ssid と srv.url と TLS素材が揃っているか
void     settingsDump(Stream &out);            // show コマンド用
