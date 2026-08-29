// syncer.cpp — WiFi同期の実装。詳細は syncer.h を参照。
#include "syncer.h"
#include "rtcclock.h"
#include "settings.h"
#include "led.h"
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <SD.h>
#include <mbedtls/md.h>
#include <mbedtls/sha256.h>

static int s_sent = 0, s_carry = 0;
int syncSentCount()  { return s_sent; }
int syncCarryCount() { return s_carry; }

const char *syncResultName(SyncResult r) {
  switch (r) {
    case SYNC_OK:              return "OK";
    case SYNC_NOT_PROVISIONED: return "NOT_PROVISIONED";
    case SYNC_NO_WIFI:         return "NO_WIFI";
    case SYNC_AUTH_FAIL:       return "AUTH_FAIL";
    case SYNC_SERVER_FAIL:     return "SERVER_FAIL";
    case SYNC_CARRY_OVER:      return "CARRY_OVER";
    case SYNC_ABORT_SWITCH:    return "ABORT_SWITCH";
    case SYNC_SD_FAIL:         return "SD_FAIL";
  }
  return "?";
}

// ---------------------------------------------------------------------------
// ハッシュ / HMAC（SPEC §6.1）
// ---------------------------------------------------------------------------
static void toHex(const uint8_t *in, size_t n, char *out) {
  static const char *H = "0123456789abcdef";
  for (size_t i = 0; i < n; i++) { out[i * 2] = H[in[i] >> 4]; out[i * 2 + 1] = H[in[i] & 15]; }
  out[n * 2] = 0;
}

static void sha256Bytes(const uint8_t *p, size_t n, char *hexOut) {
  uint8_t d[32];
  mbedtls_sha256_context c;
  mbedtls_sha256_init(&c);
  mbedtls_sha256_starts(&c, 0);
  mbedtls_sha256_update(&c, p, n);
  mbedtls_sha256_finish(&c, d);
  mbedtls_sha256_free(&c);
  toHex(d, 32, hexOut);
}

// ファイル全体のSHA-256。ストリーミングで読む（RAMに載せない）
static bool sha256File(const char *path, char *hexOut, uint32_t *sizeOut) {
  File f = SD.open(path, FILE_READ);
  if (!f) return false;
  mbedtls_sha256_context c;
  mbedtls_sha256_init(&c);
  mbedtls_sha256_starts(&c, 0);
  static uint8_t buf[2048];
  uint32_t total = 0;
  for (;;) {
    int n = f.read(buf, sizeof(buf));
    if (n <= 0) break;
    mbedtls_sha256_update(&c, buf, (size_t)n);
    total += (uint32_t)n;
  }
  uint8_t d[32];
  mbedtls_sha256_finish(&c, d);
  mbedtls_sha256_free(&c);
  f.close();
  toHex(d, 32, hexOut);
  if (sizeOut) *sizeOut = total;
  return true;
}

// Authorization: MindClip-HMAC dev=<id>,nonce=<32hex>,sig=<64hex>
// msg = "<method>\n<path>\n<device_id>\n<sha256_hex_of_body>\n<nonce_hex>"
// タイムスタンプは使わない（RTC未同期でも成立させるため）。
static String buildAuthHeader(const char *method, const char *path, const char *bodySha) {
  uint8_t nonce[16];
  for (int i = 0; i < 16; i += 4) { uint32_t r = esp_random(); memcpy(nonce + i, &r, 4); }
  char nonceHex[33]; toHex(nonce, 16, nonceHex);

  String msg = String(method) + "\n" + path + "\n" + g_cfg.devId + "\n" + bodySha + "\n" + nonceHex;

  uint8_t sig[32];
  const mbedtls_md_info_t *info = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
  mbedtls_md_context_t ctx;
  mbedtls_md_init(&ctx);
  mbedtls_md_setup(&ctx, info, 1);
  mbedtls_md_hmac_starts(&ctx, g_cfg.hmacKey, sizeof(g_cfg.hmacKey));
  mbedtls_md_hmac_update(&ctx, (const uint8_t *)msg.c_str(), msg.length());
  mbedtls_md_hmac_finish(&ctx, sig);
  mbedtls_md_free(&ctx);

  char sigHex[65]; toHex(sig, 32, sigHex);
  return String("MindClip-HMAC dev=") + g_cfg.devId + ",nonce=" + nonceHex + ",sig=" + sigHex;
}

// ---------------------------------------------------------------------------
// 極小 JSON 取り出し（ArduinoJson に依存しない）
// ---------------------------------------------------------------------------
static bool jsonNumber(const String &s, const char *key, int64_t *out) {
  int i = s.indexOf(String("\"") + key + "\"");
  if (i < 0) return false;
  i = s.indexOf(':', i);
  if (i < 0) return false;
  i++;
  while (i < (int)s.length() && (s[i] == ' ' || s[i] == '"')) i++;
  bool neg = (i < (int)s.length() && s[i] == '-');
  if (neg) i++;
  int64_t v = 0; bool any = false;
  while (i < (int)s.length() && isdigit((int)s[i])) { v = v * 10 + (s[i] - '0'); i++; any = true; }
  if (!any) return false;
  *out = neg ? -v : v;
  return true;
}

static bool jsonString(const String &s, const char *key, String *out) {
  int i = s.indexOf(String("\"") + key + "\"");
  if (i < 0) return false;
  i = s.indexOf(':', i);
  if (i < 0) return false;
  int a = s.indexOf('"', i + 1);
  if (a < 0) return false;
  int b = s.indexOf('"', a + 1);
  if (b < 0) return false;
  *out = s.substring(a + 1, b);
  return true;
}

// ---------------------------------------------------------------------------
// TLS / HTTP
// ---------------------------------------------------------------------------
static WiFiClientSecure s_tls;
// HTTPClient はデストラクタが _reuse に関係なく _client->stop() を呼ぶ。
// 関数ローカルにするとスコープを抜けるたびに mTLS ハンドシェイクをやり直すことになるので、
// セッション中は必ずこの1個を使い回す（SPEC §6.5 の keep-alive 要件）。
static HTTPClient s_http;

static void tlsSetup() {
  if (g_cfg.caPem.length())  s_tls.setCACert(g_cfg.caPem.c_str());
  if (g_cfg.devCrt.length()) s_tls.setCertificate(g_cfg.devCrt.c_str());
  if (g_cfg.devKey.length()) s_tls.setPrivateKey(g_cfg.devKey.c_str());
  s_tls.setHandshakeTimeout(15);
  s_tls.setTimeout(HTTP_IO_MS);      // Stream::setTimeout の単位は ms（秒ではない）
}

static bool wifiConnect() {
  WiFi.persistent(false);
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(true);
  WiFi.begin(g_cfg.wifiSsid.c_str(), g_cfg.wifiPass.c_str());
  uint32_t t0 = millis(), to = (uint32_t)g_cfg.wifiToS * 1000;
  while (WiFi.status() != WL_CONNECTED && (millis() - t0) < to) { ledTick(); delay(50); }
  return WiFi.status() == WL_CONNECTED;
}

static void wifiOff() {
  s_http.setReuse(false);      // keep-alive を解除してから本当に閉じる
  s_http.end();
  s_tls.stop();
  WiFi.disconnect(true);
  WiFi.mode(WIFI_OFF);
}

// GET /api/v1/time（送るファイルが0件でも必ず呼ぶ。RTC補正のため）
static int fetchTime() {
  const char *path = "/api/v1/time";
  char emptySha[65]; sha256Bytes((const uint8_t *)"", 0, emptySha);

  HTTPClient &http = s_http;
  http.setReuse(true);
  http.setConnectTimeout(HTTP_CONNECT_MS);
  http.setTimeout(HTTP_IO_MS);
  if (!http.begin(s_tls, g_cfg.srvUrl + path)) return -1;
  http.addHeader("Authorization", buildAuthHeader("GET", path, emptySha));
  http.addHeader("X-MindClip-Device", g_cfg.devId);
  int code = http.GET();
  if (code == 200) {
    String body = http.getString();
    int64_t epoch = 0, tz = 0;
    if (jsonNumber(body, "server_epoch", &epoch) && epoch > 1600000000LL) {
      if (!jsonNumber(body, "tz_offset_min", &tz)) tz = 0;
      clockSetFromServer((uint64_t)epoch, (int32_t)tz);
    }
  }
  http.end();
  return code;
}

// ローカル失敗の番号。HTTPClient のエラーコード（-1 = CONNECTION_REFUSED,
// -11 = READ_TIMEOUT など）と衝突しない値にする。衝突させると、サーバ障害による
// 通信失敗まで「このファイル固有の問題」と誤判定してセッションを止められなくなる。
static const int LOCALERR_BEGIN = -1001;   // http.begin() 失敗
static const int LOCALERR_OPEN  = -1002;   // SD.open() 失敗

// POST /api/v1/ingest。戻り値: HTTPステータス（負値は通信失敗 or 上のローカル失敗）
static int postFile(const String &path, const String &name, const char *shaHex,
                    uint32_t bytes, uint32_t durMs, bool unsynced, uint64_t ageMs,
                    String *ackSha) {
  const char *apiPath = "/api/v1/ingest";
  File f = SD.open(path.c_str(), FILE_READ);
  if (!f) return LOCALERR_OPEN;

  HTTPClient &http = s_http;
  http.setReuse(true);
  http.setConnectTimeout(HTTP_CONNECT_MS);
  http.setTimeout(HTTP_IO_MS);
  if (!http.begin(s_tls, g_cfg.srvUrl + apiPath)) { f.close(); return LOCALERR_BEGIN; }

  http.addHeader("Content-Type", "audio/wav");
  http.addHeader("Authorization", buildAuthHeader("POST", apiPath, shaHex));
  http.addHeader("X-MindClip-Device", g_cfg.devId);
  http.addHeader("X-MindClip-Filename", name);
  http.addHeader("X-MindClip-Sha256", shaHex);
  http.addHeader("X-MindClip-Bytes", String(bytes));
  http.addHeader("X-MindClip-Duration-Ms", String(durMs));
  http.addHeader("X-MindClip-Unsynced", unsynced ? "1" : "0");
  if (unsynced && ageMs > 0) http.addHeader("X-MindClip-Age-Ms", String((unsigned long long)ageMs));

  const char *collect[] = {"Content-Type"};
  http.collectHeaders(collect, 1);

  int code = http.sendRequest("POST", &f, bytes);
  if (code == 200) {
    String body = http.getString();
    String s;
    if (jsonString(body, "sha256", &s)) *ackSha = s;
    // 時刻は GET /api/v1/time で1回だけ受ける。ここで受けると1同期でファイル数ぶん
    // NVS(settingsPutEpoch) を書くことになるので、応答の server_epoch は使わない。
  }
  http.end();
  f.close();
  return code;
}

// ---------------------------------------------------------------------------
// 1バッチの上限。無音3秒分割で1日300件前後になるため、1バッチで打ち切らず
// ディレクトリが空になるまでスキャンし直す（打ち切ると未送信が毎日積み上がりSDが埋まる）。
static const int MAX_FILES = 64;
static String s_names[MAX_FILES];      // 2KBのスタック消費を避けるため static

// 送信順は古い順。YYYYMMDD_HHMMSS は辞書順＝時系列順。
// UNSYNC-* は「時刻を持たない過去のもの」なので先に送る。
// 戻り値: 件数。**-1 は「/rec を開けなかった」**（0件と区別する。区別しないと
// FAULT_SD で SD が落ちているときに「全件送信完了」扱いで無警告に寝てしまう）。
static int listFiles(String *names, int cap) {
  File dir = SD.open(REC_DIR);
  if (!dir) return -1;
  int n = 0;
  for (File f = dir.openNextFile(); f && n < cap; f = dir.openNextFile()) {
    String nm = String(f.name());
    f.close();
    if (isSendableName(nm)) names[n++] = nm;      // .wav / .wav.b1 / .wav.b2（.bad と .rec は除く）
  }
  dir.close();
  for (int i = 1; i < n; i++) {          // 挿入ソート（件数は高々128）
    String k = names[i];
    bool kU = k.startsWith("UNSYNC-");
    int j = i - 1;
    while (j >= 0) {
      bool jU = names[j].startsWith("UNSYNC-");
      bool greater = (jU == kU) ? (names[j] > k) : (!jU && kU);
      if (!greater) break;
      names[j + 1] = names[j]; j--;
    }
    names[j + 1] = k;
  }
  return n;
}

// E16（SPEC §6.3）: 「3セッション連続で400」をSD上のファイル名で数える。
// カウンタをNVSに置かないのは、ファイルとカウンタが別媒体だと
// 「削除済みファイルのカウンタが残る／リネームで対応が切れる」不整合が起きるため。
// 200を得て削除された時点でカウントはファイルごと自然に消える。
static void markBad400(const String &full) {
  int wp = full.lastIndexOf(EXT_DONE);
  if (wp < 0) return;
  String base = full.substring(0, wp);            // 拡張子を除いたパス
  String dst;
  if      (full.endsWith(EXT_BAD1)) dst = base + EXT_BAD2;
  else if (full.endsWith(EXT_BAD2)) dst = base + EXT_BAD;   // 3回目 → 隔離
  else                              dst = base + EXT_BAD1;
  if (SD.rename(full.c_str(), dst.c_str())) mcLogf("[SYNC] E16 400 -> %s", dst.c_str());
  else                                      mcLogf("[SYNC] E16 rename failed: %s", full.c_str());
}

SyncResult syncRun(bool (*abortCb)()) {
  s_sent = 0; s_carry = 0;

  if (!settingsIsProvisioned()) return SYNC_NOT_PROVISIONED;   // E11
  if (!g_cfg.hmacSet) return SYNC_NOT_PROVISIONED;             // 無認証で送らない（要件7）
  if (!g_cfg.srvUrl.startsWith("https://")) return SYNC_NOT_PROVISIONED;

  clockMarkPreSync();          // settimeofday する前に「未同期クロック」の基準を取る
  if (!wifiConnect()) { wifiOff(); return SYNC_NO_WIFI; }      // E4: リトライしない
  tlsSetup();

  uint32_t sess0 = millis();
  // /time もファイル送信と同じ 0/1s/3s の3回リトライを掛ける。
  // WiFi接続直後の最初のTLSリクエストは、APのDHCP/ARP収束やサーバのコールドスタートで
  // 一過性に落ちやすい。ここを1発勝負にすると、その一度の失敗で**その夜の同期が
  // まるごと持ち越し**になり、日記が丸1日遅れる（データは失われないが価値が落ちる）。
  int tcode = 0;
  for (int attempt = 0; attempt < FILE_RETRY_MAX; attempt++) {
    delay(RETRY_BACKOFF_MS[attempt]);
    tcode = fetchTime();
    if (tcode == 200 || tcode == 401 || tcode == 403) break;  // 成功／認証不正は再試行しない
  }
  if (tcode == 401 || tcode == 403) { wifiOff(); return SYNC_AUTH_FAIL; }   // E6
  if (tcode != 200)                 { wifiOff(); return SYNC_SERVER_FAIL; } // E5

  SyncResult res = SYNC_OK;

  // バッチを回し切ったら listFiles をやり直す。1バッチで1件も削除できなかったら終了
  // （＝残りは全部持越し）。これで打ち切りによる恒久的な滞留が起きない。
  for (;;) {
    int n = listFiles(s_names, MAX_FILES);
    if (n < 0) { wifiOff(); return SYNC_SD_FAIL; }   // /rec が読めない。黙って寝ない
    if (n == 0) break;
    int deleted = 0;
    bool stop = false;

    for (int i = 0; i < n && !stop; i++) {
      if (abortCb && abortCb()) { res = SYNC_ABORT_SWITCH; stop = true; break; }        // E8
      if (millis() - sess0 > SESSION_MAX_MS) { res = SYNC_CARRY_OVER; stop = true; break; }

      String full = String(REC_DIR) + "/" + s_names[i];
      char shaHex[65];
      uint32_t bytes = 0;
      if (!sha256File(full.c_str(), shaHex, &bytes) || bytes < 45) { s_carry++; continue; }

      uint32_t durMs = (bytes > 44) ? (uint32_t)(((uint64_t)(bytes - 44) * 1000ULL) / AUDIO_BYTES_SEC) : 0;
      bool unsynced = s_names[i].startsWith("UNSYNC-");
      uint64_t ageMs = 0;
      if (unsynced) {
        File f = SD.open(full.c_str(), FILE_READ);
        time_t mt = f ? f.getLastWrite() : 0;
        if (f) f.close();
        if (!clockUnsyncAgeMs(mt, &ageMs)) {
          ageMs = 0;                                    // 不明ならヘッダを付けない
        } else {
          // FAT の mtime は最後の f_sync/close の時刻＝**録音の終了時刻**。
          // SPEC §6.3 の Age-Ms は「**録音開始**から今までの経過ms」なので、
          // 録音長を足して開始時刻基準に直す。これを忘れるとサーバが復元する
          // start がファイル長ぶん（最大 split_sec = 600秒）未来にずれる。
          ageMs += durMs;
        }
      }

      bool done = false;
      int lastCode = 0;
      for (int attempt = 0; attempt < FILE_RETRY_MAX && !done; attempt++) {
        delay(RETRY_BACKOFF_MS[attempt]);   // 0 / 1s / 3s（SPEC §6.3）
        String ackSha;
        int code = postFile(full, s_names[i], shaHex, bytes, durMs, unsynced, ageMs, &ackSha);
        lastCode = code;

        if (code == 200) {
          // SPEC §6.4: 200 かつ sha256 一致のときだけ削除する
          if (ackSha.length() == 64 && ackSha.equalsIgnoreCase(shaHex)) {
            SD.remove(full.c_str());
            s_sent++; deleted++;
          } else {
            s_carry++;    // ACKが読めない/不一致 → 消さずに持越し（次回 duplicate:true で回収）
          }
          done = true;
        } else if (code == 401 || code == 403) {
          wifiOff(); return SYNC_AUTH_FAIL;                       // E6: セッション即中止
        } else if (code == 507) {
          s_carry += (n - i); wifiOff(); return SYNC_SERVER_FAIL;  // サーバのディスク不足
        } else if (code == 413) {
          s_carry++; done = true;                                  // 持越し＋WARN
        } else {
          continue;                                                // 400 / 5xx / タイムアウト
        }
      }
      if (!done) {
        // 400 は「このファイル固有の問題」。ここでセッションを止めると、壊れた1本で
        // 以後の全ファイルが永久に送れなくなる（head-of-line ブロッキング）ので飛ばす。
        // ローカル失敗（http.begin / SD.open）も同じくファイル固有なので同じ扱いにする。
        // 通信のエラーコード（-1/-11 など）は「次のファイルでも同じ結果」なので含めない。
        if (lastCode == 400 || lastCode <= LOCALERR_BEGIN) {
          if (lastCode == 400) markBad400(full);   // E16: .wav → .b1 → .b2 → .bad
          s_carry++; continue;
        }
        s_carry += (n - i);          // 5xx/タイムアウト＝サーバ側障害。E5 どおり中止
        res = SYNC_SERVER_FAIL;
        stop = true;
        break;
      }
    }

    for (int i = 0; i < MAX_FILES; i++) s_names[i] = String();   // Stringのヒープを返す
    if (stop) break;
    if (n < MAX_FILES) break;     // 取りこぼしが無い＝全件見た
    if (deleted == 0) break;      // 1件も減らなかった＝残りは全部持越し。無限ループ防止
  }

  if (res == SYNC_OK && s_carry > 0) res = SYNC_CARRY_OVER;
  wifiOff();
  return res;
}
