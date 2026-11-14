"""inbox の常駐監視（`voice-logger watch` の中身）。

1回のスキャンでやること:

  1. 書き込みが終わったファイルだけを選ぶ（`stable_files`）
  2. 再試行待ちのファイルは飛ばす（`FailureLog`）
  3. 処理する。失敗は2種類に分けて扱う
       * ServiceUnavailable … Ollama 不通・モデル未取得・vault に書けない等。
         ファイルの失敗には数えず、全体を待たせて間隔を伸ばしながら再試行する
       * それ以外            … そのファイルの失敗として数え、指数バックオフ。
         `max_failures` 回で隔離ディレクトリへ移す
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from .config import Config
from .errors import ServiceUnavailable
from .pipeline import (
    FailureLog, Manifest, file_sha256, iter_audio_files, process_file, quarantine_audio,
)

logger = logging.getLogger("voice_logger")

# サービス側の障害時に全体を待たせる間隔（倍々に伸ばす）
SERVICE_RETRY_BASE_SEC = 30
SERVICE_RETRY_MAX_SEC = 300

# (サイズ, mtime_ns, その状態を最初に見た時刻)
_Seen = tuple[int, int, float]


def _readable_now(path: Path) -> bool:
    """他プロセスが書き込み用に掴んでいないかを、OSが教えてくれる範囲で確かめる。

    Windows はコピー中のファイルを共有違反で弾くので、読み書き両用で開けるかを見る
    （読み取り専用属性のファイルは書き込みで開けなくて当然なので、読めればよしとする）。
    POSIX には強制ロックが無く、検出できるのは「そもそも読めない」ことだけ。
    """
    try:
        if os.name == "nt" and os.access(path, os.W_OK):
            with open(path, "r+b"):
                return True
        with open(path, "rb") as f:
            f.read(1)
        return True
    except OSError:
        return False


def stable_files(
    inbox: Path, pending: dict[Path, _Seen], min_age_sec: float, now: float | None = None,
) -> list[Path]:
    """コピー途中のファイルを掴まないよう、書き込みが終わったと見なせるものだけ返す。

    条件は「前回のスキャンからサイズも mtime も変わっていない」かつ「最後の変更から
    `min_age_sec` 以上たっている」。サイズだけを見ると、領域を先に確保してから書く
    コピーや、途中で止まった転送を完了と見誤る。経過時間は mtime で測るが、送り元の
    時計がずれて mtime が未来にあるファイルを永久に待たないよう、自分がその状態を
    観測し続けた時間でも満たせる。
    """
    now = time.time() if now is None else now
    current: dict[Path, _Seen] = {}
    ready = []
    for path in iter_audio_files(inbox):
        try:
            st = path.stat()
        except OSError:  # 列挙した直後に消えた・移動された
            continue
        previous = pending.get(path)
        unchanged = previous is not None and previous[:2] == (st.st_size, st.st_mtime_ns)
        first_seen = previous[2] if unchanged else now
        current[path] = (st.st_size, st.st_mtime_ns, first_seen)
        aged = (now - st.st_mtime >= min_age_sec) or (now - first_seen >= min_age_sec)
        if unchanged and aged and _readable_now(path):
            ready.append(path)
    pending.clear()
    pending.update(current)
    return ready


class Watcher:
    def __init__(self, cfg: Config, manifest: Manifest, interval: float) -> None:
        self.cfg = cfg
        self.manifest = manifest
        self.failures = FailureLog(cfg.paths.state, cfg.watch)
        configured = cfg.watch.min_age_sec
        self.min_age_sec = configured if configured >= 0 else 2 * interval
        self._pending: dict[Path, _Seen] = {}
        # (パス, サイズ, mtime_ns) → sha256。待機中のファイルを毎スキャン読み直さない
        self._digests: dict[tuple[Path, int, int], str] = {}
        self._service_delay = 0.0
        self._service_retry_at = 0.0
        self.clock = time.time  # テストで時間を進められるよう差し替え可能にしてある

    def _digest(self, path: Path) -> str | None:
        try:
            st = path.stat()
            key = (path, st.st_size, st.st_mtime_ns)
            if key not in self._digests:
                self._digests[key] = file_sha256(path)
            return self._digests[key]
        except OSError:
            return None

    def _forget_missing(self, present: list[Path]) -> None:
        alive = set(present)
        for key in [k for k in self._digests if k[0] not in alive]:
            del self._digests[key]

    def _service_down(self, exc: ServiceUnavailable) -> None:
        self._service_delay = min(
            max(SERVICE_RETRY_BASE_SEC, self._service_delay * 2), SERVICE_RETRY_MAX_SEC)
        self._service_retry_at = self.clock() + self._service_delay
        logger.error("%s", exc)
        logger.error("inbox のファイルはそのまま残し、%d 秒後に再試行します", self._service_delay)

    def _file_failed(self, path: Path, digest: str, exc: Exception) -> None:
        now = self.clock()  # 処理に何分もかかった後なので、スキャン開始時刻は使わない
        if not path.exists():
            # 数える対象がもう inbox に無い。処理中に消されたか、アーカイブへ移した後の
            # 工程（台帳への記録）で失敗したかのどちらか
            if isinstance(exc, FileNotFoundError):
                logger.info("処理中にファイルが無くなりました（移動・削除）: %s", path.name)
            else:
                logger.error("処理の途中で失敗しました（ファイルは既に inbox にありません）: %s",
                             path.name, exc_info=exc)
            return
        count = self.failures.record(digest, path.name, f"{type(exc).__name__}: {exc}", now)
        if count < self.cfg.watch.max_failures:
            wait = self.failures.next_retry(digest) - now
            logger.error("処理失敗 (%d/%d 回目、%d 秒後に再試行): %s",
                         count, self.cfg.watch.max_failures, wait, path, exc_info=exc)
            return
        try:
            dest = quarantine_audio(self.cfg, path)
        except OSError:
            logger.exception("隔離ディレクトリへ移動できませんでした（次回また試みます）: %s", path)
            return
        self.failures.clear(digest)
        logger.error(
            "%d 回失敗したため隔離しました: %s → %s（最後のエラー: %s）。"
            "原因を直してから inbox に戻すと再処理されます",
            count, path.name, dest, exc, exc_info=exc)

    def scan_once(self) -> None:
        now = self.clock()
        ready = stable_files(self.cfg.paths.inbox, self._pending, self.min_age_sec, now)
        self._forget_missing(list(self._pending))
        if now < self._service_retry_at:
            return
        for path in ready:
            digest = self._digest(path)
            if digest is None or not self.failures.due(digest, now):
                continue
            try:
                process_file(self.cfg, path, self.manifest, digest=digest,
                             retire_duplicates=True)
            except ServiceUnavailable as exc:
                self._service_down(exc)
                return
            except Exception as exc:  # noqa: BLE001 — 1本の失敗で常駐を止めない
                self._file_failed(path, digest, exc)
            else:
                self._service_delay = 0.0
                self.failures.clear(digest)
