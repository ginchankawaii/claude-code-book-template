// settings.cpp — NVS(Preferences) 実装。詳細は settings.h を参照。
#include "settings.h"
#include <Preferences.h>

Settings g_cfg;

static const char NS[] = "mindclip";

// PEM/鍵は blob として置く（SPEC §10.1）。読み出しは String に載せ替える。
static String readBlobAsString(Preferences &p, const char *key) {
  size_t n = p.getBytesLength(key);
  if (n == 0 || n > 4096) return String();
  String s;
  s.reserve(n + 1);
  char *tmp = (char *)malloc(n + 1);
  if (!tmp) return String();
  p.getBytes(key, tmp, n);
  tmp[n] = 0;
  s = String(tmp);
  free(tmp);
  return s;
}

static int hexVal(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  return -1;
}

template <typename T>
static T clampv(T v, T lo, T hi) { return v < lo ? lo : (v > hi ? hi : v); }

void settingsLoad() {
  Preferences p;
  if (!p.begin(NS, true)) {   // 読み取り専用。無ければ既定値のまま
    g_cfg.ledDuty = 15; g_cfg.splitSec = 600; g_cfg.gapSec = 3; g_cfg.bufSec = 60;
    g_cfg.vadMargin = 9; g_cfg.vadHang = 800; g_cfg.vadHardclamp = 0; g_cfg.wifiToS = 30;
    g_cfg.devId = "mindclip-01"; g_cfg.hmacSet = false;
    return;
  }
  g_cfg.wifiSsid = p.getString("wifi.ssid", "");
  g_cfg.wifiPass = p.getString("wifi.pass", "");
  g_cfg.srvUrl   = p.getString("srv.url", "");
  g_cfg.devId    = p.getString("dev.id", "mindclip-01");
  g_cfg.caPem    = readBlobAsString(p, "srv.ca");
  g_cfg.devCrt   = readBlobAsString(p, "dev.crt");
  g_cfg.devKey   = readBlobAsString(p, "dev.key");

  memset(g_cfg.hmacKey, 0, sizeof(g_cfg.hmacKey));
  g_cfg.hmacSet = (p.getBytesLength("hmac.key") == 32);
  if (g_cfg.hmacSet) p.getBytes("hmac.key", g_cfg.hmacKey, 32);

  g_cfg.ledDuty      = clampv<uint8_t>(p.getUChar("cfg.led_duty", 15), 10, 20);
  g_cfg.splitSec     = clampv<uint16_t>(p.getUShort("cfg.split_sec", 600), 30, 600);
  g_cfg.gapSec       = clampv<uint8_t>(p.getUChar("cfg.gap_sec", 3), 1, 30);
  g_cfg.bufSec       = clampv<uint8_t>(p.getUChar("cfg.buf_sec", 60), 30, 60);
  g_cfg.vadMargin    = clampv<uint8_t>(p.getUChar("cfg.vad_margin", 9), 3, 24);
  g_cfg.vadHang      = clampv<uint16_t>(p.getUShort("cfg.vad_hang", 800), 100, 5000);
  g_cfg.vadHardclamp = p.getUChar("cfg.vad_clamp", 0) ? 1 : 0;
  g_cfg.wifiToS      = clampv<uint8_t>(p.getUChar("cfg.wifi_to_s", 30), 5, 120);

  g_cfg.lastEpoch = p.getULong64("clk.last_epoch", 0);
  g_cfg.bootCount = p.getULong("st.boot_count", 0);
  p.end();
}

// "set <key> <value>" 用。cfg.* は数値、その他は文字列。
bool settingsSetString(const String &key, const String &val) {
  Preferences p;
  if (!p.begin(NS, false)) return false;
  bool ok = true;
  if (key == "hmac.key") {
    // 64桁hex。サーバ側で生成した鍵をデバイスへ入れる唯一の経路（gen hmac の代替）
    String h = val; h.trim(); h.toLowerCase();
    if (h.length() != 64) { p.end(); return false; }
    uint8_t k[32];
    for (int i = 0; i < 32; i++) {
      int hi = hexVal(h[i * 2]), lo = hexVal(h[i * 2 + 1]);
      if (hi < 0 || lo < 0) { p.end(); return false; }
      k[i] = (uint8_t)((hi << 4) | lo);
    }
    ok = p.putBytes("hmac.key", k, 32) == 32;
  } else if (key == "wifi.ssid" || key == "wifi.pass" || key == "srv.url" || key == "dev.id") {
    String v = val;
    if (key == "srv.url") {
      // 末尾スラッシュが残ると実リクエストが //api/v1/ingest になり 404 を食らう
      while (v.length() && v.charAt(v.length() - 1) == '/') v.remove(v.length() - 1);
    }
    ok = p.putString(key.c_str(), v) > 0 || v.length() == 0;
  } else if (key.startsWith("cfg.")) {
    long v = val.toInt();
    if (key == "cfg.split_sec" || key == "cfg.vad_hang") ok = p.putUShort(key.c_str(), (uint16_t)v) > 0;
    else                                                 ok = p.putUChar(key.c_str(), (uint8_t)v) > 0;
  } else {
    ok = false;
  }
  p.end();
  return ok;
}

bool settingsSetBlob(const String &key, const uint8_t *data, size_t len) {
  if (len == 0 || len > 4096) return false;
  Preferences p;
  if (!p.begin(NS, false)) return false;
  bool ok = p.putBytes(key.c_str(), data, len) == len;
  p.end();
  return ok;
}

bool settingsCommit() {
  // Preferences は put の時点でコミットされる。ここでは読み直して整合を取る。
  settingsLoad();
  return true;
}

void settingsEraseAll() {
  Preferences p;
  if (p.begin(NS, false)) { p.clear(); p.end(); }
}

void settingsPutEpoch(uint64_t epoch) {
  Preferences p;
  if (!p.begin(NS, false)) return;
  p.putULong64("clk.last_epoch", epoch);
  p.end();
  g_cfg.lastEpoch = epoch;
}

uint32_t settingsBumpBootCount() {
  Preferences p;
  if (!p.begin(NS, false)) return g_cfg.bootCount;
  uint32_t n = p.getULong("st.boot_count", 0) + 1;
  p.putULong("st.boot_count", n);
  p.end();
  g_cfg.bootCount = n;
  return n;
}

String settingsMask(const String &secret) {
  if (secret.length() == 0) return String("(unset)");
  if (secret.length() <= 4) return String("****");
  return String("****") + secret.substring(secret.length() - 4);
}

bool settingsIsProvisioned() {
  // TLS素材まで見る。見ないと「設定不備(E11=5回点滅)」が「サーバ応答なし(E5=2回点滅)」に
  // 化けて、現地で最も切り分けづらい項目が最も紛らわしい表示になる。
  return g_cfg.wifiSsid.length() > 0 && g_cfg.srvUrl.startsWith("https://")
         && g_cfg.caPem.length() > 0 && g_cfg.devCrt.length() > 0 && g_cfg.devKey.length() > 0;
}

void settingsDump(Stream &out) {
  out.printf("wifi.ssid        = %s\n", g_cfg.wifiSsid.length() ? g_cfg.wifiSsid.c_str() : "(unset)");
  out.printf("wifi.pass        = %s\n", settingsMask(g_cfg.wifiPass).c_str());
  out.printf("srv.url          = %s\n", g_cfg.srvUrl.length() ? g_cfg.srvUrl.c_str() : "(unset)");
  out.printf("dev.id           = %s\n", g_cfg.devId.c_str());
  out.printf("srv.ca           = %u bytes\n", (unsigned)g_cfg.caPem.length());
  out.printf("dev.crt          = %u bytes\n", (unsigned)g_cfg.devCrt.length());
  out.printf("dev.key          = %s (%u bytes)\n", g_cfg.devKey.length() ? "****" : "(unset)",
             (unsigned)g_cfg.devKey.length());
  out.printf("hmac.key         = %s\n", g_cfg.hmacSet ? "**** (32 bytes)" : "(unset)");
  out.printf("cfg.led_duty     = %u %%\n", g_cfg.ledDuty);
  out.printf("cfg.split_sec    = %u\n", g_cfg.splitSec);
  out.printf("cfg.gap_sec      = %u\n", g_cfg.gapSec);
  out.printf("cfg.buf_sec      = %u\n", g_cfg.bufSec);
  out.printf("cfg.vad_margin   = %u dB\n", g_cfg.vadMargin);
  out.printf("cfg.vad_hang     = %u ms\n", g_cfg.vadHang);
  out.printf("cfg.vad_clamp    = %u\n", g_cfg.vadHardclamp);
  out.printf("cfg.wifi_to_s    = %u\n", g_cfg.wifiToS);
  out.printf("clk.last_epoch   = %llu\n", (unsigned long long)g_cfg.lastEpoch);
  out.printf("st.boot_count    = %lu\n", (unsigned long)g_cfg.bootCount);
}
