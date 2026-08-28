"""`src` レイアウトの保険。

`pyproject.toml` の `[tool.pytest.ini_options] pythonpath` は pytest 7 以降でしか
効かないので、古い pytest でも `import voice_logger` が通るようにここでも sys.path に足す。
（`python -m unittest discover tests` は conftest.py を読まないので、
そちらは従来どおり `PYTHONPATH=src` を付けること。）
"""

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
