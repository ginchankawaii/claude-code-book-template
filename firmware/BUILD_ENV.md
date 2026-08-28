# コンパイル検証環境（動作確認済み・2026-08-28）

## 使い方
```sh
SP=/tmp/claude-0/-home-user-claude-code-book-template/a0987823-e1ef-5733-8f68-0fdc6df5afdd/scratchpad
export ARDUINO_DIRECTORIES_DATA=$SP/acli-data ARDUINO_DIRECTORIES_USER=$SP/acli-user
# PSRAM は既定が disabled（boards.txt の PSRAM メニュー先頭）。
# 既定のままだと ps_malloc(1.92MB) が NULL を返し、書込バッファが5秒へ縮退して
# 省電力要件2（30〜60秒ためてまとめ書き）を満たせない。必ず PSRAM=opi を付けること。
$SP/arduino-cli compile --fqbn esp32:esp32:XIAO_ESP32S3:PSRAM=opi <スケッチのディレクトリ>

# PSRAM 無しの縮退動作を確認したいときだけ:
# $SP/arduino-cli compile --fqbn esp32:esp32:XIAO_ESP32S3 <スケッチのディレクトリ>
```

### 警告を確認するときは必ず `-v` を付けること（偽陰性の罠）
arduino-cli 1.2.2 は **`-v` が無いとコンパイラの警告を1行も表示しない**。
`--warnings all` だけを付けて「warning 0件」と読んでも、それは表示されていないだけである
（vad.cpp に未使用変数を注入した probe ビルドで確認済み: `-v` 付きのときだけ警告が出た）。
```sh
$SP/arduino-cli compile -v --warnings all --fqbn esp32:esp32:XIAO_ESP32S3:PSRAM=opi <スケッチのディレクトリ>
```
この構成では `-Wall -Wextra -Werror=return-type` が適用される。
現行コードは `PSRAM=opi` / 非PSRAM の両構成とも警告 **0件**（2026-08-28 確認）。
esp32:esp32@3.3.11 / ボード FQBN は `esp32:esp32:XIAO_ESP32S3:PSRAM=opi`（実機用）。
SD / ESP_I2S / WiFi / Preferences / driver/rtc_io.h すべて解決済み。

## 【重要】.ino に**関数定義**を書かないこと

この環境の ctags は Arduino 公式フォークではないため、arduino-cli が
.ino から生成する関数プロトタイプの**戻り値の型が欠落**し
（` setup();` になる）、必ずコンパイルエラーになる。

壊れたプロトタイプ生成が発火するのは **.ino 内の「関数定義」に対してだけ**なので、
ルールの正しい表現は「コメントのみにする」ではなく **「.ino に関数定義を書かない」** である
（`#include "app.h"` のような非コメント行は無害でビルドは通る。確認済み）。

**回避策（成果物の構造としてもこれを採用する）**:
- `mindclip.ino` はコメントと `#include` だけにする（**関数定義を置かない**）
- `setup()` / `loop()` を含む全実装を **`.cpp` / `.h`** に置く
- .cpp は通常のC++としてコンパイルされ前処理を受けないため問題が起きない
- Arduino IDE でも同じ構造でそのままビルドできる（利用者側に不利益なし）

実際の構成（`PSRAM=opi` で Flash 33% / RAM 16%、警告0件）:
```
mindclip/
  mindclip.ino   ← コメントと #include "app.h" のみ（関数定義なし）
  app.cpp/.h     ← setup()/loop() と状態機械
  recorder.cpp/.h  vad.cpp/.h  syncer.cpp/.h
  settings.cpp/.h  rtcclock.cpp/.h  led.cpp/.h  provision.cpp/.h
  config.h       ← ピン・定数・NVS構造体
```
