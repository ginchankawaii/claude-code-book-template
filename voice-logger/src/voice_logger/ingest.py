"""デバイス受信API (Phase 1) — MindClip DIY からの音声を inbox に受け取る HTTP サーバ。

プロトコルは `firmware/SPEC.md` §6 で確定済み:

  GET  /api/v1/time    … デバイスのRTC補正用。サーバの現在時刻を返す
  POST /api/v1/ingest  … WAVの生バイト列を受け取り inbox に保存する

設計上の要点（SPEC §6.4 の順序を厳密に守る）:

  1. ボディを `inbox/<name>.wav.part` に書く（`.part` は `iter_audio_files()` が拾わない）
  2. flush + fsync
  3. 受信データの sha256 を計算し `X-MindClip-Sha256` と照合。不一致なら `.part` を消して 400
  4. os.rename で `inbox/<name>.wav` へ（同一FS内なのでアトミック）
  5. ディレクトリを fsync
  6. **ここで初めて 200 を返す** — デバイスは 200 を見て初めてSDから消すため

認証は二重（COMMS §3-1）。片方でも欠けたら起動しない/受け付けない:

  * mTLS      … クライアント証明書をプライベートCAで検証（`[ingest] client_ca`）
  * 共有秘密  … アプリ層 HMAC-SHA256。リバースプロキシでTLSを終端しても認証が消えない

    msg = "<method>\\n<path>\\n<device_id>\\n<sha256_hex_of_body>\\n<nonce_hex>"
    Authorization: MindClip-HMAC dev=<device_id>,nonce=<32hex>,sig=<64hex>

  タイムスタンプは使わない（デバイスのRTCが未同期でも認証が成立する必要があるため）。
  リプレイ耐性は ①nonce の LRU キャッシュ（4096件 / 24h）②ボディ sha256 による冪等化。
  ①はプロセス内メモリのみなので、**サーバ再起動後や4096件を超えて押し出された後は
  古い nonce のリプレイが 401 にならない**。ただし②が効くため、リプレイされても
  `duplicate:true` が返って inbox のファイルは1本のまま増えない（SPEC §6.1 の但し書き）。

  署名の検証対象は `X-MindClip-Sha256`（デバイスが宣言した sha256）で、ボディが
  その宣言と一致するかは受信後に別途照合して **不一致なら 400**（401 ではない）を返す。
  ボディを1バイトも読まずに 401 を確定できるうえ、「SDの読み出しがぶれてsha256が
  変わっただけの1ファイル」を認証エラーと誤診してセッション全体を止めずに済む。

依存は標準ライブラリのみ（FastAPI/uvicorn を足さない）。理由は3つ:
  ・ボディを一切バッファに溜めずに .part へストリーム書きし fsync するまでを自分で制御したい
  ・mTLS のためだけに ASGI サーバを持ち込みたくない（`ssl.SSLContext` で十分）
  ・Phase 0 が「重量級依存なしで動くコアロジック」を保っている方針に合わせる
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import os
import re
import secrets
import shutil
import socket
import ssl
import threading
import time
import uuid
from collections import OrderedDict
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import Config, IngestConfig

logger = logging.getLogger("voice_logger")

AUTH_SCHEME = "MindClip-HMAC"
TIME_PATH = "/api/v1/time"
INGEST_PATH = "/api/v1/ingest"
HEALTH_PATH = "/healthz"

# timeparse.parse_start_time() が必ず "filename" として解釈できる形だけを inbox に置く
STORED_STEM_RE = re.compile(r"^(\d{8})_(\d{6})(?:_\d+)*$")
PART_GLOB = ".ingest-*.wav.part"      # 受信中の一時ファイル（iter_audio_files() は拾わない）
DRAIN_MARGIN = 1 << 20                # ボディを読み捨ててでも応答を返す上限の上乗せ分
UNAUTH_DRAIN_CAP = 1 << 20            # 認証を通る前に読み捨ててよい上限（帯域増幅の防止）
MAX_AGE_MS = 7 * 24 * 3600 * 1000
NONCE_RE = re.compile(r"^[0-9a-fA-F]{16,64}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


# --------------------------------------------------------------------------- 補助


def canonical_name(start: datetime) -> str:
    """録音開始時刻 → `YYYYMMDD_HHMMSS.wav`（Phase 0 の timeparse がこの形式を読む）。"""
    return f"{start:%Y%m%d_%H%M%S}.wav"


def time_payload(now: datetime | None = None) -> dict:
    now = (now or datetime.now()).astimezone()
    offset = now.utcoffset() or timedelta(0)
    return {
        "ok": True,
        "server_epoch": int(now.timestamp()),
        "tz_offset_min": int(offset.total_seconds() // 60),
        "iso": now.isoformat(timespec="seconds"),
    }


def signing_string(method: str, path: str, device_id: str, body_sha256: str, nonce: str) -> str:
    return f"{method}\n{path}\n{device_id}\n{body_sha256}\n{nonce}"


def build_authorization(
    key: bytes, method: str, path: str, device_id: str, body: bytes, nonce: str | None = None,
    body_sha256: str | None = None,
) -> str:
    """クライアント側の署名生成（デバイス実装とテストの参照実装）。

    デバイスは送信前に SD 上のファイルから sha256 を計算し、その値を
    `X-MindClip-Sha256` ヘッダと署名の両方に使う。`body_sha256` はその
    「宣言値」を明示したいとき（＝ヘッダと署名が同じ値であることを試験するとき）に使う。
    """
    nonce = nonce or secrets.token_hex(16)
    body_sha = (body_sha256 or hashlib.sha256(body).hexdigest()).lower()
    msg = signing_string(method, path, device_id, body_sha, nonce)
    sig = hmac.new(key, msg.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{AUTH_SCHEME} dev={device_id},nonce={nonce},sig={sig}"


def _parse_authorization(header: str | None) -> tuple[str, str, str] | None:
    if not header:
        return None
    scheme, _, rest = header.partition(" ")
    if scheme.lower() != AUTH_SCHEME.lower():
        return None
    params: dict[str, str] = {}
    for item in rest.split(","):
        k, _, v = item.strip().partition("=")
        if k:
            params[k.strip().lower()] = v.strip()
    dev, nonce, sig = params.get("dev"), params.get("nonce"), params.get("sig")
    if not dev or not nonce or not sig:
        return None
    if not NONCE_RE.match(nonce) or not re.match(r"^[0-9a-fA-F]{64}$", sig):
        return None
    return dev, nonce, sig.lower()


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:  # 一部のFS/OSではディレクトリを開けない
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


class NonceCache:
    """使用済み nonce の LRU（SPEC §6.1: 4096件 / 24h）。"""

    def __init__(self, capacity: int = 4096, ttl_sec: int = 24 * 3600) -> None:
        self.capacity = capacity
        self.ttl_sec = ttl_sec
        self._items: OrderedDict[str, float] = OrderedDict()
        self._lock = threading.Lock()

    def use(self, device_id: str, nonce: str) -> bool:
        """未使用なら記録して True、再利用なら False。"""
        key = f"{device_id}:{nonce.lower()}"
        now = time.time()
        with self._lock:
            while self._items:
                oldest_key, ts = next(iter(self._items.items()))
                if now - ts > self.ttl_sec:
                    self._items.pop(oldest_key)
                else:
                    break
            if key in self._items:
                return False
            self._items[key] = now
            while len(self._items) > self.capacity:
                self._items.popitem(last=False)
            return True


class ReceiptLedger:
    """受信済み sha256 の台帳。再送（ACKロスト）を `duplicate:true` で回収するために使う。

    Phase 0 の `pipeline.Manifest`（処理済み台帳）とは別ファイル。
    inbox から archive へ移動された後でも「もう受け取った」と答えられるようにするため。

    **追記型（JSON Lines）**にしてある。1件ごとに台帳全体を書き直して fsync すると、
    上限の20000件では1件あたり100ms超・ファイル6MBに達し、しかもその待ち時間は
    「200 を返す前」＝デバイスがWiFiを上げたまま（約100mA）待っている区間に丸ごと乗る。
    追記なら1件あたりの書込は数百バイトで、コストは件数に依存しない。

      * 1レコード = `{"sha256": ..., "stored_name": ..., ...}` の1行
      * 起動時に全行を読み、後勝ちで OrderedDict に畳む（同一 sha256 は最後の行が有効）
      * 行数が `limit` の2倍を超えたら、その時点のメモリ内容だけを書き直して圧縮する
        （tmp へ書き出し → fsync → `os.replace` → ディレクトリ fsync のアトミック置換）

    旧形式（`ingest_receipts.json` = 全体書き直し）が残っていれば起動時に取り込み、
    `.json.migrated` へ退避する。
    """

    def __init__(self, state_dir: Path, limit: int = 20000) -> None:
        self.path = state_dir / "ingest_receipts.jsonl"
        self.legacy_path = state_dir / "ingest_receipts.json"
        self.limit = limit
        self._lock = threading.Lock()
        self._data: OrderedDict[str, dict] = OrderedDict()
        self._lines = 0
        self._fh = None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        migrated = self._load_legacy()
        self._load()
        if migrated:
            self._compact_locked()

    # ---- 読み込み

    def _load_legacy(self) -> bool:
        if not self.legacy_path.exists():
            return False
        try:
            raw = json.loads(self.legacy_path.read_text(encoding="utf-8"))
            self._data = OrderedDict(raw)
        except (json.JSONDecodeError, OSError, TypeError):
            logger.warning("旧形式の受信台帳が読めないので無視します: %s", self.legacy_path)
            return False
        try:
            self.legacy_path.replace(self.legacy_path.with_suffix(".json.migrated"))
        except OSError:
            pass
        logger.info("旧形式の受信台帳 %d 件を追記型へ移行しました", len(self._data))
        return True

    def _load(self) -> None:
        if not self.path.exists():
            return
        broken = 0
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    self._lines += 1
                    try:
                        rec = json.loads(line)
                        digest = rec.pop("sha256")
                    except (json.JSONDecodeError, KeyError, TypeError):
                        broken += 1  # 追記途中で電源が落ちた最終行など。捨てて続行
                        continue
                    self._data[digest] = rec
                    self._data.move_to_end(digest)
        except OSError as exc:
            logger.warning("受信台帳が読めないので新規作成します: %s (%s)", self.path, exc)
            return
        while len(self._data) > self.limit:
            self._data.popitem(last=False)
        if broken:
            logger.warning("受信台帳の壊れた行を %d 行読み飛ばしました: %s", broken, self.path)

    # ---- 書き込み

    def _handle(self):
        if self._fh is None:
            self._fh = open(self.path, "a", encoding="utf-8")
        return self._fh

    def _compact_locked(self) -> None:
        """メモリ上の内容だけを書き直す（行数を `len(self._data)` に戻す）。"""
        if self._fh is not None:
            self._fh.close()
            self._fh = None
        tmp = self.path.with_suffix(".jsonl.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            for digest, entry in self._data.items():
                f.write(json.dumps({"sha256": digest, **entry}, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(self.path)
        _fsync_dir(self.path.parent)
        self._lines = len(self._data)

    def lookup(self, digest: str) -> dict | None:
        with self._lock:
            return self._data.get(digest)

    def record(self, digest: str, entry: dict) -> None:
        with self._lock:
            self._data[digest] = entry
            self._data.move_to_end(digest)
            while len(self._data) > self.limit:
                self._data.popitem(last=False)
            f = self._handle()
            f.write(json.dumps({"sha256": digest, **entry}, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())  # 200 を返す前に台帳を確定させる（再送の冪等化の根拠）
            self._lines += 1
            if self._lines > max(2 * self.limit, 1000):
                self._compact_locked()

    def close(self) -> None:
        with self._lock:
            if self._fh is not None:
                self._fh.close()
                self._fh = None


# --------------------------------------------------------------------------- 本体


class AuthError(Exception):
    def __init__(self, status: int, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason


class IngestService:
    """設定・鍵・台帳・命名規則を持つ受信ロジック（HTTPから切り離してテストしやすくする）。"""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.ic: IngestConfig = cfg.ingest
        self.inbox = Path(cfg.paths.inbox)
        self.state = Path(cfg.paths.state)
        self.inbox.mkdir(parents=True, exist_ok=True)
        self.state.mkdir(parents=True, exist_ok=True)
        self.keys = self._load_keys()
        if not self.keys:
            raise RuntimeError(
                "共有秘密(HMAC)が未設定です。無認証では受け付けません。"
                " config.toml の [ingest] hmac_key_hex / hmac_key_file / devices か、"
                " 環境変数 MINDCLIP_HMAC_KEY (hex) を設定してください"
            )
        # 未知デバイスIDでも既知と同じHMAC計算を通すためのダミー鍵（起動ごとにランダム）。
        # これで「未知ID」と「署名不一致」の応答が区別できなくなる
        self._decoy_key = secrets.token_bytes(32)
        self.nonces = NonceCache()
        self.ledger = ReceiptLedger(self.state)
        self._name_lock = threading.Lock()
        self._reserved: set[str] = set()
        self._networks = [ipaddress.ip_network(n) for n in self.ic.allowed_networks]
        self.cleanup_stale_parts()

    def cleanup_stale_parts(self) -> int:
        """前回プロセスが SIGKILL された等で残った `.ingest-*.wav.part` を起動時に消す。

        `.part` は Phase 0 に拾われないので処理事故にはならないが、放置すると
        inbox の容量だけを食い続ける（§6.4）。起動時にしか呼ばないので、
        受信中のファイルを巻き込むことはない。
        """
        removed = 0
        for stale in self.inbox.glob(PART_GLOB):
            try:
                size = stale.stat().st_size
                stale.unlink()
            except OSError:
                continue
            removed += 1
            logger.warning("前回の中断で残った一時ファイルを削除しました: %s (%d バイト)",
                           stale.name, size)
        return removed

    # ---- 鍵

    def _load_keys(self) -> dict[str, bytes]:
        keys: dict[str, bytes] = {}

        def parse(value: str, where: str) -> bytes:
            value = value.strip()
            if value.startswith("@"):
                value = Path(os.path.expanduser(value[1:])).read_text(encoding="utf-8").strip()
            try:
                key = bytes.fromhex(value)
            except ValueError as exc:
                raise RuntimeError(f"{where} の鍵が16進数ではありません") from exc
            if len(key) < 16:
                raise RuntimeError(f"{where} の鍵が短すぎます（16バイト以上必要）")
            return key

        # "*" = デバイスID を問わず使う鍵（単機運用）
        env = os.environ.get("MINDCLIP_HMAC_KEY", "").strip()
        if env:
            keys["*"] = parse(env, "MINDCLIP_HMAC_KEY")
        if self.ic.hmac_key_hex:
            keys["*"] = parse(self.ic.hmac_key_hex, "[ingest] hmac_key_hex")
        if self.ic.hmac_key_file:
            keys["*"] = parse("@" + self.ic.hmac_key_file, "[ingest] hmac_key_file")
        for dev, value in (self.ic.devices or {}).items():
            keys[dev] = parse(value, f"[ingest.devices] {dev}")
        return keys

    def key_for(self, device_id: str) -> bytes | None:
        return self.keys.get(device_id) or self.keys.get("*")

    # ---- 認証

    def check_client_ip(self, addr: str) -> bool:
        if not self._networks:
            return True
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return False
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        return any(ip in net for net in self._networks)

    def authenticate(
        self, method: str, path: str, header: str | None, body_sha256: str, peer_cn: str | None
    ) -> str:
        parsed = _parse_authorization(header)
        if not parsed:
            raise AuthError(401, "Authorization ヘッダが無い/形式不正")
        device_id, nonce, sig = parsed
        key = self.key_for(device_id)
        if key is None:
            # 未知IDと署名不一致で応答を変えると、デバイスIDを列挙できてしまう。
            # ダミー鍵で同じ計算量を通し、外向きの文言・処理時間を揃える
            # （どちらだったかはサーバログにだけ残す）。
            logger.warning("未知のデバイスID: %s", device_id)
            key = self._decoy_key
        expected = hmac.new(
            key, signing_string(method, path, device_id, body_sha256, nonce).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, sig):
            raise AuthError(401, "認証失敗")
        if self.ic.cert_cn_must_match_device and peer_cn is not None and peer_cn != device_id:
            raise AuthError(403, f"証明書CN({peer_cn})とデバイスID({device_id})が不一致")
        if not self.nonces.use(device_id, nonce):
            raise AuthError(401, "nonce の再利用（リプレイ）")
        return device_id

    # ---- 命名

    def resolve_start_time(self, headers: dict, now: datetime) -> tuple[datetime, str]:
        """保存名の基準となる録音開始時刻と、その決定根拠を返す。"""
        unsynced = (headers.get("x-mindclip-unsynced") or "0").strip() not in ("", "0", "false")
        filename = (headers.get("x-mindclip-filename") or "").strip()
        stem = Path(filename.replace("\\", "/")).name
        # デバイス側の作業用サフィックス（`.wav.b1` / `.wav.b2` = SPEC §6.3 E16 の再送カウンタ、
        # `.wav.rec` = 録音中）を落として素の stem にする。落とさないと正準名なのに
        # STORED_STEM_RE に外れ、録音時刻を捨てて server_now で命名してしまう。
        cut = stem.lower().find(".wav")
        if cut > 0:
            stem = stem[:cut]

        if not unsynced:
            m = STORED_STEM_RE.match(stem)
            if m:
                try:
                    return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S"), "filename"
                except ValueError:
                    pass
            logger.warning(
                "正準名でないファイル名を受信したためサーバ時刻で命名します: %r", filename
            )
            return now, "server_now"

        raw_age = (headers.get("x-mindclip-age-ms") or "").strip()
        try:
            age_ms = int(raw_age)
        except ValueError:
            age_ms = -1
        if 0 <= age_ms <= MAX_AGE_MS:
            return now - timedelta(milliseconds=age_ms), "age_ms"
        logger.warning("X-MindClip-Age-Ms が無い/異常(%r)。サーバ時刻で命名します", raw_age)
        return now, "server_now"

    def reserve_name(self, start: datetime) -> str:
        """衝突しない保存名を予約する（`_1`, `_2`, … は timeparse が先頭一致で解釈できる）。"""
        base = f"{start:%Y%m%d_%H%M%S}"
        with self._name_lock:
            for i in range(0, 1000):
                name = f"{base}.wav" if i == 0 else f"{base}_{i}.wav"
                if name in self._reserved or (self.inbox / name).exists():
                    continue
                self._reserved.add(name)
                return name
        raise RuntimeError(f"同名ファイルが多すぎます: {base}")

    def release_name(self, name: str) -> None:
        with self._name_lock:
            self._reserved.discard(name)

    # ---- 重複判定

    def already_received(self, digest: str) -> dict | None:
        entry = self.ledger.lookup(digest)
        if entry:
            return entry
        manifest = self.state / "manifest.json"
        if manifest.exists():  # Phase 0 側で処理済み（sha256 キー）
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return None
            hit = data.get(digest)
            if hit:
                return {"stored_name": hit.get("source", ""), "source": "manifest"}
        return None

    def free_bytes(self) -> int:
        return shutil.disk_usage(self.inbox).free


class _Handler(BaseHTTPRequestHandler):
    server_version = "MindClipIngest/1.0"
    sys_version = ""
    protocol_version = "HTTP/1.1"  # keep-alive（デバイスは1本のTLSを使い回す）
    _responded = False             # 1リクエスト内で応答行を送ったか（500 の二重送信を防ぐ）

    # ---- 応答

    def _send_json(self, status: int, payload: dict, close: bool = False) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._responded = True
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if close:
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        self.wfile.write(body)

    def _fail(self, status: int, reason: str, close: bool = True, **extra) -> None:
        logger.warning("%s %s → %d %s", self.command, self.path, status, reason)
        self._send_json(status, {"ok": False, "error": reason, **extra}, close=close)

    def log_message(self, fmt: str, *args) -> None:  # BaseHTTPRequestHandler の stderr 出力を抑止
        logger.debug("%s %s", self.address_string(), fmt % args)

    def _fail_internal(self, where: str) -> None:
        """想定外の例外を **500** にして返す（応答を返さずに切らない）。

        `os.rename` や台帳書込のような「起こらないはず」の失敗でハンドラを抜けると、
        HTTPステータスを一切返さないまま接続が切れる。デバイスからはそれが
        「一時障害（サーバ応答なし）」に見えるため SPEC §7 E5 としてセッション全体が
        中止され、原因が恒久的だと毎晩全件が送れず最後はSDが埋まって E2＝録音停止になる。
        500 を返しておけば挙動は同じ「持越し」でも、ログに例外が残り診断できる。
        """
        logger.exception("%s で予期しない例外: %s %s", where, self.command, self.path)
        if self._responded:            # 応答済みなら接続だけ落とす（ヘッダは二重に送れない）
            self.close_connection = True
            return
        try:
            self._fail(500, "サーバ内部エラーです（サーバのログを確認してください）")
        except OSError:
            self.close_connection = True

    # ---- 共通前処理

    @property
    def service(self) -> IngestService:
        return self.server.service  # type: ignore[attr-defined]

    def _peer_cn(self) -> str | None:
        cert = getattr(self.connection, "getpeercert", lambda: None)()
        if not cert:
            return None
        for rdn in cert.get("subject", ()):
            for key, value in rdn:
                if key == "commonName":
                    return value
        return None

    def _raw_path(self) -> str:
        """リクエストラインのパスを**そのまま**返す。

        `http.server` は `//api/...` を `/api/...` に正規化してしまうため、
        `self.path` だけを見ると「srv.url の末尾スラッシュ」事故が
        署名対象パスの不一致＝401（デバイス側では E6＝設定不正）に化けて原因が分からなくなる。
        """
        words = self.requestline.split()
        return words[1].split("?", 1)[0] if len(words) >= 2 else self.path

    def _route(self, expected: str) -> bool:
        """パスが `expected` かを判定し、違えば 404 を返す（末尾スラッシュ事故は原因を明示）。"""
        raw_path = self._raw_path()
        if raw_path == expected:
            return True
        if re.sub(r"/{2,}", "/", raw_path) == expected:
            self._fail(404, f"パスが {raw_path!r} になっています。"
                            f" srv.url の末尾スラッシュを外してください（正しくは {expected}）")
            return False
        self._fail(404, "不明なパスです")
        return False

    def _drain_body(self, length: int, cap: int) -> bool:
        """エラー応答を返す前にボディを読み捨てる。読み切れたら True。

        HTTP/1.1 では「ボディを読まずに応答して切る」とクライアント側が
        送信失敗(EPIPE)しか観測できず、413/507 のような**返したい意味**が伝わらない。
        ディスクには一切書かないので、上限内なら読み捨ててから応答する。
        """
        if length > cap:
            return False
        remaining = length
        try:
            while remaining > 0:
                chunk = self.rfile.read(min(1 << 16, remaining))
                if not chunk:
                    return False
                remaining -= len(chunk)
        except OSError:
            return False
        return True

    def _fail_before_body(self, status: int, reason: str, length: int, cap: int, **extra) -> None:
        """ボディ受信前に確定したエラー。読み捨てられたなら keep-alive を維持する。

        `length < 0`（Content-Length が読めない）なら読み捨てようがないので接続を切る。
        切る場合、送信中のクライアントには応答が届かず送信失敗として観測されうる。
        """
        drained = length >= 0 and self._drain_body(length, cap)
        self._fail(status, reason, close=not drained, **extra)

    def _guard_client(self) -> bool:
        if not self.service.check_client_ip(self.client_address[0]):
            self._fail(403, f"許可されていない接続元です: {self.client_address[0]}")
            return False
        return True

    # ---- ルーティング

    def do_GET(self) -> None:  # noqa: N802
        self._responded = False   # keep-alive: 1インスタンスが複数リクエストを捌く
        path = self.path.split("?", 1)[0]
        # healthz も接続元フィルタの内側に置く（許可範囲外からの生存確認を返さない）
        if not self._guard_client():
            return
        if path == HEALTH_PATH:
            self._send_json(200, {"ok": True})
            return
        if not self._route(TIME_PATH):
            return
        try:
            device = self.service.authenticate("GET", path, self.headers.get("Authorization"),
                                               hashlib.sha256(b"").hexdigest(), self._peer_cn())
        except AuthError as exc:
            self._fail(exc.status, exc.reason)
            return
        try:
            payload = time_payload()
            logger.info("時刻応答: dev=%s epoch=%d", device, payload["server_epoch"])
            self._send_json(200, payload)
        except (socket.timeout, TimeoutError, ConnectionError):
            self.close_connection = True
        except Exception:  # noqa: BLE001 — 応答を返さずに切らないための最後の砦
            self._fail_internal("時刻応答")

    def do_POST(self) -> None:  # noqa: N802
        self._responded = False   # keep-alive: 1インスタンスが複数リクエストを捌く
        path = self.path.split("?", 1)[0]
        if not self._guard_client():
            return
        if not self._route(INGEST_PATH):
            return
        try:
            self._handle_ingest(path)
        except (socket.timeout, TimeoutError):
            self._fail(408, "ボディ受信がタイムアウトしました")
        except ConnectionError as exc:
            logger.warning("接続が切れました: %s", exc)
            self.close_connection = True
        except Exception:  # noqa: BLE001 — 応答を返さずに切らないための最後の砦
            self._fail_internal("受信処理")

    # ---- POST /api/v1/ingest

    def _handle_ingest(self, path: str) -> None:
        svc = self.service
        headers = {k.lower(): v for k, v in self.headers.items()}

        # 0) Content-Length を先に読む（エラー応答の前にボディを読み捨てるかの判断に使う）
        raw_len = headers.get("content-length")
        try:
            length = int(raw_len) if raw_len is not None else -1
        except ValueError:
            length = -1

        # 1) 認証ヘッダの形だけ先に見る（未知のデバイスにはディスクを1バイトも使わない）
        parsed = _parse_authorization(self.headers.get("Authorization"))
        if not parsed or svc.key_for(parsed[0]) is None:
            # 認証前なので読み捨ては小さく打ち切る（正常なリクエストなら応答が読める）
            self._fail_before_body(401, "認証ヘッダが不正、または未知のデバイスです",
                                   length, DRAIN_MARGIN)
            return
        device_id = parsed[0]

        # 2) 長さの検証（ボディを読む前に 413 / 400 / 507 を確定させる）
        if raw_len is None:
            self._fail(400, "Content-Length が必要です（chunked は非対応）")
            return
        if length < 0:
            self._fail(400, "Content-Length が数値ではありません")
            return
        if length == 0:
            self._fail(400, "空のボディです", close=False)
            return
        # 読み捨ての上限。ここを超える申告は読まずに切る（帯域を守る）
        drain_cap = svc.ic.max_bytes + DRAIN_MARGIN
        # 認証を通る前は読み捨て量を小さく抑える。ここを max_bytes にすると、鍵を持たない
        # 相手が「巨大な Content-Length + でたらめな署名」を送るだけで、サーバに最大128MBを
        # 読ませられる（応答を読める形にするための読み捨てが増幅に使われる）。
        # 正規のデバイスがここに来るのはヘッダ形式異常のときだけで、その場合は接続が切れても
        # ファイルは持ち越されるので安全側。
        unauth_cap = min(drain_cap, UNAUTH_DRAIN_CAP)
        if length > svc.ic.max_bytes:
            self._fail_before_body(413, f"サイズ超過です（上限 {svc.ic.max_bytes} バイト）",
                                   length, unauth_cap)
            return
        declared = headers.get("x-mindclip-bytes")
        if declared is not None and declared.strip().isdigit() and int(declared) != length:
            self._fail_before_body(
                400, f"X-MindClip-Bytes({declared}) と Content-Length({length}) が不一致",
                length, unauth_cap)
            return
        expected_sha = (headers.get("x-mindclip-sha256") or "").strip().lower()
        if not SHA256_RE.match(expected_sha):
            self._fail_before_body(400, "X-MindClip-Sha256 が無い/形式不正", length, unauth_cap)
            return

        # 3) 認証（署名は「デバイスが宣言した sha256」に対して検証する）
        #    ボディがその宣言と一致するかは 5) で照合し、**不一致は 400**（401 ではない）。
        #    こうしないと「SDの読み出しがぶれて sha が変わっただけ」の1ファイルが
        #    401 = 認証設定不正と誤診され、デバイスがセッション全体を中止してしまう（SPEC §7 E6）。
        try:
            svc.authenticate("POST", path, self.headers.get("Authorization"), expected_sha,
                             self._peer_cn())
        except AuthError as exc:
            self._fail_before_body(exc.status, exc.reason, length, unauth_cap)
            return
        if svc.free_bytes() - length < svc.ic.min_free_bytes:
            self._fail_before_body(507, "サーバのディスク空き容量が不足しています",
                                   length, drain_cap)
            return

        # 4) .part にストリーム書き込み（.part は iter_audio_files() が拾わない）
        part = svc.inbox / f".ingest-{uuid.uuid4().hex}.wav.part"
        try:
            received, digest = self._stream_to_part(part, length)
        except BaseException:
            part.unlink(missing_ok=True)
            raise

        try:
            # 失敗応答の前に必ず .part を消す（応答を読んだ側から見て一瞬でも見えないように）
            if received != length:  # 部分受信（電池切れ・WiFi断など）
                part.unlink(missing_ok=True)
                self._fail(400, f"部分受信です（{received}/{length} バイト）")
                return
            # 5) ボディ整合（転送中の破損・SD読み出しのぶれ）→ ファイル単位の 400
            if digest != expected_sha:
                part.unlink(missing_ok=True)
                self._fail(400, "sha256 が一致しません（転送中に壊れた可能性）", close=False)
                return

            now = datetime.now()
            # 6) 既に受け取っている sha256 なら書かずに duplicate:true（デバイスは消してよい）
            dup = svc.already_received(digest)
            if dup:
                logger.info("重複受信: dev=%s sha=%s… 既存=%s",
                            device_id, digest[:12], dup.get("stored_name"))
                self._send_json(200, {
                    "ok": True, "sha256": digest, "stored_name": dup.get("stored_name", ""),
                    "bytes": length, "duplicate": True, **time_payload(now),
                })
                return

            start, basis = svc.resolve_start_time(headers, now)
            name = svc.reserve_name(start)
            target = svc.inbox / name
            try:
                # 7) SPEC §6.4: rename（アトミック）→ ディレクトリ fsync → 200
                os.rename(part, target)
                _fsync_dir(svc.inbox)
            finally:
                svc.release_name(name)

            try:
                svc.ledger.record(digest, {
                    "stored_name": name, "device": device_id, "bytes": length,
                    "received_at": now.isoformat(timespec="seconds"),
                    "original_name": headers.get("x-mindclip-filename", ""),
                    "name_basis": basis,
                    "duration_ms": headers.get("x-mindclip-duration-ms", ""),
                })
            except OSError:
                # ファイルは既に inbox にある（＝受理は済んでいる）。ここで 500 を返すと
                # デバイスが再送し、台帳に無いので重複判定も効かず inbox に2本目が並ぶ。
                # 台帳は再送回収のための最適化にすぎないので、失敗はログに留めて 200 を返す。
                logger.exception("受信台帳に記録できませんでした（保存は完了しています）: %s", name)
            logger.info("受信完了: %s (%d バイト, dev=%s, 命名=%s)", name, length, device_id, basis)
            self._send_json(200, {
                "ok": True, "sha256": digest, "stored_name": name,
                "bytes": length, "duplicate": False, **time_payload(now),
            })
        finally:
            part.unlink(missing_ok=True)  # 成功時は rename 済みなので何もしない

    def _stream_to_part(self, part: Path, length: int) -> tuple[int, str]:
        h = hashlib.sha256()
        received = 0
        with open(part, "wb") as f:
            while received < length:
                chunk = self.rfile.read(min(1 << 16, length - received))
                if not chunk:
                    break  # 接続断 = 部分受信
                f.write(chunk)
                h.update(chunk)
                received += len(chunk)
            f.flush()
            os.fsync(f.fileno())  # SPEC §6.4-2: 200 を返す前に必ずディスクに落とす
        if received != length:
            self.close_connection = True
        return received, h.hexdigest()


class IngestHTTPServer(ThreadingHTTPServer):
    """同時接続数に上限を設けた ThreadingHTTPServer。

    素の ThreadingHTTPServer は接続ごとに無制限にスレッドを作るため、LAN内の1台が
    多数の低速接続（slowloris）を張るだけでスレッド・FD を枯渇させ、受信APIを停止
    させられる。デバイスは 200 を受けるまで SD からファイルを消さないので、受信が
    止まり続けると最終的に SD が埋まって録音自体が止まる（SPEC E2）。
    上限に達した接続は待たせず即座に閉じ、デバイス側は次回同期へ持ち越す。
    """

    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 32

    def __init__(self, addr, handler, service: IngestService,
                 max_connections: int = 16) -> None:
        self.service = service
        self._slots = threading.BoundedSemaphore(max_connections)
        self._max_connections = max_connections
        super().__init__(addr, handler)

    def process_request(self, request, client_address) -> None:
        if not self._slots.acquire(blocking=False):
            logger.warning("同時接続数の上限(%d)に達したため接続を拒否: %s",
                           self._max_connections, client_address[0])
            # 枠を取れなかった接続は close_request を通さずここで閉じる。
            # （通してしまうと、取っていない枠を release して上限が壊れる）
            try:
                request.close()
            except OSError:
                pass
            return
        super().process_request(request, client_address)

    def close_request(self, request) -> None:
        # 受理した接続は必ずここを1回通るので、枠の返却漏れが起きない
        try:
            super().close_request(request)
        finally:
            self._slots.release()


def build_ssl_context(ic: IngestConfig) -> ssl.SSLContext | None:
    """設定からTLS(必要なら mTLS)コンテキストを作る。平文許可時のみ None を返す。"""
    if not ic.tls_cert or not ic.tls_key:
        if not ic.allow_plaintext:
            raise RuntimeError(
                "TLS証明書([ingest] tls_cert / tls_key)が未設定です。"
                " デバイスは http:// を受け付けません。試験目的で平文にする場合のみ"
                " allow_plaintext = true を明示してください"
            )
        # 平文では mTLS が成立しない。require_mtls=true のまま起動すると
        # 「クライアント証明書で守られている」と誤認したまま無防備に待ち受けることになる
        # ため、矛盾した設定は黙って通さず起動を拒否する。
        if ic.require_mtls:
            raise RuntimeError(
                "allow_plaintext = true と require_mtls = true が同時に指定されています。"
                " 平文HTTPではクライアント証明書の検証ができないため、この組み合わせでは"
                " mTLS は一切効きません。試験目的であることを承知のうえで平文にする場合は"
                " require_mtls = false も明示してください"
            )
        logger.warning(
            "平文HTTPで待ち受けます（allow_plaintext=true）。TLSもクライアント証明書検証も"
            "無効で、認証は共有秘密HMACのみです。実運用では使わないこと"
        )
        return None
    if ic.cert_cn_must_match_device and not ic.client_ca:
        # CN一致要求は mTLS があって初めて意味を持つ。無言で無効化しない。
        raise RuntimeError(
            "cert_cn_must_match_device = true ですが [ingest] client_ca が未設定です。"
            " クライアント証明書を検証しない構成では CN の照合ができません。"
            " client_ca を指定するか cert_cn_must_match_device = false にしてください"
        )
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(certfile=os.path.expanduser(ic.tls_cert),
                        keyfile=os.path.expanduser(ic.tls_key))
    if ic.client_ca:
        ctx.load_verify_locations(cafile=os.path.expanduser(ic.client_ca))
        ctx.verify_mode = ssl.CERT_REQUIRED
    elif ic.require_mtls:
        raise RuntimeError(
            "mTLS が有効(require_mtls=true)ですが [ingest] client_ca が未設定です。"
            " クライアント証明書を検証するCAを指定するか require_mtls = false にしてください"
        )
    else:
        logger.warning("クライアント証明書を検証しません（HMAC のみで認証します）")
    return ctx


def build_server(cfg: Config, host: str | None = None, port: int | None = None) -> IngestHTTPServer:
    ic = cfg.ingest
    service = IngestService(cfg)
    ctx = build_ssl_context(ic)
    bind_host = host if host is not None else ic.host
    bind_port = ic.port if port is None else port
    if bind_host in ("0.0.0.0", "::"):
        logger.warning(
            "%s にバインドします。全インターフェースで待ち受けるため、"
            "LANのIPを明示するか allowed_networks / ファイアウォールで必ず絞ること", bind_host
        )
    server = IngestHTTPServer((bind_host, bind_port), _Handler, service)
    if ctx is not None:
        server.socket = ctx.wrap_socket(server.socket, server_side=True)
    server.timeout = ic.socket_timeout_sec
    _Handler.timeout = ic.socket_timeout_sec
    return server


def serve(cfg: Config, host: str | None = None, port: int | None = None) -> int:
    server = build_server(cfg, host, port)
    scheme = "https" if cfg.ingest.tls_cert else "http"
    bound_host, bound_port = server.server_address[:2]
    logger.info("受信APIを開始: %s://%s:%s%s （Ctrl-Cで終了）",
                scheme, bound_host, bound_port, INGEST_PATH)
    logger.info("デバイス数: %d（'*' は全デバイス共通鍵）, inbox=%s",
                len(server.service.keys), server.service.inbox)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("終了します")
    finally:
        server.shutdown()
        server.server_close()
        server.service.ledger.close()
    return 0
