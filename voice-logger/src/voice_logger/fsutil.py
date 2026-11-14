"""状態ファイル・ノートを壊さないためのファイル操作（標準ライブラリのみ）。

  * `atomic_write_text` … 同じディレクトリの一時ファイルに書いて fsync → `os.replace`。
    途中で落ちても「古い内容」か「新しい内容」のどちらかが必ず残る
  * `FileLock`          … `O_EXCL` で作るロックファイル。fcntl/msvcrt に依存しないので
    Linux / Windows / バインドマウント越しのどれでも同じ動きをする
"""

from __future__ import annotations

import errno
import os
import time
from pathlib import Path

# Windows では相手（Obsidian・ウイルス対策・同期ソフト）がファイルを開いている間、
# 上書き rename が一時的に拒否される。バインドマウント越しだと EBUSY で見えることもある
_BUSY_ERRNOS = {errno.EACCES, errno.EPERM, errno.EBUSY}


def fsync_dir(path: Path) -> None:
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:  # Windows などディレクトリを開けない環境では何もしない
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def is_busy_error(exc: OSError) -> bool:
    """「今は誰かが掴んでいるだけ」で、少し待てば通る見込みのある失敗か。"""
    return isinstance(exc, PermissionError) or exc.errno in _BUSY_ERRNOS


def write_synced(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())


def replace_with_retry(tmp: Path, path: Path, attempts: int = 5, delay_sec: float = 0.2) -> None:
    """`os.replace` を、相手が掴んでいる間だけ短く待って再試行する。だめなら例外を上げる。"""
    for attempt in range(attempts):
        try:
            os.replace(tmp, path)
            return
        except OSError as exc:
            if not is_busy_error(exc) or attempt == attempts - 1:
                raise
            time.sleep(delay_sec * (attempt + 1))


def temp_sibling(path: Path) -> Path:
    # 先頭ドットにしておくと Obsidian / iter_audio_files / Syncthing の既定設定が無視する
    return path.with_name(f".{path.name}.{os.getpid()}.tmp")


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = temp_sibling(path)
    try:
        write_synced(tmp, text)
        replace_with_retry(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)  # 成功時は rename 済みなので何もしない
    fsync_dir(path.parent)


class FileLock:
    """プロセス間の排他（`with FileLock(path):`）。

    ロックを持ったまま強制終了されると残骸が残るので、`stale_sec` より古いロックは
    奪う。守る区間は「読み直して書き戻す」だけの短い処理に限ること。
    """

    def __init__(self, path: Path, timeout_sec: float = 10.0, stale_sec: float = 30.0) -> None:
        self.path = path
        self.timeout_sec = timeout_sec
        self.stale_sec = stale_sec

    def _break_if_stale(self) -> None:
        try:
            age = time.time() - self.path.stat().st_mtime
        except OSError:
            return
        if age > self.stale_sec:
            try:
                self.path.unlink()
            except OSError:
                pass

    def __enter__(self) -> "FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout_sec
        while True:
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                pass
            except OSError as exc:
                # Windows では削除途中のファイルに対する作成が一時的に拒否される
                if not is_busy_error(exc):
                    raise
            else:
                os.write(fd, str(os.getpid()).encode("ascii"))
                os.close(fd)
                return self
            self._break_if_stale()
            if time.monotonic() > deadline:
                raise TimeoutError(f"ロックを取得できません: {self.path}")
            time.sleep(0.05)

    def __exit__(self, *exc_info) -> None:
        try:
            self.path.unlink()
        except OSError:
            pass
