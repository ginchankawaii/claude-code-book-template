# コンパイル検証環境（動作確認済み・2026-08-28）

## 使い方
```sh
SP=/tmp/claude-0/-home-user-claude-code-book-template/a0987823-e1ef-5733-8f68-0fdc6df5afdd/scratchpad
export ARDUINO_DIRECTORIES_DATA=$SP/acli-data ARDUINO_DIRECTORIES_USER=$SP/acli-user
$SP/arduino-cli compile --fqbn esp32:esp32:XIAO_ESP32S3 <スケッチのディレクトリ>
```
esp32:esp32@3.3.11 / ボード FQBN は `esp32:esp32:XIAO_ESP32S3`。
SD / ESP_I2S / WiFi / Preferences / driver/rtc_io.h すべて解決済み。

## 【重要】.ino に関数を書かないこと

この環境の ctags は Arduino 公式フォークではないため、arduino-cli が
.ino から生成する関数プロトタイプの**戻り値の型が欠落**し
（` setup();` になる）、必ずコンパイルエラーになる。

**回避策（成果物の構造としてもこれを採用する）**:
- `mindclip.ino` は**コメントだけの薄いファイル**にする
- `setup()` / `loop()` を含む全実装を **`.cpp` / `.h`** に置く
- .cpp は通常のC++としてコンパイルされ前処理を受けないため問題が起きない
- Arduino IDE でも同じ構造でそのままビルドできる（利用者側に不利益なし）

検証済みの最小例（Flash 11% / RAM 8% でビルド成功）:
```
mindclip/
  mindclip.ino   ← コメントのみ
  main.cpp       ← #include <Arduino.h> と setup()/loop()
```
