// recorder.cpp — 録音・バッファ・WAV書込の実装。詳細は recorder.h を参照。
//
// 【重要】SDへの書込は必ず「1回あたり DRAIN_CHUNK バイト」に刻み、I2S読み出しの合間に
// 少しずつ流す（recorderPump が1周ごとに serviceDrain() を1回だけ呼ぶ）。
// ESP_I2S の DMA は 6面×240フレーム = 2880バイト = 90ms しか無く（core 3.3.11 の
// I2S_DEFAULT_CFG は固定でファーム側から変更できない）、まとめて 1.92MB を同期書込みすると
// その間 i2s_channel_read が呼ばれず DMA が黙って溢れて音が消える。
// 32KB/回なら書込1回は約32ms（実効1MB/s想定）で 60ms の音声取り込みより短く、
// DMAの滞留は必ず減っていくため欠落しない。
//
// ファイル境界も「リングバッファ上の位置」で持つ（s_segBytes）。分割を決めた瞬間に
// 次のファイル名（＝時刻）を確定させ、書き切ってから閉じて次を開くので、
// 書込に時間が掛かってもその間の音声は捨てられず、ファイル名の時刻もずれない。
#include "recorder.h"
#include "vad.h"
#include "rtcclock.h"
#include <ESP_I2S.h>
#include <esp_heap_caps.h>
#include <SPI.h>
#include <SD.h>

static I2SClass s_i2s;

// 1回のSD書込の上限。DMA(90ms)を溢れさせない大きさに固定する。
static const size_t DRAIN_CHUNK = 32768;

// s_file.write() に渡すポインタは**必ず内部DRAMの整列アドレス**にする（下の writeVia）。
// リングは PSRAM 上にあり、WAVヘッダ44バイトのぶんファイル内オフセットが常にセクタ境界から
// ずれるため、FATFS が disk_write() に渡すポインタは PSRAM の非整列アドレスになる。
// IDF 5.5 の sdmmc_write_sectors() は esp_dma_is_buffer_alignment_satisfied() が偽のとき
// 「512バイト1セクタずつ memcpy + 単ブロック書込」のバウンス経路に落ち、
// スループットが 100〜300KB/s まで落ちる。そうなると 32KB の書込が 160ms を超えて
// DMA(90ms)を溢れさせ、音が欠ける（SPEC §4.1 の D_spi=1.12% の前提も崩れる）。
static const size_t BOUNCE_CHUNK = 16384;
static uint8_t *s_dma = nullptr;       // 64B整列・内部DRAM・DMA可のバウンスバッファ

// ---- リングバッファ --------------------------------------------------------
static uint8_t *s_buf     = nullptr;   // 書込バッファ（PSRAM 優先）
static size_t   s_bufCap  = 0;
static size_t   s_bufHead = 0;         // 次に書き込む位置
static size_t   s_bufTail = 0;         // 次にSDへ流す位置
static size_t   s_bufFill = 0;         // 未書込バイト数
static size_t   s_bufHi   = 0;         // ここを超えたらまとめ書きを開始する（高水位）
static size_t   s_segBytes = 0;        // うち「現在のファイルに属する」先頭側のバイト数
static bool     s_drainActive = false;
static uint32_t s_overflowDrops = 0;

static uint8_t *s_pre     = nullptr;   // プリロール 500ms のリングバッファ
static size_t   s_preCap  = 0;
static size_t   s_preHead = 0;
static size_t   s_preLen  = 0;

static int16_t  s_chunk[CHUNK_SAMPLES];
static size_t   s_carryBytes = 0;      // FRAMEに満たない端数の繰越（欠落させない）

// ---- ファイル --------------------------------------------------------------
static File     s_file;
static bool     s_fileOpen     = false;
static bool     s_closeReq     = false;   // 現ファイルは「書き切ったら閉じる」状態
static char     s_stem[40];               // 現ファイルのステム
static char     s_nextStem[40];           // 分割時に先に確定させた次ファイルのステム
static bool     s_nextStemValid = false;
static char     s_pathRec[80];
static uint32_t s_dataBytes    = 0;       // ヘッダに宣言済みのバイト数
static uint32_t s_writtenBytes = 0;       // 実際にファイルへ書いたバイト数
static uint32_t s_fileStartMs  = 0;
static bool     s_wasSpeech    = false;

// ---- 状態 ------------------------------------------------------------------
static FaultCause s_fault      = FAULT_NONE;
static int        s_failStreak = 0;       // ファイル単位の連続書込失敗（E3）
static bool       s_sdMounted  = false;
static uint32_t   s_bufSecActual = 0;
static uint64_t   s_freeCache  = 0;       // 空き容量の推定値（f_getfree を録音経路から追放）
static uint32_t   s_i2sLastOkMs = 0;
static uint64_t   s_totalWritten = 0;     // 起動後にSDへ書いた総バイト（テレメトリ）
static bool       s_fileWriteErr = false; // 現ファイルで本体データの書込に失敗したか（E3）

// ---- 計器（SPEC §4.2 の [stat] 行。README §8.6 で 28mA を落としたときに
//      I_idle と D_capture を切り分ける唯一の証拠になる）--------------------
static uint64_t   s_spiBusyUs  = 0;   // SDへ書いていた累積時間（D_spi の分子）
static uint64_t   s_i2sWaitUs  = 0;   // i2s_read でブロックしていた累積時間（cpu_busy の裏）
static uint32_t   s_statT0Ms   = 0;   // 計器の基準時刻
static uint32_t   s_flushMsMax = 0;   // 1バースト(serviceDrain 1回)の最大所要ms
static uint32_t   s_fileCount  = 0;   // 確定した .wav の本数

FaultCause recorderFaultCause() { return s_fault; }
void       recorderClearFault() { s_fault = FAULT_NONE; s_failStreak = 0; }
bool       recorderIsCapturing() { return (s_fileOpen || s_nextStemValid) && vadIsSpeech(); }
uint32_t   recorderBufferSeconds() { return s_bufSecActual; }
uint64_t   recorderWrittenBytes()  { return s_totalWritten; }
uint32_t   recorderOverflowDrops() { return s_overflowDrops; }
uint64_t   recorderSpiBusyUs()     { return s_spiBusyUs; }
uint64_t   recorderI2sWaitUs()     { return s_i2sWaitUs; }
uint32_t   recorderFlushMsMax()    { return s_flushMsMax; }
uint32_t   recorderFileCount()     { return s_fileCount; }
uint32_t   recorderStatElapsedMs() { return millis() - s_statT0Ms; }

// ---------------------------------------------------------------------------
// SD / I2S
// ---------------------------------------------------------------------------
static uint64_t rawFreeBytes() {
  if (!s_sdMounted) return 0;
  uint64_t total = SD.totalBytes(), used = SD.usedBytes();
  return (total > used) ? (total - used) : 0;
}

// f_getfree はカードによっては秒オーダーでブロックするので、録音中は絶対に呼ばない。
// マウント直後・同期直後・FAULT復帰時だけ実測し、途中は書込バイト数を引いて推定する。
void recorderRefreshFreeSpace() { s_freeCache = rawFreeBytes(); }

uint64_t recorderFreeBytes() { return s_freeCache; }

static void freeConsume(uint64_t n) { s_freeCache = (s_freeCache > n) ? (s_freeCache - n) : 0; }

bool recorderMountSD() {
  if (s_sdMounted) return true;
  SPI.begin(PIN_SD_SCK, PIN_SD_MISO, PIN_SD_MOSI, PIN_SD_CS);
  for (int i = 0; i < 3; i++) {
    if (SD.begin(PIN_SD_CS, SPI, SD_SPI_HZ)) { s_sdMounted = true; break; }
    delay(200);
    if (SD.begin(PIN_SD_CS, SPI, SD_SPI_HZ_LOW)) { s_sdMounted = true; break; }
    delay(200);
  }
  if (!s_sdMounted) { s_fault = FAULT_SD; return false; }
  if (!SD.exists(REC_DIR)) SD.mkdir(REC_DIR);
  recorderRefreshFreeSpace();
  return true;
}

void recorderUnmountSD() {
  if (s_fileOpen) { s_file.close(); s_fileOpen = false; }
  if (s_sdMounted) { SD.end(); s_sdMounted = false; }
}

bool recorderInitI2S() {
  s_i2s.end();                       // 二重 begin() 防止（既に終了済みでも安全）
  s_i2s.setPinsPdmRx(PIN_PDM_CLK, PIN_PDM_DATA);
  if (!s_i2s.begin(I2S_MODE_PDM_RX, AUDIO_RATE, I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO)) {
    s_fault = FAULT_I2S;
    return false;
  }
  s_carryBytes  = 0;
  s_i2sLastOkMs = millis();
  return true;
}

void recorderDeinitI2S() { s_i2s.end(); }

// ---------------------------------------------------------------------------
// バッファ確保（E12: PSRAM が無ければ縮退。全滅なら FAULT_MEM）
// ---------------------------------------------------------------------------
bool recorderAllocBuffers() {
  if (!s_buf) {
    size_t want = (size_t)g_cfg.bufSec * AUDIO_BYTES_SEC;
    s_buf = (uint8_t *)ps_malloc(want);
    if (!s_buf) {
      want = 10 * AUDIO_BYTES_SEC;             // 320KB を内部SRAMから
      s_buf = (uint8_t *)malloc(want);
      if (!s_buf) { want = 5 * AUDIO_BYTES_SEC; s_buf = (uint8_t *)malloc(want); }
    }
    s_bufCap = s_buf ? want : 0;
  }
  s_bufSecActual = (uint32_t)(s_bufCap / AUDIO_BYTES_SEC);
  s_bufHead = s_bufTail = s_bufFill = s_segBytes = 0;
  // 高水位: 3/4。ここまで貯めてから一気に流す（要件2の「まとめ書き」）。
  s_bufHi = (s_bufCap > DRAIN_CHUNK * 4) ? (s_bufCap / 4 * 3) : s_bufCap;

  // 書込は必ずこのバッファ経由にする（PSRAM非整列によるバウンス経路を避ける）。
  if (!s_dma) {
    s_dma = (uint8_t *)heap_caps_aligned_alloc(64, BOUNCE_CHUNK,
                                               MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
  }

  if (!s_pre) {
    s_preCap = (size_t)PREROLL_MS * AUDIO_BYTES_SEC / 1000;   // 500ms = 16000B
    s_pre = (uint8_t *)malloc(s_preCap);
    if (!s_pre) s_preCap = 0;
  }
  s_preHead = 0; s_preLen = 0;

  // バッファが1バイトも取れないと「何も録れない機械」になる。黙って続けない。
  if (!s_buf) { s_fault = FAULT_MEM; return false; }
  return s_bufSecActual >= 30;      // 戻り = 要件どおりの 30〜60 秒が取れたか
}

// SYNCING に入る前に録音バッファを返す。PSRAM構成では無風だが、PSRAM無しの縮退構成
// （録音バッファが内部DRAMに載る）では WiFi + mTLS ハンドシェイクと同時に握ると
// DRAM が枯渇しうるので、安全側に倒しておく。RECORDING に戻るときは再確保する。
void recorderFreeBuffers() {
  if (s_buf) { free(s_buf); s_buf = nullptr; }
  if (s_pre) { free(s_pre); s_pre = nullptr; }
  if (s_dma) { heap_caps_free(s_dma); s_dma = nullptr; }
  s_bufCap = s_preCap = 0;
  s_bufHead = s_bufTail = s_bufFill = s_segBytes = 0;
  s_preHead = s_preLen = 0;
  s_bufHi = 0;
  s_bufSecActual = 0;
}

// ---------------------------------------------------------------------------
// WAV ヘッダ（SPEC §5.1: 拡張チャンクを付けない正準44バイト）
// ---------------------------------------------------------------------------
static void put32(uint8_t *p, uint32_t v) { p[0]=v; p[1]=v>>8; p[2]=v>>16; p[3]=v>>24; }
static void put16(uint8_t *p, uint16_t v) { p[0]=v; p[1]=v>>8; }

static void buildHeader(uint8_t *h, uint32_t dataBytes) {
  memcpy(h + 0,  "RIFF", 4);  put32(h + 4,  36 + dataBytes);
  memcpy(h + 8,  "WAVE", 4);
  memcpy(h + 12, "fmt ", 4);  put32(h + 16, 16);
  put16(h + 20, 1);           put16(h + 22, 1);
  put32(h + 24, AUDIO_RATE);  put32(h + 28, AUDIO_BYTES_SEC);
  put16(h + 32, 2);           put16(h + 34, 16);
  memcpy(h + 36, "data", 4);  put32(h + 40, dataBytes);
}

// SPEC §5.2 手順3-4: 宣言サイズを実バイト数に追いつかせる（常に「宣言 ≤ 実体」を保つ）
static bool updateHeaderSizes(uint32_t dataBytes) {
  uint8_t v[4];
  if (!s_file.seek(4))  return false;
  put32(v, 36 + dataBytes);
  if (s_file.write(v, 4) != 4) return false;
  if (!s_file.seek(40)) return false;
  put32(v, dataBytes);
  if (s_file.write(v, 4) != 4) return false;
  s_file.flush();
  s_dataBytes = dataBytes;
  return s_file.seek(44 + dataBytes);
}

static bool openWithStem(const char *stem) {
  if (!s_sdMounted) { s_fault = FAULT_SD; return false; }
  if (recorderFreeBytes() < SD_FREE_MIN) { s_fault = FAULT_SD; return false; }   // E2

  snprintf(s_stem, sizeof(s_stem), "%s", stem);
  snprintf(s_pathRec, sizeof(s_pathRec), "%s/%s%s", REC_DIR, s_stem, EXT_RECORDING);
  // 同一秒に2ファイル作った場合の保険。完成済み .wav とも衝突させない。
  // 最後の候補(_99)も必ず存在確認してから使う。確認しないまま FILE_WRITE(=切り詰め)で
  // 開くと、既にある _99.wav.rec を上書きしてしまう（削除禁止ルールの抜け穴）。
  for (int n = 1; n <= 100; n++) {
    char done[80];
    snprintf(done, sizeof(done), "%s/%s%s", REC_DIR, s_stem, EXT_DONE);
    if (!SD.exists(s_pathRec) && !SD.exists(done)) break;
    if (n == 100) { s_fault = FAULT_SD; return false; }   // 同一秒に100本。異常事態
    snprintf(s_stem, sizeof(s_stem), "%s_%d", stem, n);
    snprintf(s_pathRec, sizeof(s_pathRec), "%s/%s%s", REC_DIR, s_stem, EXT_RECORDING);
  }

  s_file = SD.open(s_pathRec, FILE_WRITE, true);
  if (!s_file) { s_fault = FAULT_SD; return false; }

  uint8_t h[44];
  buildHeader(h, 0);
  if (s_file.write(h, 44) != 44) { s_file.close(); SD.remove(s_pathRec); s_fault = FAULT_SD; return false; }
  s_file.flush();
  freeConsume(44);
  s_dataBytes = 0; s_writtenBytes = 0; s_fileStartMs = millis(); s_fileWriteErr = false;
  s_fileOpen = true; s_closeReq = false;
  return true;
}

// 分割を宣言する。この時点で「現ファイルに属するバイト数」を凍結し、
// 以降の追記は次のファイルのものになる（音声は1サンプルも捨てない）。
static void requestClose() {
  if (!s_fileOpen || s_closeReq) return;
  s_closeReq   = true;
  s_segBytes   = s_bufFill;
  s_drainActive = true;
}

// 整列した内部DRAMを経由してSDへ書く（PSRAM非整列のバウンス経路を踏まないため）。
static size_t writeVia(const uint8_t *src, size_t n) {
  if (!s_dma) return s_file.write(src, n);       // 確保できなかった場合の縮退
  size_t done = 0;
  while (done < n) {
    size_t take = n - done;
    if (take > BOUNCE_CHUNK) take = BOUNCE_CHUNK;
    memcpy(s_dma, src + done, take);
    size_t w = s_file.write(s_dma, take);
    done += w;
    if (w != take) break;
  }
  return done;
}

// リング先頭から最大 maxBytes（現ファイル分に限る）をSDへ書く。戻り = 成功
static bool drainStep(size_t maxBytes) {
  if (!s_fileOpen || s_segBytes == 0) return true;
  size_t n = (maxBytes < s_segBytes) ? maxBytes : s_segBytes;
  size_t contig = s_bufCap - s_bufTail;
  if (n > contig) n = contig;

  size_t w = writeVia(s_buf + s_bufTail, n);
  if (w != n) {                                  // E3: 1回だけ再試行
    s_file.flush();
    w += writeVia(s_buf + s_bufTail + w, n - w);
  }
  s_writtenBytes += (uint32_t)w;
  s_totalWritten += (uint64_t)w;
  freeConsume(w);                                // 失敗パスでも空き容量推定をずらさない
  s_bufTail = (s_bufTail + w) % s_bufCap;
  s_bufFill  -= w;
  s_segBytes -= w;
  if (w != n) {
    // E3: 本体データの書込失敗は**ファイル単位の失敗**として記録する。
    // ヘッダ更新(4B)は不良セクタでも成功しがちなので、成功判定に使ってはならない
    // （使うと finalizeClose で s_failStreak が毎回0に戻り、E3が永久に発火しない）。
    s_fileWriteErr = true;
    s_file.flush();
    updateHeaderSizes(s_writtenBytes);
    return false;
  }
  return true;
}

// 書き切ったファイルを確定させる: flush → ヘッダ更新 → close → .wav.rec を .wav へ
static void finalizeClose() {
  if (!s_fileOpen) return;
  bool ok = !s_fileWriteErr;      // E3: 「このファイルで書込エラーが一度も無かったか」
  s_file.flush();
  if (!updateHeaderSizes(s_writtenBytes)) ok = false;
  uint32_t bytes = s_writtenBytes;
  s_file.close();
  s_fileOpen = false;
  s_closeReq = false;

  char pathDone[80];
  size_t plen = strlen(s_pathRec);
  memcpy(pathDone, s_pathRec, plen + 1);
  pathDone[plen - 4] = 0;                       // ".wav.rec" → ".wav"

  if (bytes < (MIN_FILE_MS * AUDIO_BYTES_SEC / 1000)) {
    SD.remove(s_pathRec);                       // 2秒未満は捨てる（SPEC §3.2）
  } else if (s_fileCount++, !SD.rename(s_pathRec, pathDone)) {
    for (int n = 1; n < 100; n++) {             // 名前衝突なら連番を足して再試行
      char alt[80];
      snprintf(alt, sizeof(alt), "%s/%s_%d%s", REC_DIR, s_stem, n, EXT_DONE);
      if (!SD.exists(alt) && SD.rename(s_pathRec, alt)) break;
    }
    // 全部失敗しても .wav.rec のまま残す（次回起動の復旧で再挑戦できる）。消さない。
  }
  if (ok) s_failStreak = 0; else s_failStreak++;
  if (s_failStreak >= 3) s_fault = FAULT_SD;    // 3ファイル連続失敗（E3→E1扱い）
  s_fileWriteErr = false;
  s_wasSpeech = false;
}

// 書込に失敗したファイルを打ち切る（E3 後半: 番号を進めて録音を続ける）
static void abortCurrentFile() {
  if (!s_fileOpen) return;
  s_bufTail = (s_bufTail + s_segBytes) % s_bufCap;    // 書けなかった分は諦める
  s_bufFill -= s_segBytes;
  s_segBytes = 0;
  finalizeClose();
}

// recorderPump / recorderFinishAndClose から呼ぶ「1回分」の書込サービス
static void serviceDrainInner(size_t chunk) {

  if (s_fileOpen) {
    if (s_segBytes > 0) {
      if (!drainStep(chunk)) { abortCurrentFile(); }
      else if (s_segBytes > 0) return;                 // まだ続きがある。次のpumpで
    }
    if (s_fileOpen && s_segBytes == 0) {
      s_file.flush();
      if (!updateHeaderSizes(s_writtenBytes)) s_fileWriteErr = true;  // 1バーストにつき fsync 1回
      if (s_closeReq) finalizeClose();
    }
  }

  if (!s_fileOpen) {
    if (s_bufFill > 0 && s_nextStemValid) {
      if (openWithStem(s_nextStem)) { s_nextStemValid = false; s_segBytes = s_bufFill; }
      else { s_bufTail = s_bufHead; s_bufFill = 0; s_segBytes = 0; }   // 開けない=FAULT。捨てる
    } else if (s_bufFill > 0) {
      s_bufTail = s_bufHead; s_bufFill = 0; s_segBytes = 0;            // 行き先が無い（起こらない）
    }
  }
  if (s_bufFill == 0 && !s_closeReq) s_drainActive = false;
}

// SPEC §4.2 の計器: SPI稼働時間(D_spiの分子)と「1バーストの最大所要ms」をここで測る。
// flush_ms_max が DMA の 90ms に近付いていたら、書込がDMAを溢れさせかけている証拠。
static void serviceDrain(size_t chunk) {
  if (!s_drainActive) return;
  uint32_t t0 = micros();
  serviceDrainInner(chunk);
  uint32_t dt = micros() - t0;
  s_spiBusyUs += dt;
  uint32_t ms = dt / 1000;
  if (ms > s_flushMsMax) s_flushMsMax = ms;
}

// ---------------------------------------------------------------------------
// プリロール（SPEC §3.1: 発話検出前 500ms も保存する）
// ---------------------------------------------------------------------------
static void prerollPush(const uint8_t *p, size_t n) {
  if (!s_pre || s_preCap == 0) return;
  if (n >= s_preCap) { memcpy(s_pre, p + (n - s_preCap), s_preCap); s_preHead = 0; s_preLen = s_preCap; return; }
  size_t first = s_preCap - s_preHead;
  if (n <= first) { memcpy(s_pre + s_preHead, p, n); s_preHead += n; }
  else            { memcpy(s_pre + s_preHead, p, first); memcpy(s_pre, p + first, n - first); s_preHead = n - first; }
  if (s_preHead >= s_preCap) s_preHead -= s_preCap;
  s_preLen = (s_preLen + n > s_preCap) ? s_preCap : s_preLen + n;
}

static void bufAppend(const uint8_t *p, size_t n);   // 前方宣言

static void prerollDrain() {
  if (!s_pre || s_preLen == 0) return;
  size_t start = (s_preHead + s_preCap - s_preLen) % s_preCap;
  size_t first = s_preCap - start;
  if (s_preLen <= first) bufAppend(s_pre + start, s_preLen);
  else { bufAppend(s_pre + start, first); bufAppend(s_pre, s_preLen - first); }
  s_preLen = 0; s_preHead = 0;
}

static void bufAppend(const uint8_t *p, size_t n) {
  if (!s_buf || s_bufCap == 0) return;
  while (n > 0) {
    if (s_bufFill == s_bufCap) {                 // 満杯: 同期的に少しだけ吐き出す
      size_t before = s_bufFill;
      s_drainActive = true;
      serviceDrain(DRAIN_CHUNK);
      if (s_bufFill >= before) { s_overflowDrops += n; return; }   // 進めない → 新しい音を捨てる
    }
    size_t room = s_bufCap - s_bufFill;
    size_t take = (n < room) ? n : room;
    size_t contig = s_bufCap - s_bufHead;
    if (take > contig) take = contig;
    memcpy(s_buf + s_bufHead, p, take);
    s_bufHead = (s_bufHead + take) % s_bufCap;
    s_bufFill += take;
    if (!s_closeReq) s_segBytes = s_bufFill;     // 分割待ちでなければ全部が現ファイル分
    p += take; n -= take;
  }
  if (s_bufFill >= s_bufHi) s_drainActive = true;   // 高水位でまとめ書き開始
}

// 追記先（ファイル or 次ファイル名）を用意する。分割待ちの間は名前だけ先に確定させる。
static void ensureTarget() {
  if (s_fault != FAULT_NONE) return;
  if (s_closeReq) {
    if (!s_nextStemValid) { clockMakeStem(s_nextStem, sizeof(s_nextStem)); s_nextStemValid = true; }
    return;
  }
  if (s_fileOpen) return;
  if (s_nextStemValid) { if (openWithStem(s_nextStem)) s_nextStemValid = false; return; }
  char stem[40];
  clockMakeStem(stem, sizeof(stem));
  openWithStem(stem);
}

// ---------------------------------------------------------------------------
void recorderEnterRecording() {
  vadBegin();
  s_bufHead = s_bufTail = s_bufFill = s_segBytes = 0;
  s_preLen = 0; s_preHead = 0; s_wasSpeech = false;
  s_drainActive = false; s_closeReq = false; s_nextStemValid = false;
  s_carryBytes = 0;
  s_i2sLastOkMs = millis();
  s_fileWriteErr = false;
  s_spiBusyUs = 0; s_i2sWaitUs = 0; s_flushMsMax = 0; s_fileCount = 0;
  s_statT0Ms = millis();
}

void recorderPump() {
  if (s_fault != FAULT_NONE) return;

  // ここでブロックしている間にCPUは WFI に入る（省電力予算の前提。ポーリング禁止）
  size_t want = CHUNK_BYTES - s_carryBytes;
  uint32_t tw0 = micros();
  size_t got  = s_i2s.readBytes((char *)s_chunk + s_carryBytes, want);
  s_i2sWaitUs += (uint64_t)(micros() - tw0);        // cpu_busy の裏（= I_idle の代理指標）
  if (got == 0) {                                   // E15: マイクが死んでいる可能性
    if (millis() - s_i2sLastOkMs > I2S_STALL_MS) { s_fault = FAULT_I2S; }
    return;
  }
  s_i2sLastOkMs = millis();

  size_t total  = s_carryBytes + got;
  size_t frames = total / (FRAME_SAMPLES * 2);
  size_t used   = frames * FRAME_SAMPLES * 2;
  s_carryBytes  = total - used;                     // 端数は必ず次回へ繰り越す（欠落ゼロ）

  for (size_t i = 0; i < frames; i++) {
    const int16_t *f = s_chunk + i * FRAME_SAMPLES;
    const uint8_t *fb = (const uint8_t *)f;
    bool sp = vadFeedFrame(f, FRAME_SAMPLES);

    if (sp) {
      ensureTarget();
      if (s_fault != FAULT_NONE) return;
      if (!s_wasSpeech) { prerollPush(fb, FRAME_SAMPLES * 2); prerollDrain(); }
      else              { bufAppend(fb, FRAME_SAMPLES * 2); }
    } else {
      prerollPush(fb, FRAME_SAMPLES * 2);
    }
    s_wasSpeech = sp;

    if (s_fileOpen && !s_closeReq) {
      // 分割条件1: 無音が gap_sec 続いた（ファイル内の時刻ずれを±gap_secに封じる）
      if (!sp && vadSilenceMs() >= (uint32_t)g_cfg.gapSec * 1000) { requestClose(); continue; }
      // 分割条件2: ハード上限 split_sec
      if ((millis() - s_fileStartMs) >= (uint32_t)g_cfg.splitSec * 1000) { requestClose(); continue; }
    }
  }
  if (s_carryBytes > 0) memmove(s_chunk, (const uint8_t *)s_chunk + used, s_carryBytes);

  // 1周につき1回だけ、32KBを上限にSDへ流す（DMA 90ms を溢れさせない）
  serviceDrain(DRAIN_CHUNK);

  // 空き容量の見張り（E2）。推定値なので f_getfree は呼ばない
  if (recorderFreeBytes() < SD_FREE_MIN) {
    recorderRefreshFreeSpace();                     // 誤差の可能性があるので1回だけ実測
    if (recorderFreeBytes() < SD_FREE_MIN) {
      recorderFinishAndClose();
      s_fault = FAULT_SD;
    }
  }
}

void recorderFinishAndClose() {
  // 録音を止めるので、ここだけは残りを同期的に書き切る（DMAを気にしなくてよい）
  for (int guard = 0; guard < 20000; guard++) {
    if (s_fileOpen && !s_closeReq) requestClose();
    if (!s_fileOpen && s_bufFill == 0) break;
    s_drainActive = true;
    size_t beforeFill = s_bufFill;
    bool   wasOpen    = s_fileOpen;
    serviceDrain(DRAIN_CHUNK);
    if (!s_fileOpen && s_bufFill == beforeFill && wasOpen == s_fileOpen) break;   // 進まない
  }
  s_bufHead = s_bufTail = s_bufFill = s_segBytes = 0;
  s_drainActive = false; s_nextStemValid = false;
  s_preLen = 0; s_preHead = 0;
}

// ---------------------------------------------------------------------------
// BOOT時の .wav.rec 復旧（SPEC §5.3）
// ---------------------------------------------------------------------------
void recorderRecoverRecFiles() {
  if (!s_sdMounted) return;
  File dir = SD.open(REC_DIR);
  if (!dir) return;

  String victims[32];
  int nv = 0;
  bool truncated = false;
  for (;;) {
    File f = dir.openNextFile();
    if (!f) break;
    String p = String(f.path());
    f.close();                                   // 上限に達しても必ず閉じる
    if (!p.endsWith(EXT_RECORDING)) continue;
    if (nv >= 32) { truncated = true; break; }
    victims[nv++] = p;
  }
  dir.close();
  if (truncated) mcLogf("[REC] recover: >32 .wav.rec — 残りは次回起動で復旧する");

  for (int i = 0; i < nv; i++) {
    File f = SD.open(victims[i].c_str(), "r+");
    if (!f) continue;
    uint32_t fsize = (uint32_t)f.size();
    uint32_t hdr = 0;
    if (fsize >= 44 && f.seek(40)) {
      uint8_t v[4];
      if (f.read(v, 4) == 4) hdr = (uint32_t)v[0] | ((uint32_t)v[1] << 8) | ((uint32_t)v[2] << 16) | ((uint32_t)v[3] << 24);
    }
    uint32_t avail = (fsize > 44) ? (fsize - 44) : 0;
    // SPEC §5.2 の不変条件「宣言サイズ ≤ 実バイト数」が常に成り立つので、
    // filesize-44 は常に安全な下界である。min(header, avail) を採ってはならない:
    // ヘッダ更新は1バーストにつき1回しか行われないため、ドレイン中に電池が切れると
    // 実体は最大47秒あるのに hdr=0 となり、min() では 0 → 1秒未満とみなして
    // **ファイルごと削除**してしまう（§7 共通ルール「消す方向に倒さない」に反する）。
    (void)hdr;
    uint32_t fixed = avail;
    if (fixed >= AUDIO_BYTES_SEC) {                    // 1秒以上あれば救う
      uint8_t v[4];
      put32(v, 36 + fixed); f.seek(4);  f.write(v, 4);
      put32(v, fixed);      f.seek(40); f.write(v, 4);
      f.flush(); f.close();
      String done = victims[i];
      done.remove(done.length() - 4);                  // ".wav.rec" → ".wav"
      if (!SD.rename(victims[i].c_str(), done.c_str())) {
        // 既存の .wav と衝突している。救った音声を消してはならない（closeFile と同じ連番退避）
        String base = done.substring(0, done.length() - 4);   // 拡張子を外す
        bool moved = false;
        for (int n = 1; n < 100 && !moved; n++) {
          String alt = base + "_" + String(n) + EXT_DONE;
          if (!SD.exists(alt.c_str())) moved = SD.rename(victims[i].c_str(), alt.c_str());
        }
        // それでも駄目なら .wav.rec のまま残す（次回起動で再挑戦。削除は絶対にしない）
      }
    } else {
      f.close();
      SD.remove(victims[i].c_str());                   // 1秒未満は削除（§5.3）
    }
  }
  recorderRefreshFreeSpace();
}

bool recorderHasPendingFiles() {
  if (!s_sdMounted) return false;
  File dir = SD.open(REC_DIR);
  if (!dir) return false;
  bool found = false;
  for (File f = dir.openNextFile(); f; f = dir.openNextFile()) {
    String n = String(f.name());
    f.close();
    if (isSendableName(n)) { found = true; break; }   // .wav / .wav.b1 / .wav.b2
  }
  dir.close();
  return found;
}
