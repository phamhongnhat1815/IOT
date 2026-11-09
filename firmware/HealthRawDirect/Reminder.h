#pragma once
#include <stdint.h>
#include <stddef.h>
#include <string.h>

// Pure policy shared with native tests. No measurement/button/sensor state here.
namespace Reminder {
constexpr uint32_t SOUND_ACTIVE = 1u<<31, SOUND_MISSED = 1u<<30, CLOCK_MASK = (1u<<30)-1;
inline uint32_t soundWord(uint32_t now,bool missed) {
  return SOUND_ACTIVE | (missed ? SOUND_MISSED : 0u) | (now & CLOCK_MASK);
}
inline uint32_t soundElapsed(uint32_t now,uint32_t word) {
  return (now-(word & CLOCK_MASK)) & CLOCK_MASK;
}
constexpr size_t CAPACITY = 16, RECORD_BYTES = 73;
constexpr size_t SNAPSHOT_BYTES = 4 + CAPACITY * RECORD_BYTES + 4;
struct Entry { char id[65]{}; uint64_t expires = 0; };
struct Cache {
  Entry entries[CAPACITY]{};
  static bool validId(const char* id) {
    if (!id || strlen(id) != 64) return false;
    for (size_t i=0;i<64;++i)
      if (!((id[i]>='0' && id[i]<='9') || (id[i]>='a' && id[i]<='f'))) return false;
    return true;
  }
  bool contains(const char* id) const {
    for (const auto& e:entries) if (!strcmp(e.id,id)) return true;
    return false;
  }
  bool add(const char* id, uint64_t expires, uint64_t now) {
    if (!validId(id) || expires<=now || now<1700000000ULL) return false;
    for (auto& e:entries) if (!e.id[0] || e.expires<=now) {
      memcpy(e.id,id,65); e.expires=expires; return true;
    }
    return false; // Never evict an unexpired ID and replay its sound later.
  }
};
inline uint32_t checksum(const uint8_t* p,size_t n) {
  uint32_t h=2166136261u;
  for(size_t i=0;i<n;++i) h=(h^p[i])*16777619u;
  return h;
}
inline void encode(const Cache& c,uint8_t* out) {
  memset(out,0,SNAPSHOT_BYTES); memcpy(out,"SLR1",4);
  for(size_t i=0;i<CAPACITY;++i) {
    size_t at=4+i*RECORD_BYTES; memcpy(out+at,c.entries[i].id,65);
    for(size_t b=0;b<8;++b) out[at+65+b]=uint8_t(c.entries[i].expires>>(8*b));
  }
  uint32_t h=checksum(out,SNAPSHOT_BYTES-4);
  for(size_t b=0;b<4;++b) out[SNAPSHOT_BYTES-4+b]=uint8_t(h>>(8*b));
}
inline bool decode(const uint8_t* in,size_t n,Cache& out) {
  if(n!=SNAPSHOT_BYTES || memcmp(in,"SLR1",4)) return false;
  uint32_t expected=0;
  for(size_t b=0;b<4;++b) expected|=uint32_t(in[n-4+b])<<(8*b);
  if(expected!=checksum(in,n-4)) return false;
  Cache candidate;
  for(size_t i=0;i<CAPACITY;++i) {
    size_t at=4+i*RECORD_BYTES; auto& e=candidate.entries[i];
    memcpy(e.id,in+at,65);
    if(e.id[64] || (e.id[0] && !Cache::validId(e.id))) return false;
    for(size_t b=0;b<8;++b) e.expires|=uint64_t(in[at+65+b])<<(8*b);
    if((!e.id[0] && e.expires) || (e.id[0] && e.expires<1700000000ULL)) return false;
  }
  out=candidate; return true;
}
inline bool buzzerOn(uint32_t elapsed,bool missed,uint8_t alarmPhase) {
  if(alarmPhase || elapsed>=10000UL) return false;
  uint32_t phase=elapsed%2000UL;
  return phase<200UL || (missed && phase>=300UL && phase<450UL);
}
}
