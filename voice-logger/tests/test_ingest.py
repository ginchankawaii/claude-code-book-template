"""受信API (`voice_logger.ingest`) のテスト。**実際にサーバを起動して** HTTP で叩く。

実行: cd voice-logger && PYTHONPATH=src python -m unittest discover tests -v

重量級依存（faster-whisper / Ollama）は読み込まない。標準ライブラリ + openssl のみ。
"""

from __future__ import annotations

import hashlib
import http.client
import json
import logging
import os
import secrets
import shutil
import socket
import ssl
import struct
import subprocess
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from voice_logger import ingest as ingest_mod
from voice_logger.config import Config, IngestConfig, PathsConfig
from voice_logger.ingest import ReceiptLedger, build_authorization, build_server
from voice_logger.pipeline import iter_audio_files
from voice_logger.timeparse import parse_start_time

# サーバのログはテスト出力を汚すだけなので黙らせる
logging.getLogger("voice_logger").setLevel(logging.CRITICAL)

# 環境変数由来の鍵がテストの前提を変えないように落としておく
os.environ.pop("MINDCLIP_HMAC_KEY", None)

KEY = bytes.fromhex("00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff")
DEVICE = "mindclip-01"


def wav_bytes(seconds: float = 0.1, seed: int = 1) -> bytes:
    """16kHz/16bit/mono の最小WAV（中身はテスト用の適当な波形）。"""
    n = int(16000 * seconds)
    pcm = b"".join(struct.pack("<h", (i * seed * 37) % 4096 - 2048) for i in range(n))
    header = (
        b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, 16000, 32000, 2, 16)
        + b"data" + struct.pack("<I", len(pcm))
    )
    return header + pcm


class ServerFixture:
    """テスト用に受信APIを実サーバとして起動する。"""

    def __init__(self, tmpdir: Path, **ingest_kwargs):
        self.tmp = tmpdir
        options = dict(
            host="127.0.0.1", port=0, allow_plaintext=True, require_mtls=False,
            hmac_key_hex=KEY.hex(), min_free_bytes=0,
        )
        options.update(ingest_kwargs)
        ingest = IngestConfig(**options)
        self.cfg = Config(
            paths=PathsConfig(
                inbox=tmpdir / "inbox", archive=tmpdir / "archive",
                state=tmpdir / "state", obsidian_vault=tmpdir / "vault",
            ),
            ingest=ingest,
        )
        self.server = build_server(self.cfg)
        self.host, self.port = self.server.server_address[:2]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def inbox(self) -> Path:
        return self.cfg.paths.inbox

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    # ---- HTTP クライアント（プロキシ環境変数の影響を受けないよう素の http.client を使う）

    def _conn(self, ssl_context: ssl.SSLContext | None = None):
        if ssl_context is not None:
            return http.client.HTTPSConnection(self.host, self.port, timeout=15,
                                               context=ssl_context)
        return http.client.HTTPConnection(self.host, self.port, timeout=15)

    def request(self, method: str, path: str, body: bytes = b"", headers: dict | None = None,
                key: bytes | None = KEY, device: str = DEVICE, nonce: str | None = None,
                sign_body: bytes | None = None, sign_sha: str | None = None,
                ssl_context: ssl.SSLContext | None = None):
        headers = dict(headers or {})
        if key is not None:
            headers["Authorization"] = build_authorization(
                key, method, path, device, sign_body if sign_body is not None else body, nonce,
                body_sha256=sign_sha,
            )
        conn = self._conn(ssl_context)
        try:
            conn.request(method, path, body=body, headers=headers)
            resp = conn.getresponse()
            payload = resp.read()
            return resp.status, json.loads(payload.decode("utf-8"))
        finally:
            conn.close()

    def post_wav_as(self, device: str, body: bytes, filename: str, **extra_headers):
        return self.post_wav(body, filename, _device=device, **extra_headers)

    def post_wav(self, body: bytes, filename: str, _device: str = DEVICE, **extra_headers):
        headers = {
            "Content-Type": "audio/wav",
            "Content-Length": str(len(body)),
            "X-MindClip-Device": DEVICE,
            "X-MindClip-Filename": filename,
            "X-MindClip-Sha256": hashlib.sha256(body).hexdigest(),
            "X-MindClip-Bytes": str(len(body)),
            "X-MindClip-Duration-Ms": "100",
        }
        headers["X-MindClip-Device"] = _device
        headers.update({k: str(v) for k, v in extra_headers.items()})
        return self.request("POST", "/api/v1/ingest", body=body, headers=headers, device=_device)


class IngestTestBase(unittest.TestCase):
    ingest_kwargs: dict = {}

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._dir.name)
        self.srv = ServerFixture(self.tmp, **self.ingest_kwargs)
        self.addCleanup(self.srv.close)
        self.addCleanup(self._dir.cleanup)

    def inbox_names(self) -> list[str]:
        return sorted(p.name for p in self.srv.inbox.iterdir())


class TestHappyPath(IngestTestBase):
    def test_time_endpoint_returns_server_clock(self):
        status, body = self.srv.request("GET", "/api/v1/time")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertLess(abs(body["server_epoch"] - datetime.now().timestamp()), 5)
        expected_off = int((datetime.now().astimezone().utcoffset().total_seconds()) // 60)
        self.assertEqual(body["tz_offset_min"], expected_off)
        self.assertEqual(datetime.fromisoformat(body["iso"]).timestamp(),
                         float(body["server_epoch"]))

    def test_ingest_stores_file_and_acks_after_fsync(self):
        body = wav_bytes()
        status, resp = self.srv.post_wav(body, "20260827_091500.wav")
        self.assertEqual(status, 200, resp)
        self.assertTrue(resp["ok"])
        self.assertFalse(resp["duplicate"])
        self.assertEqual(resp["stored_name"], "20260827_091500.wav")
        self.assertEqual(resp["sha256"], hashlib.sha256(body).hexdigest())
        self.assertEqual(resp["bytes"], len(body))
        # 200 を返した時点でファイルは inbox に完全な形で存在している（.part は残らない）
        self.assertEqual(self.inbox_names(), ["20260827_091500.wav"])
        stored = self.srv.inbox / "20260827_091500.wav"
        self.assertEqual(stored.read_bytes(), body)
        # 応答に時刻も含む（デバイスは送信の往復ごとにRTCを確認できる）
        self.assertIn("server_epoch", resp)

    def test_stored_name_is_understood_by_phase0(self):
        self.srv.post_wav(wav_bytes(), "20260827_091500.wav")
        found = iter_audio_files(self.srv.inbox)
        self.assertEqual([p.name for p in found], ["20260827_091500.wav"])
        start, source = parse_start_time(found[0])
        self.assertEqual(source, "filename")
        self.assertEqual(start, datetime(2026, 8, 27, 9, 15, 0))

    def test_non_canonical_name_is_renamed_to_canonical(self):
        status, resp = self.srv.post_wav(wav_bytes(), "recording.wav")
        self.assertEqual(status, 200)
        start, source = parse_start_time(self.srv.inbox / resp["stored_name"])
        self.assertEqual(source, "filename")  # inbox に非正準名を置かない
        self.assertLess(abs((datetime.now() - start).total_seconds()), 60)


class TestUnsyncedNaming(IngestTestBase):
    def test_unsynced_file_is_renamed_using_age_ms(self):
        age_ms = 3_600_000  # 1時間前に録音開始
        status, resp = self.srv.post_wav(
            wav_bytes(), "UNSYNC-0007-003.wav",
            **{"X-MindClip-Unsynced": 1, "X-MindClip-Age-Ms": age_ms},
        )
        self.assertEqual(status, 200, resp)
        start, source = parse_start_time(self.srv.inbox / resp["stored_name"])
        self.assertEqual(source, "filename")
        expected = datetime.now() - timedelta(milliseconds=age_ms)
        self.assertLess(abs((start - expected).total_seconds()), 30)

    def test_unsynced_with_bad_age_falls_back_to_server_now(self):
        status, resp = self.srv.post_wav(
            wav_bytes(seed=2), "UNSYNC-0007-004.wav",
            **{"X-MindClip-Unsynced": 1, "X-MindClip-Age-Ms": -5},
        )
        self.assertEqual(status, 200, resp)
        start, source = parse_start_time(self.srv.inbox / resp["stored_name"])
        self.assertEqual(source, "filename")
        self.assertLess(abs((datetime.now() - start).total_seconds()), 60)


class TestAuth(IngestTestBase):
    def test_missing_authorization_is_rejected(self):
        body = wav_bytes()
        headers = {
            "Content-Length": str(len(body)),
            "X-MindClip-Sha256": hashlib.sha256(body).hexdigest(),
        }
        status, resp = self.srv.request("POST", "/api/v1/ingest", body=body,
                                        headers=headers, key=None)
        self.assertEqual(status, 401)
        self.assertEqual(self.inbox_names(), [])  # 1バイトもディスクに残さない

    def test_wrong_key_is_rejected(self):
        body = wav_bytes()
        headers = {
            "Content-Length": str(len(body)),
            "X-MindClip-Sha256": hashlib.sha256(body).hexdigest(),
            "X-MindClip-Filename": "20260827_091500.wav",
        }
        headers["Authorization"] = build_authorization(b"\x00" * 32, "POST", "/api/v1/ingest",
                                                       DEVICE, body)
        status, _ = self.srv.request("POST", "/api/v1/ingest", body=body, headers=headers, key=None)
        self.assertEqual(status, 401)
        self.assertEqual(self.inbox_names(), [])

    def test_signature_bound_to_declared_sha(self):
        """宣言sha(ヘッダ)と署名がずれていれば 401。ボディを1バイトも書かずに落ちる。"""
        body = wav_bytes(seed=3)
        other = wav_bytes(seed=4)
        headers = {
            "Content-Length": str(len(body)),
            "X-MindClip-Sha256": hashlib.sha256(body).hexdigest(),
            "X-MindClip-Filename": "20260827_100000.wav",
        }
        status, _ = self.srv.request("POST", "/api/v1/ingest", body=body, headers=headers,
                                     sign_body=other)
        self.assertEqual(status, 401)
        self.assertEqual(self.inbox_names(), [])  # .part も残さない（応答後に消す競合も無い）

    def test_nonce_replay_is_rejected(self):
        nonce = secrets.token_hex(16)
        status, _ = self.srv.request("GET", "/api/v1/time", nonce=nonce)
        self.assertEqual(status, 200)
        status, resp = self.srv.request("GET", "/api/v1/time", nonce=nonce)
        self.assertEqual(status, 401)
        self.assertIn("nonce", resp["error"])

    def test_time_endpoint_requires_auth(self):
        status, _ = self.srv.request("GET", "/api/v1/time", key=None)
        self.assertEqual(status, 401)

    def test_server_refuses_to_start_without_shared_secret(self):
        cfg = Config(
            paths=PathsConfig(inbox=self.tmp / "i2", archive=self.tmp / "a2",
                              state=self.tmp / "s2", obsidian_vault=self.tmp / "v2"),
            ingest=IngestConfig(host="127.0.0.1", port=0, allow_plaintext=True,
                                require_mtls=False),
        )
        env = os.environ.pop("MINDCLIP_HMAC_KEY", None)
        try:
            with self.assertRaises(RuntimeError):
                build_server(cfg)
        finally:
            if env is not None:
                os.environ["MINDCLIP_HMAC_KEY"] = env

    def test_plaintext_requires_explicit_optin(self):
        cfg = Config(
            paths=PathsConfig(inbox=self.tmp / "i3", archive=self.tmp / "a3",
                              state=self.tmp / "s3", obsidian_vault=self.tmp / "v3"),
            ingest=IngestConfig(host="127.0.0.1", port=0, hmac_key_hex=KEY.hex()),
        )
        with self.assertRaises(RuntimeError):
            build_server(cfg)


class TestPerDeviceKeys(IngestTestBase):
    """デバイスごとに鍵を分けた運用（[ingest.devices]）。共通鍵 '*' は無い。"""

    ingest_kwargs = {"hmac_key_hex": "", "devices": {DEVICE: KEY.hex()}}

    def test_known_device_accepted(self):
        status, _ = self.srv.request("GET", "/api/v1/time")
        self.assertEqual(status, 200)

    def test_unknown_device_rejected(self):
        status, resp = self.srv.request("GET", "/api/v1/time", device="someone-else")
        self.assertEqual(status, 401)
        self.assertIn("デバイス", resp["error"])

    def test_unknown_device_rejected_before_reading_body(self):
        body = wav_bytes()
        status, _ = self.srv.post_wav_as("someone-else", body, "20260827_091500.wav")
        self.assertEqual(status, 401)
        self.assertEqual(self.inbox_names(), [])


class TestClientNetworkFilter(IngestTestBase):
    ingest_kwargs = {"allowed_networks": ["10.0.0.0/8"]}

    def test_client_outside_allowed_networks_is_rejected(self):
        status, resp = self.srv.request("GET", "/api/v1/time")
        self.assertEqual(status, 403)
        self.assertIn("127.0.0.1", resp["error"])


class TestIntegrity(IngestTestBase):
    def test_partial_upload_is_detected_and_discarded(self):
        """Content-Length より少ないバイト数で切断（電池切れ・WiFi断の再現）。"""
        body = wav_bytes(seconds=0.5)
        sent = body[: len(body) // 3]
        auth = build_authorization(KEY, "POST", "/api/v1/ingest", DEVICE, body)
        raw = (
            f"POST /api/v1/ingest HTTP/1.1\r\nHost: {self.srv.host}\r\n"
            f"Authorization: {auth}\r\nContent-Type: audio/wav\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"X-MindClip-Filename: 20260827_091500.wav\r\n"
            f"X-MindClip-Sha256: {hashlib.sha256(body).hexdigest()}\r\n"
            f"X-MindClip-Bytes: {len(body)}\r\n\r\n"
        ).encode("ascii") + sent
        sock = socket.create_connection((self.srv.host, self.srv.port), timeout=15)
        try:
            sock.sendall(raw)
            sock.shutdown(socket.SHUT_WR)  # 送信途中で切れた状態
            resp = b""
            while b"\r\n\r\n" not in resp:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                resp += chunk
        finally:
            sock.close()
        self.assertIn(b"400", resp.split(b"\r\n")[0])
        self.assertEqual(self.inbox_names(), [])  # .part も .wav も残さない

    def test_content_length_and_declared_bytes_must_match(self):
        body = wav_bytes()
        status, resp = self.srv.post_wav(body, "20260827_091500.wav",
                                         **{"X-MindClip-Bytes": len(body) + 1})
        self.assertEqual(status, 400)
        self.assertIn("不一致", resp["error"])
        self.assertEqual(self.inbox_names(), [])

    def test_sha256_mismatch_is_400_not_401(self):
        """SDの読み出しがぶれて「宣言sha ≠ 実ボディ」になった場合。

        署名自体は正しい（デバイスは自分が計算した sha で署名する）ので、
        これは認証エラー(401)ではなく**そのファイル固有の 400**でなければならない。
        401 にするとデバイスは E6＝設定不正とみなしてセッション全体を中止する（SPEC §7）。
        """
        body = wav_bytes(seed=5)
        wrong = hashlib.sha256(b"something else").hexdigest()
        headers = {
            "Content-Length": str(len(body)),
            "X-MindClip-Filename": "20260827_091500.wav",
            "X-MindClip-Sha256": wrong,
            "X-MindClip-Bytes": str(len(body)),
        }
        status, resp = self.srv.request("POST", "/api/v1/ingest", body=body, headers=headers,
                                        sign_sha=wrong)
        self.assertEqual(status, 400)
        self.assertIn("sha256", resp["error"])
        self.assertEqual(self.inbox_names(), [])

    def test_missing_sha256_header_is_rejected(self):
        body = wav_bytes()
        headers = {"Content-Length": str(len(body)),
                   "X-MindClip-Filename": "20260827_091500.wav"}
        status, _ = self.srv.request("POST", "/api/v1/ingest", body=body, headers=headers)
        self.assertEqual(status, 400)


class TestLimits(IngestTestBase):
    ingest_kwargs = {"max_bytes": 4096}

    def test_oversize_body_returns_413(self):
        body = wav_bytes(seconds=1.0)
        self.assertGreater(len(body), 4096)
        status, _ = self.srv.post_wav(body, "20260827_091500.wav")
        self.assertEqual(status, 413)
        self.assertEqual(self.inbox_names(), [])


class TestDiskFull(IngestTestBase):
    ingest_kwargs = {"min_free_bytes": 1 << 62}

    def test_no_space_returns_507(self):
        status, _ = self.srv.post_wav(wav_bytes(), "20260827_091500.wav")
        self.assertEqual(status, 507)
        self.assertEqual(self.inbox_names(), [])


class TestDuplicates(IngestTestBase):
    def test_same_name_different_content_gets_sequence_suffix(self):
        a, b = wav_bytes(seed=6), wav_bytes(seed=7)
        self.assertNotEqual(a, b)
        s1, r1 = self.srv.post_wav(a, "20260827_091500.wav")
        s2, r2 = self.srv.post_wav(b, "20260827_091500.wav")
        self.assertEqual((s1, s2), (200, 200))
        self.assertEqual(r1["stored_name"], "20260827_091500.wav")
        self.assertEqual(r2["stored_name"], "20260827_091500_1.wav")
        self.assertEqual(self.inbox_names(), ["20260827_091500.wav", "20260827_091500_1.wav"])
        self.assertEqual((self.srv.inbox / r1["stored_name"]).read_bytes(), a)
        self.assertEqual((self.srv.inbox / r2["stored_name"]).read_bytes(), b)
        for name in self.inbox_names():  # 連番付きでも timeparse は先頭一致で解釈できる
            self.assertEqual(parse_start_time(self.srv.inbox / name)[1], "filename")

    def test_resend_of_same_bytes_is_idempotent(self):
        """ACKを取りこぼしたデバイスの再送。二重保存せず duplicate:true を返す。"""
        body = wav_bytes(seed=8)
        s1, r1 = self.srv.post_wav(body, "20260827_091500.wav")
        s2, r2 = self.srv.post_wav(body, "20260827_091500.wav")
        self.assertEqual((s1, s2), (200, 200))
        self.assertFalse(r1["duplicate"])
        self.assertTrue(r2["duplicate"])
        self.assertEqual(r2["stored_name"], r1["stored_name"])
        self.assertEqual(self.inbox_names(), ["20260827_091500.wav"])

    def test_already_processed_by_phase0_is_duplicate(self):
        """Phase 0 が処理して archive へ移した後の再送も duplicate:true（デバイスは消してよい）。"""
        body = wav_bytes(seed=9)
        s1, r1 = self.srv.post_wav(body, "20260827_091500.wav")
        self.assertEqual(s1, 200)
        (self.srv.inbox / r1["stored_name"]).unlink()  # pipeline がアーカイブした状況を再現
        s2, r2 = self.srv.post_wav(body, "20260827_091500.wav")
        self.assertEqual(s2, 200)
        self.assertTrue(r2["duplicate"])
        self.assertEqual(self.inbox_names(), [])


class TestKeepAliveSession(IngestTestBase):
    def test_multiple_files_over_one_connection(self):
        """デバイスは1本のコネクションを使い回す（SPEC §6.5）。"""
        conn = http.client.HTTPConnection(self.srv.host, self.srv.port, timeout=15)
        try:
            names = []
            for i in range(3):
                body = wav_bytes(seed=20 + i)
                headers = {
                    "Content-Type": "audio/wav",
                    "Content-Length": str(len(body)),
                    "X-MindClip-Filename": f"2026082{i}_091500.wav",
                    "X-MindClip-Sha256": hashlib.sha256(body).hexdigest(),
                    "X-MindClip-Bytes": str(len(body)),
                    "Authorization": build_authorization(KEY, "POST", "/api/v1/ingest",
                                                         DEVICE, body),
                }
                conn.request("POST", "/api/v1/ingest", body=body, headers=headers)
                resp = conn.getresponse()
                payload = json.loads(resp.read())
                self.assertEqual(resp.status, 200, payload)
                names.append(payload["stored_name"])
        finally:
            conn.close()
        self.assertEqual(sorted(names), self.inbox_names())


class TestErrorsAreDeliverable(IngestTestBase):
    """413 / 507 / 400 を「デバイスが実際に読める」こと。

    ボディを読まずに応答して切ると、送信中のデバイスからは EPIPE（送信失敗）にしか
    見えず、413/507 の意味が伝わらない。上限内なら読み捨ててから応答する。
    """

    ingest_kwargs = {"max_bytes": 4096}

    def _post(self, conn, body, name, headers=None):
        h = {
            "Content-Type": "audio/wav",
            "Content-Length": str(len(body)),
            "X-MindClip-Filename": name,
            "X-MindClip-Sha256": hashlib.sha256(body).hexdigest(),
            "X-MindClip-Bytes": str(len(body)),
            "Authorization": build_authorization(KEY, "POST", "/api/v1/ingest", DEVICE, body),
        }
        h.update(headers or {})
        conn.request("POST", "/api/v1/ingest", body=body, headers=h)
        resp = conn.getresponse()
        return resp.status, json.loads(resp.read())

    def test_413_is_readable_and_session_continues(self):
        conn = http.client.HTTPConnection(self.srv.host, self.srv.port, timeout=15)
        try:
            big = wav_bytes(seconds=1.0)  # > max_bytes
            self.assertGreater(len(big), 4096)
            status, resp = self._post(conn, big, "20260827_091500.wav")
            self.assertEqual(status, 413)
            self.assertIn("上限", resp["error"])
            # 同じコネクションで次のファイルが送れる（keep-alive が生き残っている）
            small = wav_bytes(seconds=0.05)
            status, resp = self._post(conn, small, "20260827_092000.wav")
            self.assertEqual(status, 200, resp)
        finally:
            conn.close()
        self.assertEqual(self.inbox_names(), ["20260827_092000.wav"])

    def test_400_does_not_kill_the_connection(self):
        conn = http.client.HTTPConnection(self.srv.host, self.srv.port, timeout=15)
        try:
            body = wav_bytes(seconds=0.05)
            status, _ = self._post(conn, body, "20260827_091500.wav",
                                   headers={"X-MindClip-Bytes": str(len(body) + 1)})
            self.assertEqual(status, 400)
            status, resp = self._post(conn, wav_bytes(seconds=0.05, seed=2),
                                      "20260827_092000.wav")
            self.assertEqual(status, 200, resp)
        finally:
            conn.close()


class TestDiskFullIsReadable(IngestTestBase):
    ingest_kwargs = {"min_free_bytes": 1 << 62}

    def test_507_carries_a_reason(self):
        status, resp = self.srv.post_wav(wav_bytes(), "20260827_091500.wav")
        self.assertEqual(status, 507)
        self.assertIn("空き容量", resp["error"])
        self.assertEqual(self.inbox_names(), [])


class TestStartupCleanup(IngestTestBase):
    def test_stale_part_files_are_removed_on_start(self):
        """SIGKILL などで残った .part を起動時に掃除する（放置すると容量だけ食う）。"""
        stale = self.srv.inbox / ".ingest-deadbeef.wav.part"
        stale.write_bytes(b"\x00" * 1024)
        keep = self.srv.inbox / "20260827_091500.wav"
        keep.write_bytes(wav_bytes())
        svc = self.srv.server.service
        self.assertEqual(svc.cleanup_stale_parts(), 1)
        self.assertFalse(stale.exists())
        self.assertTrue(keep.exists())  # 本物の録音には触らない


class TestPathHints(IngestTestBase):
    def test_double_slash_path_explains_the_trailing_slash(self):
        """srv.url に末尾スラッシュを入れた場合（`https://host:8443/`）の 404 を分かるようにする。"""
        status, resp = self.srv.request("GET", "//api/v1/time")
        self.assertEqual(status, 404)
        self.assertIn("srv.url", resp["error"])

    def test_unknown_path_is_still_plain_404(self):
        status, resp = self.srv.request("GET", "/api/v1/nope")
        self.assertEqual(status, 404)
        self.assertNotIn("srv.url", resp["error"])


@unittest.skipUnless(shutil.which("openssl"), "openssl が必要")
class TestMutualTLS(unittest.TestCase):
    """mTLS: プライベートCAでクライアント証明書を検証する（証明書が無ければ接続を張れない）。"""

    @classmethod
    def setUpClass(cls):
        cls._dir = tempfile.TemporaryDirectory()
        d = Path(cls._dir.name)
        cls.d = d

        def run(*args):
            subprocess.run(["openssl", *args], check=True, capture_output=True)

        run("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
            "-subj", "/CN=MindClip Test CA", "-keyout", str(d / "ca.key"),
            "-out", str(d / "ca.crt"))
        for who, cn in (("server", "127.0.0.1"), ("client", DEVICE)):
            run("req", "-newkey", "rsa:2048", "-nodes",
                "-subj", f"/CN={cn}", "-keyout", str(d / f"{who}.key"),
                "-out", str(d / f"{who}.csr"))
            ext = d / f"{who}.ext"
            ext.write_text("subjectAltName=IP:127.0.0.1\n" if who == "server"
                           else "extendedKeyUsage=clientAuth\n")
            run("x509", "-req", "-in", str(d / f"{who}.csr"), "-CA", str(d / "ca.crt"),
                "-CAkey", str(d / "ca.key"), "-CAcreateserial", "-days", "1",
                "-extfile", str(ext), "-out", str(d / f"{who}.crt"))

    @classmethod
    def tearDownClass(cls):
        cls._dir.cleanup()

    def setUp(self):
        self._work = tempfile.TemporaryDirectory()
        work = Path(self._work.name)
        self.srv = ServerFixture(
            work, allow_plaintext=False, require_mtls=True,
            tls_cert=str(self.d / "server.crt"), tls_key=str(self.d / "server.key"),
            client_ca=str(self.d / "ca.crt"), cert_cn_must_match_device=True,
        )
        self.addCleanup(self.srv.close)
        self.addCleanup(self._work.cleanup)

    def _client_ctx(self, with_cert: bool):
        ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=str(self.d / "ca.crt"))
        if with_cert:
            ctx.load_cert_chain(str(self.d / "client.crt"), str(self.d / "client.key"))
        return ctx

    def test_client_certificate_accepted(self):
        status, body = self.srv.request("GET", "/api/v1/time",
                                        ssl_context=self._client_ctx(with_cert=True))
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])

    def test_connection_without_client_certificate_fails(self):
        with self.assertRaises(ssl.SSLError):
            self.srv.request("GET", "/api/v1/time",
                             ssl_context=self._client_ctx(with_cert=False))

    def test_mtls_still_requires_shared_secret(self):
        status, _ = self.srv.request("GET", "/api/v1/time", key=None,
                                     ssl_context=self._client_ctx(with_cert=True))
        self.assertEqual(status, 401)

    def test_mtls_requires_client_ca_when_enabled(self):
        work = Path(self._work.name)
        cfg = Config(
            paths=PathsConfig(inbox=work / "i", archive=work / "a", state=work / "s",
                              obsidian_vault=work / "v"),
            ingest=IngestConfig(host="127.0.0.1", port=0, hmac_key_hex=KEY.hex(),
                                tls_cert=str(self.d / "server.crt"),
                                tls_key=str(self.d / "server.key"), require_mtls=True),
        )
        with self.assertRaises(RuntimeError):
            build_server(cfg)


class TestInternalErrors(IngestTestBase):
    """想定外の例外は 500 で返す（応答を返さずに接続を切らない）。

    返さずに切ると、デバイスからは「サーバ応答なし」＝一時障害に見えて
    SPEC §7 E5 でセッション全体が中止される。原因が恒久的だと毎晩全件が送れず、
    最後はSDが埋まって E2＝録音停止になる（データは消えないが録音が止まる）。
    """

    def test_rename_failure_returns_500_and_leaves_no_part(self):
        real_rename = ingest_mod.os.rename

        def boom(src, dst):
            raise OSError(28, "No space left on device")

        ingest_mod.os.rename = boom
        self.addCleanup(setattr, ingest_mod.os, "rename", real_rename)
        with self.assertLogs("voice_logger", level="ERROR"):
            status, resp = self.srv.post_wav(wav_bytes(), "20260827_091500.wav")
        self.assertEqual(status, 500)
        self.assertFalse(resp["ok"])
        self.assertEqual(self.inbox_names(), [])          # .part も残さない

    def test_server_survives_and_answers_the_next_request(self):
        """500 を返した後もサーバは生きていて、次のファイルは普通に受かる。"""
        real_rename = ingest_mod.os.rename
        ingest_mod.os.rename = lambda src, dst: (_ for _ in ()).throw(OSError("boom"))
        with self.assertLogs("voice_logger", level="ERROR"):
            first, _ = self.srv.post_wav(wav_bytes(seed=21), "20260827_091500.wav")
        ingest_mod.os.rename = real_rename
        second, resp = self.srv.post_wav(wav_bytes(seed=22), "20260827_091501.wav")
        self.assertEqual((first, second), (500, 200))
        self.assertEqual(resp["stored_name"], "20260827_091501.wav")

    def test_ledger_write_failure_still_acks(self):
        """台帳の書込に失敗しても 200 を返す（ファイルは既に inbox にあるため）。

        ここで 500 にするとデバイスが再送し、台帳が空なので重複判定も効かず
        inbox に同じ音声が2本並ぶ。台帳は再送回収の最適化にすぎない。
        """
        svc = self.srv.server.service

        def boom(digest, entry):
            raise OSError("ledger is read-only")

        svc.ledger.record = boom
        with self.assertLogs("voice_logger", level="ERROR"):
            status, resp = self.srv.post_wav(wav_bytes(seed=23), "20260827_091500.wav")
        self.assertEqual(status, 200)
        self.assertEqual(self.inbox_names(), ["20260827_091500.wav"])


class TestStoredNameParsing(IngestTestBase):
    def test_double_sequence_suffix_keeps_the_recording_time(self):
        """`_99_1`（SD側の連番とサーバ側の連番が重なった名前）でも録音時刻を捨てない。"""
        s1, r1 = self.srv.post_wav(wav_bytes(seed=31), "20260827_091500_99_1.wav")
        self.assertEqual(s1, 200)
        self.assertTrue(r1["stored_name"].startswith("20260827_091500"))
        self.assertEqual(
            parse_start_time(self.srv.inbox / r1["stored_name"]),
            (datetime(2026, 8, 27, 9, 15, 0), "filename"),
        )

    def test_retry_suffix_from_the_device_keeps_the_recording_time(self):
        """SPEC §6.3 E16 のカウンタ用サフィックス（`.wav.b1` / `.wav.b2`）を落として解釈する。"""
        for i, suffix in enumerate((".wav.b1", ".wav.b2", ".wav.rec")):
            status, resp = self.srv.post_wav(wav_bytes(seed=40 + i), "20260827_091500" + suffix)
            self.assertEqual(status, 200)
            self.assertTrue(resp["stored_name"].startswith("20260827_091500"), resp)
            self.assertTrue(resp["stored_name"].endswith(".wav"), resp)

    def test_garbage_name_still_falls_back_to_server_now(self):
        with self.assertLogs("voice_logger", level="WARNING"):
            status, resp = self.srv.post_wav(wav_bytes(seed=32), "memo-3.wav")
        self.assertEqual(status, 200)
        self.assertRegex(resp["stored_name"], r"^\d{8}_\d{6}(_\d+)?\.wav$")


class TestReceiptLedger(unittest.TestCase):
    """台帳は追記型（1件あたりのコストが件数に依存しない）。"""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.state = Path(self._dir.name)
        self.addCleanup(self._dir.cleanup)

    def test_record_appends_one_line_and_survives_restart(self):
        led = ReceiptLedger(self.state, limit=1000)
        for i in range(50):
            led.record(f"{i:064x}", {"stored_name": f"f{i}.wav", "bytes": i})
        led.close()
        lines = led.path.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 50)
        again = ReceiptLedger(self.state, limit=1000)
        self.assertEqual(again.lookup(f"{7:064x}")["stored_name"], "f7.wav")
        self.assertIsNone(again.lookup("ff" * 32))
        again.close()

    def test_cost_per_record_does_not_grow_with_size(self):
        """全体書き直し方式だと 20000 件で1件 100ms 超になっていた退行を防ぐ。"""
        led = ReceiptLedger(self.state, limit=20000)
        entry = {"stored_name": "20260827_091500.wav", "device": DEVICE, "bytes": 1920044,
                 "received_at": "2026-08-27T09:16:00", "original_name": "x.wav",
                 "name_basis": "filename", "duration_ms": "60000"}
        t0 = time.perf_counter()
        for i in range(200):
            led.record(f"{i:064x}", entry)
        early = (time.perf_counter() - t0) / 200
        for i in range(200, 5000):
            led.record(f"{i:064x}", entry)
        t1 = time.perf_counter()
        for i in range(5000, 5200):
            led.record(f"{i:064x}", entry)
        late = (time.perf_counter() - t1) / 200
        led.close()
        self.assertLess(late, 0.020, "1件あたり20msを超えるなら追記型になっていない")
        self.assertLess(late, early * 5 + 0.005)  # 件数に対してほぼ一定

    def test_compaction_keeps_the_file_bounded(self):
        """行数が `max(2*limit, 1000)` を超えたら圧縮する（無限に伸びない）。"""
        led = ReceiptLedger(self.state, limit=600)
        for i in range(4000):
            led.record(f"{i:064x}", {"stored_name": f"f{i}.wav"})
        led.close()
        lines = led.path.read_text(encoding="utf-8").strip().splitlines()
        self.assertLessEqual(len(lines), 2 * 600 + 1)
        again = ReceiptLedger(self.state, limit=600)
        self.assertEqual(again.lookup(f"{3999:064x}")["stored_name"], "f3999.wav")
        self.assertIsNone(again.lookup(f"{0:064x}"))   # 古い分は押し出されている
        again.close()

    def test_broken_tail_line_is_skipped(self):
        """追記の途中で電源が落ちた最終行を読み飛ばして起動できる。"""
        led = ReceiptLedger(self.state, limit=100)
        led.record("aa" * 32, {"stored_name": "ok.wav"})
        led.close()
        with open(led.path, "a", encoding="utf-8") as f:
            f.write('{"sha256": "bb')     # 途中で切れた行
        with self.assertLogs("voice_logger", level="WARNING"):
            again = ReceiptLedger(self.state, limit=100)
        self.assertEqual(again.lookup("aa" * 32)["stored_name"], "ok.wav")
        again.close()

    def test_legacy_json_ledger_is_migrated(self):
        legacy = self.state / "ingest_receipts.json"
        legacy.write_text(json.dumps({"cc" * 32: {"stored_name": "old.wav"}}), encoding="utf-8")
        led = ReceiptLedger(self.state, limit=100)
        self.assertEqual(led.lookup("cc" * 32)["stored_name"], "old.wav")
        self.assertFalse(legacy.exists())
        self.assertTrue((self.state / "ingest_receipts.json.migrated").exists())
        led.close()
        self.assertEqual(ReceiptLedger(self.state).lookup("cc" * 32)["stored_name"], "old.wav")


if __name__ == "__main__":
    unittest.main()
