// =============================================================================
// vad.h — エネルギー閾値VAD＋書込デューティ・ガバナ（SPEC §4）
//
// 20msフレームの平均絶対値を dBFS 換算し、非対称IIRで追従するノイズフロア＋margin を
// 閾値にする。立ち上がり3フレーム連続 / ハングオーバー800ms。
// ガバナは直近600秒の D_capture（音声採用秒 ÷ 経過秒）を見て margin を ±1dB/30s 調整する。
// なお SPEC §8.4 の通り、28mAゲートの主因は I_idle でありVADではない。
// D_capture は主に SD容量・転送時間の予算として管理する。ハードクランプは既定オフ。
// =============================================================================
#pragma once
#include "config.h"

void     vadBegin();                                  // g_cfg を読んで初期化
bool     vadFeedFrame(const int16_t *frame, size_t n); // 20msフレームを1つ投入。戻り=採用するか
bool     vadIsSpeech();                                // ハングオーバー込みの現在状態
uint32_t vadSilenceMs();                               // 無音が続いているms（発話中は0）
float    vadDutyCapture();                             // 直近600秒の D_capture (0..1)
uint8_t  vadMarginDb();                                // 現在の実効margin
float    vadFloorDb();
bool     vadClamped();                                 // ハードクランプ作動中
bool     vadTakeWarn();                                // 「margin上限に10分張り付き」の警告を1回取り出す
