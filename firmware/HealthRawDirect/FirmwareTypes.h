#pragma once
#include <stdint.h>
#include <stddef.h>

constexpr uint16_t SAMPLE_HZ = 100;
constexpr uint16_t PAIRS_PER_BATCH = 50;
constexpr uint16_t SESSION_PAIRS = 1500;
constexpr uint16_t SESSION_BATCHES = SESSION_PAIRS / PAIRS_PER_BATCH;
constexpr uint16_t MAX_TEMPERATURES = 16;
constexpr uint16_t MIN_TEMPERATURES = 5;
constexpr uint32_t SESSION_MAGIC = 0x534C4142; // SLAB
constexpr uint16_t SESSION_VERSION = 1;

enum class SoundMode : uint8_t { QUIET, WAITING, SUCCESS, OFFLINE, ERROR, MEASURING, DUE, MISSED };

#pragma pack(push, 1)
struct Pair { uint32_t red; uint32_t ir; };
struct Temperature {
  uint32_t sampleIndex;
  uint32_t readMs;
  float objectC;
  float ambientC;
};
struct RawSession {
  uint32_t magic;
  uint16_t version;
  uint16_t sampleRate;
  uint16_t batchSize;
  uint16_t pairCount;
  uint16_t temperatureCount;
  uint16_t reserved;
  uint32_t createdMs;
  char deviceId[32];
  char sessionId[80];
  Pair pairs[SESSION_PAIRS];
  Temperature temperatures[MAX_TEMPERATURES];
  uint32_t batchStartUs[SESSION_BATCHES];
  uint32_t batchEndUs[SESSION_BATCHES];
  uint32_t crc;
};
#pragma pack(pop)

static_assert(sizeof(RawSession) == 12632, "Unexpected flash format layout");
static_assert(SESSION_PAIRS % PAIRS_PER_BATCH == 0, "Partial final batch not supported");

inline uint32_t crc32Update(uint32_t crc, const uint8_t* data, size_t length) {
  for (size_t i = 0; i < length; ++i) {
    crc ^= data[i];
    for (uint8_t bit = 0; bit < 8; ++bit)
      crc = (crc >> 1) ^ (0xEDB88320UL & (0UL - (crc & 1UL)));
  }
  return crc;
}

inline uint32_t sessionCrc(const RawSession& session) {
  return crc32Update(0xFFFFFFFFUL, reinterpret_cast<const uint8_t*>(&session),
                     offsetof(RawSession, crc)) ^ 0xFFFFFFFFUL;
}
