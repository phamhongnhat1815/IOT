#pragma once
#include <stdint.h>

// Explicit identities, not a bypass for arbitrary WHO_AM_I values.
// MPU6515 uses the MPU6500 register family (Linux inv_mpu6050 driver).
inline const char* mpuModelName(uint8_t who) {
  switch(who) {
    case 0x68: return "MPU6050";
    case 0x70: return "MPU6500";
    case 0x74: return "MPU6515";
    default: return nullptr;
  }
}
inline bool mpuHasAccelFilter(uint8_t who) { return who==0x70 || who==0x74; }
