// led.cpp — LEDC(PWM) による微灯表示。詳細は led.h を参照。
#include "led.h"

static uint32_t s_onDuty  = 38;      // 8bit: 255 * 15% ≒ 38
static LedPattern s_pat   = LEDP_OFF;
static uint32_t s_t0      = 0;

void ledBegin(uint8_t dutyPercent) {
  if (dutyPercent < 10) dutyPercent = 10;
  if (dutyPercent > 20) dutyPercent = 20;
  s_onDuty = (uint32_t)(255UL * dutyPercent / 100UL);
  ledcAttach(PIN_LED, 5000, 8);      // ch自動割当 / 5kHz / 8bit
  ledcWrite(PIN_LED, 0);
  s_t0 = millis();
}

void ledSetPattern(LedPattern p) {
  if (p == s_pat) return;
  s_pat = p;
  s_t0 = millis();
}

// n回点滅（onMs点灯/offMs消灯）＋restMs休み、を周期とするパターンの点灯判定
static bool burstOn(uint32_t t, int n, uint32_t onMs, uint32_t offMs, uint32_t restMs) {
  uint32_t unit = onMs + offMs;
  uint32_t period = unit * n + restMs;
  uint32_t x = t % period;
  if (x >= unit * (uint32_t)n) return false;
  return (x % unit) < onMs;
}

void ledTick() {
  uint32_t t = millis() - s_t0;
  bool on = false;
  switch (s_pat) {
    case LEDP_OFF:       on = false; break;
    case LEDP_CAPTURE:   on = true;  break;
    // SPEC §2.1 は 60ms パルスだが、録音ループの1周が I2S の 64ms 単位で
    // 進むため 60ms では ledTick() が点灯窓を跨いで見落とす。視認できる下限として
    // 100ms を採る（明るさ・平均電流は変わらない）。
    case LEDP_LISTEN:    on = (t % 4000) < 100; break;
    case LEDP_SYNC:      on = (t % 1000) < 500; break;
    case LEDP_PROVISION: on = (t % 200) < 100; break;
    case LEDP_FAULT:     on = burstOn(t, 3, 150, 150, 1500); break;
    case LEDP_ERR2:      on = burstOn(t, 2, 150, 150, 1500); break;
    case LEDP_ERR5:      on = burstOn(t, 5, 100, 100, 1500); break;
  }
  ledcWrite(PIN_LED, on ? s_onDuty : 0);
}

void ledBlinkBlocking(int times, uint32_t onMs, uint32_t offMs) {
  for (int i = 0; i < times; i++) {
    ledcWrite(PIN_LED, s_onDuty); delay(onMs);
    ledcWrite(PIN_LED, 0);        delay(offMs);
  }
}

void ledOffHard() {
  ledcWrite(PIN_LED, 0);
  ledcDetach(PIN_LED);
  pinMode(PIN_LED, OUTPUT);
  digitalWrite(PIN_LED, LOW);
}
