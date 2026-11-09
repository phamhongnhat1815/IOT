#pragma once
#include <math.h>
#include <stdint.h>

// Units: acceleration in g, angular speed in degrees/second, time in ms.
// Deliberately unconfigured: neck-pendant thresholds have not been agreed/calibrated.
struct FallConfig {
  float lowG = NAN, impactG = NAN, rotationDps = NAN, tiltDeg = NAN;
  float stillAccelG = NAN, stillGyroDps = NAN;
  uint32_t impactWindowMs = 0, settleWindowMs = 0, stillMs = 0;
  bool valid() const {
    return isfinite(lowG) && lowG > 0 && lowG < 1 && isfinite(impactG) && impactG > 1 &&
      isfinite(rotationDps) && rotationDps > 0 && isfinite(tiltDeg) && tiltDeg > 0 && tiltDeg <= 180 &&
      isfinite(stillAccelG) && stillAccelG > 0 && isfinite(stillGyroDps) && stillGyroDps > 0 &&
      impactWindowMs > 0 && settleWindowMs >= stillMs && stillMs > 0;
  }
};

class FallDetector {
 public:
  FallConfig config;
  enum Stage { IDLE, MOVEMENT, POST_IMPACT } stage = IDLE;
  void reset() { stage = IDLE; baseline = false; stillTracking = false; }
  bool update(uint32_t now, float ax, float ay, float az, float gx, float gy, float gz) {
    if (!config.valid()) { reset(); return false; }
    float a = sqrtf(ax*ax + ay*ay + az*az), w = sqrtf(gx*gx + gy*gy + gz*gz);
    if (!isfinite(a) || !isfinite(w) || a < 0.001f) { reset(); return false; }
    // A scheduling/I2C gap invalidates the temporal chain.
    if (baseline && now-lastSample > 100) reset();
    lastSample = now;
    float x=ax/a, y=ay/a, z=az/a;
    if (!baseline) { bx=x; by=y; bz=z; baseline=true; }
    if (stage == IDLE) {
      if (a < config.lowG || w > config.rotationDps || a > config.impactG) {
        stage = MOVEMENT; started = now; peakRotation = w;
        rx=bx; ry=by; rz=bz;
      } else if (fabsf(a-1) < config.stillAccelG && w < config.stillGyroDps) {
        bx = 0.95f*bx+0.05f*x; by=0.95f*by+0.05f*y; bz=0.95f*bz+0.05f*z;
        float n=sqrtf(bx*bx+by*by+bz*bz); bx/=n; by/=n; bz/=n;
      }
    }
    if (stage == MOVEMENT) {
      if (w > peakRotation) peakRotation=w;
      if (now-started > config.impactWindowMs) { stage=IDLE; return false; }
      if (a > config.impactG) { stage=POST_IMPACT; started=now; stillTracking=false; }
    } else if (stage == POST_IMPACT) {
      if (w > peakRotation) peakRotation=w;
      if (now-started > config.settleWindowMs) { reset(); return false; }
      float dot=rx*x+ry*y+rz*z;
      if (dot < -1) dot=-1; if (dot > 1) dot=1;
      float tilt=acosf(dot)*57.2957795f;
      if (fabsf(a-1) < config.stillAccelG && w < config.stillGyroDps) {
        if (!stillTracking) { stillTracking=true; stillSince=now; }
        if (now-stillSince >= config.stillMs &&
            (tilt >= config.tiltDeg || peakRotation >= config.rotationDps)) {
          reset(); return true;
        }
      } else stillTracking=false;
    }
    return false;
  }
 private:
  bool baseline=false, stillTracking=false;
  uint32_t started=0, stillSince=0, lastSample=0;
  float bx=0,by=0,bz=1,rx=0,ry=0,rz=1,peakRotation=0;
};
