#include "Reminder.h"
#include <assert.h>
#include <stdio.h>

int main() {
  constexpr uint64_t now=1800000000;
  char id[65]; memset(id,'a',64); id[64]=0;
  Reminder::Cache c;
  assert(!c.add("invalid",now+60,now));
  assert(!c.add(id,now,now));
  assert(!c.add(id,now+60,0));
  assert(c.add(id,now+60,now));
  assert(c.contains(id));
  uint8_t bytes[Reminder::SNAPSHOT_BYTES];
  Reminder::encode(c,bytes);
  Reminder::Cache reboot;
  assert(Reminder::decode(bytes,sizeof(bytes),reboot));
  assert(reboot.contains(id));
  assert(!Reminder::decode(bytes,sizeof(bytes)-1,reboot));
  bytes[12]^=1;
  assert(!Reminder::decode(bytes,sizeof(bytes),reboot));
  assert(reboot.contains(id)); // Failed decode does not corrupt active state.
  for(size_t i=1;i<Reminder::CAPACITY;++i) {
    id[0]="0123456789abcdef"[i];
    assert(c.add(id,now+60,now));
  }
  id[0]='b'; id[1]='b';
  assert(!c.add(id,now+120,now)); // No eviction of live IDs.
  assert(c.add(id,now+120,now+61)); // Expired slots can be reused.
  assert(Reminder::buzzerOn(0,false,0));
  assert(!Reminder::buzzerOn(200,false,0));
  assert(!Reminder::buzzerOn(300,false,0));
  assert(Reminder::buzzerOn(300,true,0));
  assert(!Reminder::buzzerOn(450,true,0));
  assert(!Reminder::buzzerOn(10000,true,0));
  assert(!Reminder::buzzerOn(0,true,1)); // Fall cancellation window stays silent.
  assert(!Reminder::buzzerOn(0,true,2)); // Alarm owns output.
  uint32_t start=0xffffff00u, current=100u;
  assert(Reminder::buzzerOn(uint32_t(current-start),true,0)); // millis wrap.
  uint32_t word=Reminder::soundWord(start,true);
  assert(word & Reminder::SOUND_ACTIVE);
  assert(word & Reminder::SOUND_MISSED);
  assert(Reminder::soundElapsed(current,word)==356u);
  assert(Reminder::soundElapsed(Reminder::CLOCK_MASK+100u,
         Reminder::soundWord(Reminder::CLOCK_MASK-200u,false))==300u);
  puts("PASS reminder persistence, capacity, expiry, sounds and emergency priority");
}
