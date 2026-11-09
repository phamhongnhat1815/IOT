#pragma once
#include "FallDetector.h"

constexpr uint8_t LED_RED_PIN=26, LED_GREEN_PIN=27, LED_BLUE_PIN=32, SOS_PIN=33;
// HIGH assumes GPIO -> resistor -> LED anode, LED cathode -> GND.
// Change only after confirming actual wiring (LED_TEST), not to mask crossed wires.
constexpr uint8_t LED_RED_ON_LEVEL=1, LED_GREEN_ON_LEVEL=1, LED_BLUE_ON_LEVEL=1;
constexpr uint8_t MPU_ADDRESS=0x68;
constexpr uint32_t CANCEL_HOLD_MS=2000, FALL_CANCEL_MS=6000;
// EXPERIMENTAL engineering starting points, NOT validated neck-pendant/medical thresholds.
// Tune using recordings from the actual enclosure; body position and loose suspension matter.
inline FallConfig trialFallConfig() {
  FallConfig c;
  c.lowG=0.65f; c.impactG=2.5f; c.rotationDps=150.0f; c.tiltDeg=45.0f;
  c.stillAccelG=0.20f; c.stillGyroDps=25.0f;
  c.impactWindowMs=1000; c.settleWindowMs=3000; c.stillMs=800;
  return c;
}
// Enables Serial SIM_FALL / SIM_SOS test commands only when explicitly set true.
constexpr bool ENABLE_SERIAL_SIMULATION=false;
