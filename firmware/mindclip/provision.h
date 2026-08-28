// =============================================================================
// provision.h — USBシリアルによるプロビジョニングCLI（SPEC §10.2）
//
// 使い方（初心者向け）: USBでPCに繋ぎ、シリアルモニタ(115200, 改行=LF)を開いて
// RESETボタンを押し、3秒以内に Enter を押す。LEDが高速点滅すればCLIに入っている。
//   set wifi.ssid MyHomeAP / set wifi.pass ****  / set srv.url https://192.168.1.10:8443
//   paste srv.ca (PEMを貼って最後に "." だけの行) / gen hmac / show / test wifi / test server
//   save / reboot / erase
// SSID・パスフレーズ・鍵はここからNVSに入る。ソースには一切書かない。
// =============================================================================
#pragma once
#include "config.h"

bool provisionShouldEnter(uint32_t windowMs);  // 起動後 windowMs 以内のシリアル受信を待つ
void provisionRun();                           // reboot するまで戻らない
