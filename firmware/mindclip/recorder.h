// =============================================================================
// recorder.h — PDM録音 → VAD → PSRAMバッファ → microSD の WAV 書込（SPEC §3・§5）
//
// ・I2S PDM_RX 16kHz/16bit/mono を 60ms(960サンプル=VAD3フレーム)単位でブロッキング読みする。
//   待っている間にCPUが WFI で寝ることが省電力予算(§8)の前提。ポーリング禁止。
// ・音声は PSRAM 上のリングバッファ(既定60秒=1.92MB)に貯め、高水位(3/4)または分割/クローズで
//   まとめ書きする。ただし1回のSD書込は32KBに刻み、I2S読み出しの合間に流す。
//   ESP_I2S のDMAは90ms分しかないため、数百KBを一気に同期書込みすると音が消える。
// ・WAVヘッダは「データ書込→flush→ヘッダ更新→flush」の順で更新し、
//   常に「宣言サイズ ≤ 実バイト数」を保つ（電池切れでも壊れない）。
// ・分割は「600秒ハード上限」または「無音3秒」。2秒未満のファイルは作らない。
// =============================================================================
#pragma once
#include "config.h"

bool  recorderMountSD();          // SD.begin を最大3回試す（E1）
void  recorderUnmountSD();
bool  recorderInitI2S();          // PDM_RX 初期化（E13）
void  recorderDeinitI2S();

bool  recorderAllocBuffers();     // PSRAM確保。失敗時は10sへ縮退（E12）。戻り=PSRAMが取れたか
void  recorderFreeBuffers();      // SYNCING 前に返す（縮退構成でのDRAM枯渇を避ける）
void  recorderRecoverRecFiles();  // BOOT時の .wav.rec 復旧（SPEC §5.3）

void  recorderEnterRecording();   // RECORDING に入るときの初期化
void  recorderPump();             // loop から呼ぶ。1回で最大64ms分を処理する
void  recorderFinishAndClose();   // スイッチOFF: 最終フラッシュ→ヘッダ更新→クローズ→.wav

bool  recorderIsCapturing();      // LED表示用（VAD=発話中）
FaultCause recorderFaultCause();  // FAULT_NONE 以外なら FAULT へ遷移する
void  recorderClearFault();
uint64_t recorderFreeBytes();     // 推定値（録音経路から f_getfree を追放するため）
void     recorderRefreshFreeSpace(); // 実測しなおす（マウント直後・同期直後だけ）
uint64_t recorderWrittenBytes();  // 起動後にSDへ書いた総バイト（テレメトリ）
uint32_t recorderOverflowDrops(); // リング溢れで捨てたバイト数（0であるべき）
uint32_t recorderBufferSeconds(); // 実際に確保できたバッファ秒数

// ---- SPEC §4.2 の [stat] 行のための計器（実測ゲートの切り分けに必須）--------
uint64_t recorderSpiBusyUs();     // SDへ書いていた累積時間（D_spi の分子）
uint64_t recorderI2sWaitUs();     // i2s_read でブロックしていた累積時間（cpu_busy の裏）
uint32_t recorderFlushMsMax();    // 1バーストの最大所要ms（DMA 90ms と比較する）
uint32_t recorderFileCount();     // 確定した .wav の本数
uint32_t recorderStatElapsedMs(); // 計器の基準時刻からの経過ms（D_spi の分母）
bool  recorderHasPendingFiles();  // /rec に送信対象 .wav があるか
