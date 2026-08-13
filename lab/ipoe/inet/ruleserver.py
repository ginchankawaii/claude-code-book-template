#!/usr/bin/env python3
"""HB46PP プロビジョニングサーバの模擬 (= Cisco の `nat64 provisioning mode jp01` の相手方)

    usage: sudo ./ruleserver.py [--bind ADDR] [--port 80] [--tls-port 443]
                                [--cert FILE --key FILE] [--response FILE]

────────────────────────────────────────────────────────────────────────
**なぜこれが要るのか (ラボの設計不良の是正)**

  本番の MAP-E / DS-Lite では、CPE に MAP ルールを**手で入れない**。
  CPE は起動時に **プロビジョニングサーバからルールを取得する**。
  これが JAIPA (日本インターネットプロバイダー協会) の
  「IPv6 マイグレーション技術の国内標準プロビジョニング方式」= **HB46PP**
  (HTTP-Based IPv4 over IPv6 Provisioning Protocol) であり、
  Cisco IOS XE ではこれが `nat64 provisioning mode jp01` にあたる。

  ラボにはこのサーバが存在しなかったため、これまで MAP-E の検証は
  「CPE に basic-mapping-rule を手書きする」経路でやっていた。
  **それは本番に存在しない経路である。** 実機 C1111-8P ではその経路で
  QFP がクラッシュした (build-log サイクル 9/10、6/6 再現)。
  本番と同じ経路を通していなかったこと自体がラボの欠陥だった。

────────────────────────────────────────────────────────────────────────
**HB46PP の流れ (このサーバが再現するもの)**

  1. CPE が `4over6.info` の **TXT レコード**を引く
       "v=v6mig-1 url=https://prov.lab.example/rule.cgi t=b"
         v   … 固定値 v6mig-1
         url … プロビジョニングサーバの URL
         t   … a=証明書検証なし / b=検証あり
  2. CPE が その URL に **HTTP GET**
       /rule.cgi?vendorid=...&product=...&version=...&capability=map_e,dslite
       (認証がある場合は user= / pass= / token= が付く)
  3. サーバが **JSON** を返す。CPE はその中の map_e ルールから
     **自分の IPv4 アドレスと PSID を自分で計算する** (EA-bits の展開)。

  つまりサーバは「この CPE の IPv4 は何番」を知らなくてよい。
  BMR (ipv6 プレフィックス + ipv4 プレフィックス + ea_length + psid_offset) を
  配るだけで、CPE が自分の委譲プレフィックスから導出する。

  参照: https://github.com/v6pc/v6mig-prov/blob/master/spec.md

────────────────────────────────────────────────────────────────────────
**このスクリプトの二つの役割**

  (A) 捕獲   … CPE が何を要求してきたかを **リクエスト行・全ヘッダ・ボディまで**
               記録する。Cisco の jp01 が HB46PP そのものなのか、
               独自パラメータ (api-key 等) を足しているのかは公開情報では
               確定できないので、**ルータ自身に喋らせて確かめる。**
  (B) 応答   … --response で指定した JSON をそのまま返す。
               ファイルは **リクエストのたびに読み直す** ので、
               ルータの反応を見ながら JSON を書き換えて即座に試せる
               (サーバの再起動が要らない)。

**ログ**  既定 /var/log/mape-ruleserver.log。標準出力にも同じものを出す。
"""
import argparse
import datetime
import http.server
import json
import os
import socket
import ssl
import sys
import threading
import urllib.parse

LOG_LOCK = threading.Lock()
LOG_FH = None


def log(msg):
    line = "%s %s" % (datetime.datetime.now().isoformat(timespec="seconds"), msg)
    with LOG_LOCK:
        print(line, flush=True)
        if LOG_FH:
            LOG_FH.write(line + "\n")
            LOG_FH.flush()


class Handler(http.server.BaseHTTPRequestHandler):
    # HTTP/1.1 を名乗る以上 Content-Length を必ず返すこと (下の _reply で付けている)。
    # 付け忘れるとクライアントは接続が閉じるまで本文の終わりを判定できず、
    # 「応答は返っているのにルータ側がタイムアウトする」という紛らわしい症状になる。
    protocol_version = "HTTP/1.1"
    server_version = "lab-hb46pp/1.0"

    response_path = None    # 返す JSON のファイル。None なら組み込みの既定値
    scheme = "http"         # ログ表示用

    # ── 捕獲 ────────────────────────────────────────────────────────
    def _capture(self):
        log("=" * 78)
        log("[%s] %s %s %s  from %s"
            % (self.scheme, self.command, self.path, self.request_version,
               self.client_address[0]))

        parsed = urllib.parse.urlparse(self.path)
        if parsed.query:
            log("--- クエリパラメータ ---")
            # keep_blank_values=True: 値が空のパラメータも「送ってきた」事実が重要
            for k, vals in urllib.parse.parse_qs(parsed.query,
                                                 keep_blank_values=True).items():
                for v in vals:
                    log("    %-14s = %s" % (k, v))
        else:
            log("--- クエリパラメータ: なし ---")

        log("--- ヘッダ ---")
        for k, v in self.headers.items():
            log("    %s: %s" % (k, v))

        body = b""
        length = self.headers.get("Content-Length")
        if length:
            try:
                body = self.rfile.read(int(length))
                log("--- ボディ (%s バイト) ---" % length)
                log("    %r" % body)
            except (ValueError, OSError) as e:
                log("    ボディ読み取り失敗: %s" % e)
        log("=" * 78)
        return body

    # ── 応答 ────────────────────────────────────────────────────────
    def _load_response(self):
        """応答 JSON を毎回読み直す。書き換えて即試せるようにするため。"""
        if not self.response_path:
            return json.dumps({"error": "no response file configured"}).encode()
        try:
            with open(self.response_path, "rb") as f:
                raw = f.read()
        except OSError as e:
            log("!! 応答ファイルを読めません (%s): %s" % (self.response_path, e))
            return json.dumps({"error": "response file unreadable"}).encode()
        # 壊れた JSON をそのまま返すとルータ側の切り分けが濁るので、ここで気づけるようにする
        try:
            json.loads(raw)
        except json.JSONDecodeError as e:
            log("!! 警告: 応答ファイルが JSON として壊れています: %s" % e)
        return raw

    def _reply(self, body, status=200, ctype="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        log("--> %d %s (%d バイト) を返しました" % (status, ctype, len(body)))

    def do_GET(self):
        self._capture()
        self._reply(self._load_response())

    def do_POST(self):
        self._capture()
        self._reply(self._load_response())

    def do_PUT(self):
        self._capture()
        self._reply(self._load_response())

    def do_HEAD(self):
        self._capture()
        self._reply(b"")

    def log_message(self, fmt, *args):
        """既定の stderr ログは _capture と重複するので黙らせる"""
        return


class LabServer(http.server.ThreadingHTTPServer):
    address_family = socket.AF_INET6
    allow_reuse_address = True
    daemon_threads = True

    ssl_context = None   # TLS のときだけ設定される

    def server_bind(self):
        # **V6ONLY を明示する。**
        # Linux の既定 (net.ipv6.bindv6only=0) では AF_INET6 のソケットが
        # IPv4 側も掴むため、同じポートで動いている nginx (0.0.0.0:80) と
        # 衝突して起動に失敗する。ここは IPv6 専用でよい。
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        super().server_bind()

    def get_request(self):
        """接続ごとに TLS を張る。**握手の失敗をログに出すため。**

        待受ソケット自体を wrap_socket すると、握手の失敗は accept() の中で
        ssl.SSLError として上がる。ssl.SSLError は OSError の子なので、
        socketserver はこれを「接続が取れなかっただけ」として **黙って捨てる**。
        結果、ルータ側は繋がらないのにサーバのログには何も出ない、という
        いちばん切り分けにくい状態になる (証明書未登録・時刻ずれで必ず踏む)。
        そこで待受は素のままにして、ここで 1 本ずつ包む。
        """
        sock, addr = self.socket.accept()
        if self.ssl_context is None:
            return sock, addr
        try:
            return self.ssl_context.wrap_socket(sock, server_side=True), addr
        except ssl.SSLError as e:
            log("!! TLS ハンドシェイク失敗 from %s : %s" % (addr[0], e))
            log("   よくある原因: ルータに CA が未登録 / ルータの時刻がずれている")
            sock.close()
            raise OSError("TLS handshake failed") from e


def serve(bind, port, handler_cls, certfile=None, keyfile=None):
    srv = LabServer((bind, port), handler_cls)
    if certfile:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile, keyfile)
        # **相手は古いルータかもしれない。**
        # Ubuntu の OpenSSL は既定の security level が高く、
        # 古い IOS XE が出す暗号スイートを弾くことがある。ラボの模擬サーバなので
        # 安全側に倒す理由がなく、繋がらない原因を減らすほうが価値が高い。
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        try:
            ctx.set_ciphers("DEFAULT:@SECLEVEL=1")
        except ssl.SSLError as e:
            log("!! 暗号スイートの緩和に失敗しました (既定のまま続行): %s" % e)
        srv.ssl_context = ctx
    srv.serve_forever()


def main():
    global LOG_FH

    ap = argparse.ArgumentParser(
        description="HB46PP (国内標準プロビジョニング方式) サーバの模擬")
    ap.add_argument("--bind", default="2001:db8:cafe::a1",
                    help="待受 IPv6 アドレス (既定: %(default)s)")
    ap.add_argument("--port", type=int, default=80, help="HTTP ポート (0 で無効)")
    ap.add_argument("--tls-port", type=int, default=443, help="HTTPS ポート (0 で無効)")
    ap.add_argument("--cert", help="サーバ証明書 (無指定なら HTTPS を上げない)")
    ap.add_argument("--key", help="サーバ秘密鍵")
    ap.add_argument("--response", default="/etc/mape-ruleserver/response.json",
                    help="返す JSON のファイル (既定: %(default)s)")
    ap.add_argument("--log", default="/var/log/mape-ruleserver.log")
    args = ap.parse_args()

    try:
        LOG_FH = open(args.log, "a")
    except OSError as e:
        print("ログファイルを開けません (%s): %s" % (args.log, e), file=sys.stderr)

    Handler.response_path = args.response
    if not os.path.exists(args.response):
        log("!! 応答ファイルがありません: %s (要求は記録できますが中身は返せません)"
            % args.response)

    threads = []

    if args.port:
        h = type("HttpHandler", (Handler,), {"scheme": "http"})
        t = threading.Thread(target=serve, args=(args.bind, args.port, h),
                             daemon=True)
        t.start()
        threads.append(t)
        log("HTTP  待受: http://[%s]:%d/" % (args.bind, args.port))

    if args.tls_port and args.cert:
        h = type("HttpsHandler", (Handler,), {"scheme": "https"})
        t = threading.Thread(target=serve,
                             args=(args.bind, args.tls_port, h),
                             kwargs={"certfile": args.cert, "keyfile": args.key},
                             daemon=True)
        t.start()
        threads.append(t)
        log("HTTPS 待受: https://[%s]:%d/  (cert=%s)"
            % (args.bind, args.tls_port, args.cert))
    elif args.tls_port and not args.cert:
        log("HTTPS は無効です (--cert が指定されていません)")

    if not threads:
        print("HTTP も HTTPS も無効です。--port か --cert を指定してください",
              file=sys.stderr)
        return 1

    log("応答ファイル: %s" % args.response)
    log("CPE からの要求を待っています。")
    try:
        for t in threads:
            t.join()
    except KeyboardInterrupt:
        log("終了します")
    return 0


if __name__ == "__main__":
    sys.exit(main())
