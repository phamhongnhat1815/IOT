#pragma once
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include "FirmwareTypes.h"

constexpr uint32_t ALERT_MAGIC=0x57454132;
constexpr uint32_t ALERT_WIRE_MAGIC=0x57454133;
constexpr uint8_t EVENT_CAPACITY=32;
struct AlertRecord {
  char eventId[40], kind[8], state[12], commandId[40];
  uint32_t revision, uptimeMs;
  int64_t occurredAt;
};
struct AlertJournal {
  uint32_t magic;
  uint8_t count, phase;
  bool currentQueued;
  AlertRecord current, pending[EVENT_CAPACITY];
  uint32_t crc; // Legacy in-memory field; V3 CRC covers encoded bytes, never struct padding.
};
constexpr size_t ALERT_RECORD_BYTES=116;
constexpr size_t ALERT_HEADER_BYTES=11;
constexpr size_t ALERT_ENCODED_MAX=ALERT_HEADER_BYTES+ALERT_RECORD_BYTES*(EVENT_CAPACITY+1)+4;
constexpr size_t ALERT_READ_MAX=4096;

inline uint32_t alertBytesCrc(const uint8_t* bytes,size_t length) {
  return crc32Update(0xffffffffUL,bytes,length)^0xffffffffUL;
}
inline uint32_t alertGet32(const uint8_t* p) {
  return uint32_t(p[0]) | uint32_t(p[1])<<8 | uint32_t(p[2])<<16 | uint32_t(p[3])<<24;
}
inline void alertPut32(uint8_t* p,uint32_t v) {
  for (int i=0;i<4;i++) p[i]=uint8_t(v>>(8*i));
}
inline bool alertIdValid(const char* value,size_t capacity,bool emptyOK=false) {
  size_t n=strnlen(value,capacity);
  if (n==capacity || (!n && !emptyOK)) return false;
  for(size_t i=0;i<n;i++) {
    char c=value[i];
    if (!((c>='a'&&c<='z') || (c>='A'&&c<='Z') || (c>='0'&&c<='9') || c=='-' || c=='_')) return false;
  }
  return true;
}
inline bool alertRecordValid(const AlertRecord& r,bool current=false) {
  if (!alertIdValid(r.eventId,sizeof(r.eventId))) return false;
  if (!memchr(r.kind,0,sizeof(r.kind)) || !memchr(r.state,0,sizeof(r.state)) ||
      !alertIdValid(r.commandId,sizeof(r.commandId),true)) return false;
  if (strcmp(r.kind,"fall") && strcmp(r.kind,"sos")) return false;
  if (r.occurredAt<0 || r.occurredAt>4102444800LL) return false;
  if (!strcmp(r.state,"active")) return r.revision==1 && !*r.commandId;
  if (!strcmp(r.state,"cleared")) return r.revision==2;
  return current && !strcmp(r.state,"pending") && r.revision==1 && !*r.commandId;
}
inline bool alertJournalValid(const AlertJournal& j) {
  if (j.magic!=ALERT_MAGIC || j.count>EVENT_CAPACITY || j.phase>2) return false;
  if (j.phase && !alertRecordValid(j.current,true)) return false;
  if (j.phase==1 && strcmp(j.current.state,"pending")) return false;
  if (j.phase==2 && strcmp(j.current.state,"active")) return false;
  if (!j.phase && *j.current.eventId && (!alertRecordValid(j.current,true) || strcmp(j.current.state,"cleared"))) return false;
  for(uint8_t i=0;i<j.count;i++) if (!alertRecordValid(j.pending[i])) return false;
  return true;
}
inline void alertEncodeRecord(uint8_t* p,const AlertRecord& r) {
  memcpy(p,r.eventId,40); memcpy(p+40,r.kind,8); memcpy(p+48,r.state,12); memcpy(p+60,r.commandId,40);
  alertPut32(p+100,r.revision); alertPut32(p+104,r.uptimeMs);
  uint64_t epoch=uint64_t(r.occurredAt);
  for(int i=0;i<8;i++) p[108+i]=uint8_t(epoch>>(8*i));
}
inline void alertDecodeRecord(const uint8_t* p,AlertRecord& r,bool legacy=false) {
  memset(&r,0,sizeof(r));
  memcpy(r.eventId,p,40); memcpy(r.kind,p+40,8); memcpy(r.state,p+48,12); memcpy(r.commandId,p+60,40);
  r.revision=alertGet32(p+100); r.uptimeMs=alertGet32(p+104);
  uint64_t epoch=0; size_t offset=legacy?112:108;
  for(int i=0;i<8;i++) epoch |= uint64_t(p[offset+i])<<(8*i);
  r.occurredAt=int64_t(epoch);
}
inline size_t encodeAlertJournal(const AlertJournal& j,uint8_t* out,size_t capacity) {
  size_t length=ALERT_HEADER_BYTES+ALERT_RECORD_BYTES*(size_t(j.count)+1)+4;
  if (capacity<length || !alertJournalValid(j)) return 0;
  alertPut32(out,ALERT_WIRE_MAGIC); out[4]=3; out[5]=0;
  out[6]=j.count; out[7]=j.phase; out[8]=j.currentQueued?1:0;
  out[9]=out[10]=0;
  alertEncodeRecord(out+ALERT_HEADER_BYTES,j.current);
  for(uint8_t i=0;i<j.count;i++) alertEncodeRecord(out+ALERT_HEADER_BYTES+ALERT_RECORD_BYTES*(i+1),j.pending[i]);
  alertPut32(out+length-4,alertBytesCrc(out,length-4));
  return length;
}
inline bool decodeAlertJournal(const uint8_t* in,size_t length,AlertJournal& j) {
  if (length<ALERT_HEADER_BYTES+ALERT_RECORD_BYTES+4 || alertGet32(in)!=ALERT_WIRE_MAGIC ||
      in[4]!=3 || in[5]!=0 || in[6]>EVENT_CAPACITY || in[8]>1 || in[9] || in[10]) return false;
  if (length!=ALERT_HEADER_BYTES+ALERT_RECORD_BYTES*(size_t(in[6])+1)+4 ||
      alertGet32(in+length-4)!=alertBytesCrc(in,length-4)) return false;
  memset(&j,0,sizeof(j)); j.magic=ALERT_MAGIC; j.count=in[6]; j.phase=in[7]; j.currentQueued=in[8]!=0;
  alertDecodeRecord(in+ALERT_HEADER_BYTES,j.current);
  for(uint8_t i=0;i<j.count;i++) alertDecodeRecord(in+ALERT_HEADER_BYTES+ALERT_RECORD_BYTES*(i+1),j.pending[i]);
  return alertJournalValid(j);
}
inline bool decodeLegacyAlertJournal(const uint8_t* in,size_t length,AlertJournal& j) {
  // ESP32 ABI used by earlier releases: 8-byte header, 120-byte records, 4-byte CRC + 4 tail padding.
  unsigned oldCapacity=length==2056?16:(length==3976?32:0);
  if (!oldCapacity || alertGet32(in)!=ALERT_MAGIC || in[4]>oldCapacity || in[5]>2) return false;
  size_t crcOffset=8+120*(oldCapacity+1);
  if (alertGet32(in+crcOffset)!=alertBytesCrc(in,crcOffset)) return false;
  memset(&j,0,sizeof(j)); j.magic=ALERT_MAGIC; j.count=in[4]; j.phase=in[5];
  alertDecodeRecord(in+8,j.current,true);
  for(uint8_t i=0;i<j.count;i++) alertDecodeRecord(in+8+120*(i+1),j.pending[i],true);
  // Earlier firmware had no currentQueued field; padding must not be interpreted as a bool.
  // A duplicate active replay after migration is safe (server is idempotent).
  for(uint8_t i=0;i<j.count;i++)
    if (!memcmp(j.current.eventId,j.pending[i].eventId,40) && j.current.revision==j.pending[i].revision) j.currentQueued=true;
  return alertJournalValid(j);
}
