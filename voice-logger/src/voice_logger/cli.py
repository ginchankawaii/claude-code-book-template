"""コマンドラインインターフェース。

  voice-logger process <ファイル/ディレクトリ...>   指定音声を処理
  voice-logger watch                                inbox を監視して自動処理
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from .config import Config, find_config_path, load_config
from .pipeline import Manifest, iter_audio_files, process_file

logger = logging.getLogger("voice_logger")


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )


def _load(args) -> Config:
    return load_config(find_config_path(args.config))


def cmd_process(args) -> int:
    cfg = _load(args)
    manifest = Manifest(cfg.paths.state)
    files: list[Path] = []
    for target in args.targets:
        files.extend(iter_audio_files(Path(target).expanduser()))
    if not files:
        logger.warning("対象の音声ファイルがありません")
        return 1
    processed = 0
    for path in files:
        try:
            if process_file(cfg, path, manifest, dry_run=args.dry_run):
                processed += 1
        except Exception:
            logger.exception("処理失敗（次のファイルへ進みます）: %s", path)
    logger.info("%d/%d 件を処理しました", processed, len(files))
    return 0


def _stable_files(inbox: Path, pending: dict[Path, int]) -> list[Path]:
    """コピー途中のファイルを掴まないよう、2回のスキャンでサイズ不変のものだけ返す。"""
    ready = []
    current = {p: p.stat().st_size for p in iter_audio_files(inbox)}
    for path, size in current.items():
        if pending.get(path) == size:
            ready.append(path)
    pending.clear()
    pending.update(current)
    return ready


def cmd_watch(args) -> int:
    cfg = _load(args)
    cfg.paths.inbox.mkdir(parents=True, exist_ok=True)
    manifest = Manifest(cfg.paths.state)
    logger.info("inbox を監視中: %s（%d秒間隔、Ctrl-Cで終了）", cfg.paths.inbox, args.interval)
    pending: dict[Path, int] = {}
    while True:
        try:
            for path in _stable_files(cfg.paths.inbox, pending):
                try:
                    process_file(cfg, path, manifest)
                except Exception:
                    logger.exception("処理失敗: %s", path)
            time.sleep(args.interval)
        except KeyboardInterrupt:
            logger.info("終了します")
            return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="voice-logger",
        description="ローカル完結型・音声ライフログパイプライン (Phase 0)",
    )
    parser.add_argument("--config", help="設定ファイル(TOML)のパス")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p_process = sub.add_parser("process", help="音声ファイル/ディレクトリを処理")
    p_process.add_argument("targets", nargs="+", help="音声ファイルまたはディレクトリ")
    p_process.add_argument(
        "--dry-run", action="store_true",
        help="ノート追記・アーカイブせず、生成されるMarkdownを表示",
    )
    p_process.set_defaults(func=cmd_process)

    p_watch = sub.add_parser("watch", help="inbox を監視して自動処理")
    p_watch.add_argument("--interval", type=int, default=30, help="スキャン間隔（秒）")
    p_watch.set_defaults(func=cmd_watch)

    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
