// provision.cpp — シリアルCLIの実装。詳細は provision.h を参照。
#include "provision.h"
#include "settings.h"
#include "led.h"
#include "syncer.h"
#include <WiFi.h>
#include <bootloader_random.h>

static String readLineBlocking() {
  String line;
  for (;;) {
    ledTick();
    while (Serial.available()) {
      char c = (char)Serial.read();
      if (c == '\r') continue;
      if (c == '\n') { return line; }
      if (c == 8 || c == 127) { if (line.length()) line.remove(line.length() - 1); continue; }
      if (line.length() < 4200) line += c;
    }
    delay(5);
  }
}

bool provisionShouldEnter(uint32_t windowMs) {
  uint32_t t0 = millis();
  while (millis() - t0 < windowMs) {
    ledTick();
    if (Serial.available()) { while (Serial.available()) Serial.read(); return true; }
    delay(10);
  }
  return false;
}

static void printHelp() {
  Serial.println(F(
    "MindClip provisioning CLI\n"
    "  help                       このヘルプ\n"
    "  show                       設定を表示（秘密は伏字）\n"
    "  set <key> <value>          wifi.ssid / wifi.pass / srv.url / dev.id / cfg.*\n"
    "  set hmac.key <64桁hex>      サーバ側で生成した共有秘密を取り込む\n"
    "  paste <key>                srv.ca / dev.crt / dev.key に PEM を貼る\n"
    "                             （貼り終えたら \".\" だけの行を送る）\n"
    "  gen hmac                   32バイトの共有秘密を生成し hex を1回だけ表示\n"
    "                             （サーバ側で生成する場合は set hmac.key を使う）\n"
    "  test wifi                  WiFi接続だけ試す（RSSI表示）\n"
    "  test server                GET /api/v1/time を実行（TLS/HMACの確認）\n"
    "  save                       NVSへ反映（set/paste は即時保存済み。再読込を行う）\n"
    "  erase                      全消去（工場出荷状態）\n"
    "  reboot                     再起動"));
}

// PEM 貼り付け: "." だけの行で終了
static void doPaste(const String &key) {
  if (key != "srv.ca" && key != "dev.crt" && key != "dev.key") {
    Serial.println(F("ERR: paste は srv.ca / dev.crt / dev.key のみ"));
    return;
  }
  Serial.printf("PEM を貼り付けてください。最後に \".\" だけの行で終了します (%s)\n", key.c_str());
  String pem;
  for (;;) {
    String l = readLineBlocking();
    if (l == ".") break;
    pem += l;
    pem += "\n";
    if (pem.length() > 4000) { Serial.println(F("ERR: 4000バイトを超えました。中止")); return; }
  }
  if (pem.indexOf("-----BEGIN") < 0) { Serial.println(F("ERR: PEM に見えません（-----BEGIN が無い）")); return; }
  if (settingsSetBlob(key, (const uint8_t *)pem.c_str(), pem.length())) {
    Serial.printf("OK: %s に %u バイト保存\n", key.c_str(), (unsigned)pem.length());
    settingsLoad();
  } else {
    Serial.println(F("ERR: NVS書込に失敗"));
  }
}

static void doGenHmac() {
  uint8_t k[32];
  // esp_random() は WiFi/BT が動いていないと真の乱数にならない（esp_random.h の注意書き）。
  // プロビジョニング中は無線を落としてあるので、エントロピー源を明示的に立ち上げる。
  bootloader_random_enable();
  esp_fill_random(k, sizeof(k));
  bootloader_random_disable();
  if (!settingsSetBlob("hmac.key", k, 32)) { Serial.println(F("ERR: NVS書込に失敗")); return; }
  Serial.print(F("hmac.key = "));
  for (int i = 0; i < 32; i++) Serial.printf("%02x", k[i]);
  Serial.println();
  Serial.println(F("↑ この値をサーバの設定にコピーしてください（二度と表示しません）"));
  settingsLoad();
}

static void doTestWifi() {
  if (g_cfg.wifiSsid.length() == 0) { Serial.println(F("ERR: wifi.ssid が未設定")); return; }
  WiFi.persistent(false);
  WiFi.mode(WIFI_STA);
  WiFi.begin(g_cfg.wifiSsid.c_str(), g_cfg.wifiPass.c_str());
  Serial.printf("connecting to %s ...\n", g_cfg.wifiSsid.c_str());
  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < (uint32_t)g_cfg.wifiToS * 1000) { ledTick(); delay(100); }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("OK: ip=%s rssi=%d dBm (%lu ms)\n",
                  WiFi.localIP().toString().c_str(), WiFi.RSSI(), (unsigned long)(millis() - t0));
  } else {
    Serial.println(F("NG: 接続できません（SSID/パスフレーズ/2.4GHz帯かを確認）"));
  }
  WiFi.disconnect(true);
  WiFi.mode(WIFI_OFF);
}

static void doTestServer() {
  if (!g_cfg.srvUrl.startsWith("https://")) { Serial.println(F("ERR: srv.url は https:// で始める必要があります")); return; }
  if (!g_cfg.hmacSet) { Serial.println(F("ERR: hmac.key が未設定（gen hmac を実行）")); return; }
  Serial.println(F("GET /api/v1/time ..."));
  SyncResult r = syncRun(nullptr);     // ファイルが無ければ /time だけ実行される
  Serial.printf("result=%s sent=%d carry=%d\n", syncResultName(r), syncSentCount(), syncCarryCount());
  if (r == SYNC_OK || r == SYNC_CARRY_OVER) {
    time_t lt = time(nullptr);
    Serial.printf("OK: TLS/HMAC 検証成功。server epoch=%lld\n", (long long)lt);
  }
}

void provisionRun() {
  ledSetPattern(LEDP_PROVISION);
  Serial.println();
  Serial.println(F("=== MindClip provisioning mode ==="));
  printHelp();
  for (;;) {
    Serial.print(F("mindclip> "));
    String line = readLineBlocking();
    line.trim();
    Serial.println(line);
    if (line.length() == 0) continue;

    int sp1 = line.indexOf(' ');
    String cmd = (sp1 < 0) ? line : line.substring(0, sp1);
    String rest = (sp1 < 0) ? String() : line.substring(sp1 + 1);
    rest.trim();

    if (cmd == "help")        { printHelp(); }
    else if (cmd == "show")   { settingsDump(Serial); }
    else if (cmd == "set") {
      int sp2 = rest.indexOf(' ');
      if (sp2 < 0) { Serial.println(F("ERR: set <key> <value>")); continue; }
      String k = rest.substring(0, sp2), v = rest.substring(sp2 + 1);
      v.trim();
      if (settingsSetString(k, v)) { settingsLoad(); Serial.printf("OK: %s\n", k.c_str()); }
      else                          Serial.println(F("ERR: 未知のキー、または書込失敗"));
    }
    else if (cmd == "paste")  { doPaste(rest); }
    else if (cmd == "gen")    { if (rest == "hmac") doGenHmac(); else Serial.println(F("ERR: gen hmac")); }
    else if (cmd == "test")   { if (rest == "wifi") doTestWifi(); else if (rest == "server") doTestServer();
                                else Serial.println(F("ERR: test wifi | test server")); }
    else if (cmd == "save")   { settingsCommit(); Serial.println(F("OK: saved")); }
    else if (cmd == "erase")  { settingsEraseAll(); settingsLoad(); Serial.println(F("OK: erased")); }
    else if (cmd == "reboot") { Serial.println(F("rebooting...")); Serial.flush(); delay(200); ESP.restart(); }
    else                      { Serial.println(F("ERR: 未知のコマンド。help を参照")); }
  }
}
