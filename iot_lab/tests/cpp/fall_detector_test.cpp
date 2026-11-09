#include <cassert>
#include "FallDetector.h"
#include "MpuProfile.h"
#include "AlertJournal.h"
#include <vector>
#include <cstdio>
#include <cstring>
#include "WearableConfig.h"

static AlertRecord testRecord(unsigned i=0) {
  AlertRecord r{};
  snprintf(r.eventId,sizeof(r.eventId),"fall-%u",i);
  strcpy(r.kind,"fall"); strcpy(r.state,"active");
  r.revision=1; r.uptimeMs=1234; r.occurredAt=1790000000;
  return r;
}
static void legacyRecord(uint8_t* out,const AlertRecord& r) {
  uint8_t encoded[ALERT_RECORD_BYTES]; alertEncodeRecord(encoded,r);
  memcpy(out,encoded,108); memcpy(out+112,encoded+108,8);
}
static void testJournalCodec() {
  AlertJournal j{}; j.magic=ALERT_MAGIC; j.phase=2; j.current=testRecord();
  j.pending[0]=j.current; j.count=1; j.currentQueued=true;
  uint8_t wire[ALERT_READ_MAX]; size_t n=encodeAlertJournal(j,wire,sizeof(wire));
  assert(n==ALERT_HEADER_BYTES+2*ALERT_RECORD_BYTES+4);
  AlertJournal recovered{};
  assert(decodeAlertJournal(wire,n,recovered));
  assert(recovered.phase==2 && recovered.count==1 && recovered.currentQueued);
  assert(!strcmp(recovered.current.eventId,"fall-0"));
  wire[20]^=1; assert(!decodeAlertJournal(wire,n,recovered)); wire[20]^=1;
  assert(!decodeAlertJournal(wire,n-1,recovered));
  for(unsigned capacity:{16u,32u}) {
    size_t crcOffset=8+120*(capacity+1);
    std::vector<uint8_t> old(crcOffset+8,0xa5); // Nonzero ABI padding is covered by old CRC, never a bool.
    alertPut32(old.data(),ALERT_MAGIC); old[4]=capacity; old[5]=2;
    legacyRecord(old.data()+8,j.current);
    for(unsigned i=0;i<capacity;i++) legacyRecord(old.data()+8+120*(i+1),testRecord(i));
    alertPut32(old.data()+crcOffset,alertBytesCrc(old.data(),crcOffset));
    assert(decodeLegacyAlertJournal(old.data(),old.size(),recovered));
    assert(recovered.phase==2 && recovered.count==capacity && recovered.currentQueued);
    n=encodeAlertJournal(recovered,wire,sizeof(wire));
    assert(n && decodeAlertJournal(wire,n,j));
    assert(j.count==capacity); // No truncation of the old 32-entry outbox.
    for(unsigned i=0;i<capacity;i++) assert(!strcmp(j.pending[i].eventId,testRecord(i).eventId));
    old[24]^=1; assert(!decodeLegacyAlertJournal(old.data(),old.size(),recovered));
  }
  j={}; j.magic=ALERT_MAGIC;
  n=encodeAlertJournal(j,wire,sizeof(wire)); assert(n && decodeAlertJournal(wire,n,recovered));
  assert(!recovered.count && !recovered.phase);
  j.phase=1; j.current=testRecord(); strcpy(j.current.state,"pending");
  n=encodeAlertJournal(j,wire,sizeof(wire)); assert(n && decodeAlertJournal(wire,n,recovered));
  assert(recovered.phase==1);
  j.pending[0]=j.current; j.count=1;
  assert(!encodeAlertJournal(j,wire,sizeof(wire))); // Never publish a pending grace record as a confirmed event.
}
int main() {
  testJournalCodec();
  assert(!strcmp(mpuModelName(0x68),"MPU6050"));
  assert(!strcmp(mpuModelName(116),"MPU6515"));
  assert(!strcmp(mpuModelName(0x70),"MPU6500"));
  assert(mpuHasAccelFilter(116) && !mpuHasAccelFilter(0x68));
  assert(!mpuModelName(0x00) && !mpuModelName(0xff));
  FallDetector d; d.config=trialFallConfig();
  assert(d.config.valid());
  // Normal gravity at rest and a slow tilt must not become a fall.
  for(unsigned t=0;t<1000;t+=10) assert(!d.update(t,0,0,1,0,0,0));
  for(unsigned t=1000;t<2000;t+=10) assert(!d.update(t,.7,0,.7,0,15,0));
  // A single impact followed by unchanged orientation and no rotation is not enough.
  d.reset(); d.update(2000,0,0,1,0,0,0);
  assert(!d.update(2010,0,0,3,0,0,0));
  for(unsigned t=2020;t<5500;t+=10) assert(!d.update(t,0,0,1,0,0,0));
  // Complete chain: reduced gravity, impact/rotation, then changed orientation + stillness.
  d.reset(); d.update(6000,0,0,1,0,0,0);
  assert(!d.update(6010,0,0,.4,0,180,0));
  assert(!d.update(6020,3,0,0,0,180,0));
  bool detected=false;
  for(unsigned t=6030;t<=6900;t+=10) detected=d.update(t,1,0,0,0,0,0)||detected;
  assert(detected);
  // Late impact or a sampling gap cannot complete a stale chain.
  d.reset(); d.update(7000,0,0,1,0,0,0); d.update(7010,0,0,.4,0,180,0);
  for(unsigned t=7020;t<8300;t+=10) assert(!d.update(t,0,0,1,0,0,0));
  d.update(9000,1,0,3,0,0,0);
  for(unsigned t=10000;t<11000;t+=10) assert(!d.update(t,1,0,0,0,0,0));
  // Incomplete config is disabled and bad sensor data invalidates temporal state.
  d.config=FallConfig{}; assert(!d.update(12000,0,0,3,0,200,0));
}
