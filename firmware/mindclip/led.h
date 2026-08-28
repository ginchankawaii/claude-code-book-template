// =============================================================================
// led.h — 外付けLED(D3/GPIO4) の「微灯」表示
//
// SPEC §2.1: 明るさは常に LEDC PWM デューティ 15%（既定・NVS可変）で固定し、
// **点滅パターンだけで状態を区別する**。tick() は loop から毎回呼ぶ（非ブロッキング）。
// =============================================================================
#pragma once
#include "config.h"

enum LedPattern {
  LEDP_OFF = 0,
  LEDP_LISTEN,     // 4秒ごとに60msパルス（生存表示）
  LEDP_CAPTURE,    // 連続点灯（微灯）
  LEDP_SYNC,       // 1Hz点滅
  LEDP_FAULT,      // 3回点滅＋1.5秒休み
  LEDP_PROVISION,  // 5Hz高速点滅
  LEDP_ERR2,       // 2回点滅＋1.5秒休み（WiFi/サーバ失敗）
  LEDP_ERR5        // 5回点滅＋1.5秒休み（認証失敗）
};

void ledBegin(uint8_t dutyPercent);
void ledSetPattern(LedPattern p);
void ledTick();                       // loop から毎回呼ぶ
void ledBlinkBlocking(int times, uint32_t onMs, uint32_t offMs);  // 起動時のコード表示
void ledOffHard();                    // sleep 直前に完全消灯
