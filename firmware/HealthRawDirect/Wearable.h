#pragma once
#include <Preferences.h>
#include "WearableConfig.h"
#include "MpuProfile.h"
#include "AlertJournal.h"
#include <sys/time.h>

SemaphoreHandle_t sensorMutex=nullptr, alertMutex=nullptr;
TaskHandle_t wearableHandle=nullptr;
std::atomic<bool> emergency{false}, captureInterrupted{false}, wearableFault{false};
std::atomic<bool> mpuHealthy{false};
std::atomic<uint32_t> mpuLastSample{0};
std::atomic<int> mpuBusError{-1}, mpuIdentity{-1};
std::atomic<bool> ledTesting{false};
std::atomic<uint32_t> ledTestStarted{0};
void writeIndicator(uint8_t pin,bool on,uint8_t activeLevel) {
  digitalWrite(pin,on?activeLevel:!activeLevel);
}
AlertJournal alertJournal{};
Preferences alertPrefs;
bool alertStorageOK=false;
uint32_t graceStarted=0;
struct AlertCommand { char eventId[40], commandId[40]; };
QueueHandle_t alertCommands=nullptr, simulationCommands=nullptr;

// Access to this shared scratch buffer is protected by alertMutex (or startup before tasks).
uint8_t alertCodecBuffer[ALERT_READ_MAX];
bool persistAlerts() {
  size_t length=encodeAlertJournal(alertJournal,alertCodecBuffer,sizeof(alertCodecBuffer));
  size_t written=alertStorageOK && length?alertPrefs.putBytes("journal_v3",alertCodecBuffer,length):0;
  bool ok=alertStorageOK && length && written==length;
  if (!ok) {
    wearableFault=true; captureInterrupted=true;
    Serial.printf("ALERT STORAGE ERROR: storageReady=%d schemaValid=%d encoded=%u written=%u freeEntries=%u phase=%u count=%u\n",
                  alertStorageOK,alertJournalValid(alertJournal),unsigned(length),unsigned(written),
                  unsigned(alertStorageOK?alertPrefs.freeEntries():0),alertJournal.phase,alertJournal.count);
    Serial.println(!alertStorageOK?"JOURNAL BLOCKED: doc JOURNAL READ tu dau log; khong FORMAT.":
                   !length?"JOURNAL INVALID: khong ghi de du lieu; can kiem tra schema/state.":
                           "NVS WRITE FAILED: kiem tra dung luong/NVS; khong xoa ban goc.");
  }
  return ok;
}
void loadAlerts() {
  alertStorageOK=alertPrefs.begin("wearable",false);
  if (!alertStorageOK) { wearableFault=true; Serial.println("ERROR: cannot open alert NVS namespace"); return; }
  const char* key=alertPrefs.isKey("journal_v3")?"journal_v3":"journal";
  bool existing=alertPrefs.isKey(key);
  size_t length=alertPrefs.getBytesLength(key);
  if (!existing) {
    alertJournal.magic=ALERT_MAGIC;
    if (persistAlerts()) Serial.println("JOURNAL V3: initialized (raw LittleFS unchanged).");
    return;
  }
  bool readOK=length && length<=sizeof(alertCodecBuffer) && alertPrefs.getBytes(key,alertCodecBuffer,length)==length;
  bool legacy=!strcmp(key,"journal");
  bool valid=readOK && (legacy?decodeLegacyAlertJournal(alertCodecBuffer,length,alertJournal):
                               decodeAlertJournal(alertCodecBuffer,length,alertJournal));
  Serial.printf("JOURNAL READ: key=%s bytes=%u decoded=%d\n",key,unsigned(length),valid);
  if (!valid) {
    memset(&alertJournal,0,sizeof(alertJournal)); alertStorageOK=false; wearableFault=true;
    Serial.println("ERROR: alert journal CRC/schema; original NVS key preserved. Khong FORMAT/xoa NVS.");
    return;
  }
  if (legacy) {
    // Original journal key is retained as an exact backup. Only write the independent V3 key.
    if (persistAlerts()) Serial.printf("JOURNAL MIGRATED V3: events=%u alarm=%u; giu ban goc journal.\n",alertJournal.count,alertJournal.phase);
  } else Serial.printf("JOURNAL V3 OK: events=%u alarm=%u\n",alertJournal.count,alertJournal.phase);
}
bool appendAlert() {
  if (alertJournal.count>=EVENT_CAPACITY) {
    Serial.println("ALERT QUEUE FULL: giu cac su kien cu; can ket noi collector."); return false;
  }
  alertJournal.pending[alertJournal.count++]=alertJournal.current;
  alertJournal.currentQueued=true;
  return true;
}
void createAlert(const char* kind, bool grace) {
  xSemaphoreTake(alertMutex,portMAX_DELAY);
  if (alertJournal.phase==2 || (alertJournal.phase==1 && grace)) { xSemaphoreGive(alertMutex); return; }
  alertJournal.currentQueued=false;
  memset(&alertJournal.current,0,sizeof(AlertRecord));
  snprintf(alertJournal.current.eventId,40,"%08lx%08lx-%08lx",(unsigned long)esp_random(),(unsigned long)esp_random(),(unsigned long)millis());
  snprintf(alertJournal.current.kind,8,"%s",kind);
  snprintf(alertJournal.current.state,12,"%s",grace?"pending":"active");
  alertJournal.current.revision=1;
  alertJournal.current.uptimeMs=millis();
  alertJournal.current.occurredAt=time(nullptr)>=1700000000?time(nullptr):0;
  alertJournal.phase=grace?1:2; graceStarted=millis();
  emergency=true; captureInterrupted=true;
  if (!grace) appendAlert();
  persistAlerts();
  Serial.printf("ALERT %s: %s id=%s\n",kind,grace?"cho huy 6 giay":"BAO DONG",alertJournal.current.eventId);
  xSemaphoreGive(alertMutex);
}
void clearAlert(const char* commandId="") {
  // Caller holds alertMutex. Clearing is an event, NOT deleting alarm history.
  bool wasActive=alertJournal.phase==2;
  AlertRecord previous=alertJournal.current;
  uint8_t previousPhase=alertJournal.phase, previousCount=alertJournal.count;
  bool previousQueued=alertJournal.currentQueued;
  alertJournal.currentQueued=false;
  snprintf(alertJournal.current.state,12,"cleared");
  snprintf(alertJournal.current.commandId,40,"%s",commandId);
  alertJournal.current.revision++;
  alertJournal.current.uptimeMs=millis();
  alertJournal.current.occurredAt=time(nullptr)>=1700000000?time(nullptr):0;
  if ((wasActive || *commandId) && !appendAlert()) {
    alertJournal.current=previous; alertJournal.count=previousCount;
    alertJournal.phase=previousPhase; alertJournal.currentQueued=previousQueued;
    return; // Never discard an unsent event to make room for a command response.
  }
  alertJournal.phase=0;
  if (!persistAlerts()) {
    alertJournal.current=previous; alertJournal.count=previousCount;
    alertJournal.phase=previousPhase; alertJournal.currentQueued=previousQueued; return;
  }
  emergency=false;
  Serial.println("ALERT CLEARED: tiep tuc giam sat; khong tat nguon.");
}
bool pendingAlerts() {
  xSemaphoreTake(alertMutex,portMAX_DELAY);
  bool pending=alertJournal.count || alertJournal.phase || wearableFault.load();
  xSemaphoreGive(alertMutex); return pending;
}
void alertAck(const char* eventId, uint32_t revision) {
  xSemaphoreTake(alertMutex,portMAX_DELAY);
  if (alertJournal.count && !strcmp(eventId,alertJournal.pending[0].eventId) && revision==alertJournal.pending[0].revision) {
    AlertRecord removed=alertJournal.pending[0];
    --alertJournal.count;
    memmove(alertJournal.pending,alertJournal.pending+1,alertJournal.count*sizeof(AlertRecord));
    if (!persistAlerts()) {
      memmove(alertJournal.pending+1,alertJournal.pending,alertJournal.count*sizeof(AlertRecord));
      alertJournal.pending[0]=removed; ++alertJournal.count;
    } else Serial.printf("EVENT ACK: id=%s revision=%lu pending=%u\n",eventId,(unsigned long)revision,alertJournal.count);
  }
  xSemaphoreGive(alertMutex);
}
void publishAlert() {
  static uint32_t lastSend=0;
  if (millis()-lastSend<2000 || !mqtt.connected()) return;
  AlertRecord record{}; bool available=false;
  xSemaphoreTake(alertMutex,portMAX_DELAY);
  if (alertJournal.count) { record=alertJournal.pending[0]; available=true; }
  xSemaphoreGive(alertMutex);
  if (!available) return;
  JsonDocument d;
  d["schema_version"]=1; d["device_id"]=DEVICE_ID;
  d["event_id"]=record.eventId; d["revision"]=record.revision;
  d["kind"]=record.kind; d["state"]=record.state;
  d["uptime_ms"]=record.uptimeMs; d["occurred_at"]=record.occurredAt;
  d["command_id"]=record.commandId; d["detector"]="pendant_sequence_trial_v1";
  char payload[640]; serializeJson(d,payload,sizeof(payload));
  lastSend=millis();
  if (mqtt.publish((String("iot/")+DEVICE_ID+"/event").c_str(),payload))
    Serial.printf("EVENT SENT: id=%s revision=%lu state=%s; cho collector ACK.\n",
                  record.eventId,(unsigned long)record.revision,record.state);
}
bool mpuWrite(uint8_t reg, uint8_t value) {
  Wire.beginTransmission(MPU_ADDRESS); Wire.write(reg); Wire.write(value);
  return Wire.endTransmission()==0;
}
bool mpuRead(float* v) {
  Wire.beginTransmission(MPU_ADDRESS); Wire.write(0x3B);
  int bus=Wire.endTransmission(false); mpuBusError=bus;
  if (bus!=0 || Wire.requestFrom(MPU_ADDRESS,uint8_t(14))!=14) {
    if (!bus) mpuBusError=-2; // Incomplete read.
    while (Wire.available()) Wire.read(); return false;
  }
  int16_t raw[7];
  for (int i=0;i<7;i++) raw[i]=int16_t((uint16_t(Wire.read())<<8)|uint8_t(Wire.read()));
  for (int i=0;i<3;i++) v[i]=raw[i]/4096.0f; // +/-8g
  for (int i=0;i<3;i++) v[i+3]=raw[i+4]/32.8f; // +/-1000 degrees/s
  return true;
}
// Caller owns Wire (before the task starts, or while holding sensorMutex).
void scanWearableBus() {
  Serial.print("I2C SCAN GPIO21=SDA GPIO22=SCL:");
  unsigned found=0;
  for (uint8_t address=8;address<120;address++) {
    Wire.beginTransmission(address);
    if (Wire.endTransmission()==0) { Serial.printf(" 0x%02X",address); ++found; }
  }
  if (!found) Serial.print(" KHONG THAY THIET BI");
  Serial.println("; can MAX=0x57 MLX=0x5A MPU=0x68 (AD0=GND)");
}
bool mpuReadByte(uint8_t reg,uint8_t& value) {
  Wire.beginTransmission(MPU_ADDRESS); Wire.write(reg);
  int bus=Wire.endTransmission(false); mpuBusError=bus;
  if (bus!=0) return false;
  if (Wire.requestFrom(MPU_ADDRESS,uint8_t(1))!=1) { mpuBusError=-2; return false; }
  value=Wire.read(); return true;
}
bool initMpu() {
  mpuIdentity=-1;
  uint8_t who=0;
  if (!mpuReadByte(0x75,who)) return false;
  mpuIdentity=who;
  const char* model=mpuModelName(who);
  if (!model) { mpuBusError=-3; return false; }
  bool ok=mpuWrite(0x6B,0x01) && mpuWrite(0x6C,0x00) && mpuWrite(0x1A,0x03) &&
          mpuWrite(0x19,9) && mpuWrite(0x1B,0x10) && mpuWrite(0x1C,0x10);
  // MPU6500/6515 have an independent acceleration filter at 0x1D.
  if (ok && mpuHasAccelFilter(who)) ok=mpuWrite(0x1D,0x03);
  if (!ok) { mpuBusError=-4; return false; }
  uint8_t gyro=0,accel=0,divider=0,filter=0,power=0,axes=0;
  if (!mpuReadByte(0x1B,gyro) || !mpuReadByte(0x1C,accel) || !mpuReadByte(0x19,divider) ||
      !mpuReadByte(0x1A,filter) || !mpuReadByte(0x6B,power) || !mpuReadByte(0x6C,axes)) return false;
  if ((gyro&0x1B)!=0x10 || (accel&0x18)!=0x10 || divider!=9 || (filter&7)!=3 ||
      (power&0x60) || (axes&0x3F)) { mpuBusError=-5; return false; }
  if (mpuHasAccelFilter(who)) {
    uint8_t af=0;
    if (!mpuReadByte(0x1D,af)) return false;
    if ((af&0x0F)!=3) { mpuBusError=-5; return false; }
  }
  Serial.printf("MPU OK: %s WHO_AM_I=0x%02X addr=0x%02X; 100Hz +/-8g +/-1000dps\n",model,who,MPU_ADDRESS);
  return true;
}
void wearableTask(void*) {
  FallDetector detector; detector.config=trialFallConfig();
  bool stablePressed=false, rawPrevious=false, holdDone=false;
  uint32_t changed=millis(), pressedAt=0, lastMpuTry=0, lastLog=0;
  uint32_t lastFaultLog=0;
  bool justCleared=false;
  uint32_t clearedAt=0;
  TickType_t tick=xTaskGetTickCount();
  for (;;) {
    uint32_t now=millis();
    bool pressed=digitalRead(SOS_PIN)==LOW;
    if (pressed!=rawPrevious) { rawPrevious=pressed; changed=now; }
    if (now-changed>=30 && pressed!=stablePressed) {
      stablePressed=pressed;
      if (pressed) { pressedAt=now; holdDone=false; }
      else if (!holdDone && now-pressedAt>=30) createAlert("sos",false);
    }
    if (stablePressed && !holdDone && now-pressedAt>=CANCEL_HOLD_MS) {
      holdDone=true;
      xSemaphoreTake(alertMutex,portMAX_DELAY);
      if (alertJournal.phase) { clearAlert(); justCleared=true; clearedAt=now; detector.reset(); }
      xSemaphoreGive(alertMutex);
    }
    AlertCommand cmd{};
    if (xQueueReceive(alertCommands,&cmd,0)==pdTRUE) {
      xSemaphoreTake(alertMutex,portMAX_DELAY);
      if (alertJournal.phase && !strcmp(cmd.eventId,alertJournal.current.eventId)) {
        clearAlert(cmd.commandId); justCleared=true; clearedAt=now; detector.reset();
      }
      xSemaphoreGive(alertMutex);
    }
    char simulation=0;
    if (ENABLE_SERIAL_SIMULATION && xQueueReceive(simulationCommands,&simulation,0)==pdTRUE)
      createAlert(simulation=='F'?"fall":"sos",simulation=='F');
    now=millis(); // NVS writes may advance time; avoid unsigned grace underflow.
    xSemaphoreTake(alertMutex,portMAX_DELAY);
    if (alertJournal.phase==1 && now-graceStarted>=FALL_CANCEL_MS) {
      snprintf(alertJournal.current.state,12,"active");
      alertJournal.current.uptimeMs=now;
      alertJournal.current.occurredAt=time(nullptr)>=1700000000?time(nullptr):0;
      alertJournal.phase=2; appendAlert(); persistAlerts();
      Serial.println("FALL CONFIRMED: LED do + coi; cho ACK luu su kien.");
    }
    if (alertJournal.phase==2 && !alertJournal.currentQueued && alertJournal.count<EVENT_CAPACITY) {
      appendAlert(); persistAlerts();
    }
    uint8_t phase=alertJournal.phase;
    xSemaphoreGive(alertMutex);
    bool blink=now%1000<150;
    bool sending=sound.load()==SoundMode::WAITING || eventSending.load();
    // Alarm > sending > measuring. Green/blue must never accompany an active alarm.
    bool redOn=phase && now%500<250;
    bool greenOn=!phase && sending && blink;
    bool blueOn=!phase && !sending && sound.load()==SoundMode::MEASURING && mpuHealthy.load();
    static int previousTestStep=-1;
    if (phase && ledTesting.exchange(false)) Serial.println("LED_TEST ABORT: bao dong uu tien LED do.");
    if (ledTesting.load()) {
      uint32_t testStarted=ledTestStarted.load();
      uint32_t step=(millis()-testStarted)/1000;
      if (step<5) {
        redOn=step==1; greenOn=step==2; blueOn=step==3;
        if (int(step)!=previousTestStep) {
          previousTestStep=step;
          Serial.printf("LED_TEST step=%lu %s RED26=%d GREEN27=%d BLUE32=%d\n",(unsigned long)step,
                        step==1?"RED_ONLY":step==2?"GREEN_ONLY":step==3?"BLUE_ONLY":"ALL_OFF",redOn,greenOn,blueOn);
        }
      } else {
        ledTesting=false; previousTestStep=-1;
        Serial.println("LED_TEST DONE: tro ve trang thai do/gui/bao dong.");
      }
    } else previousTestStep=-1;
    writeIndicator(LED_RED_PIN,redOn,LED_RED_ON_LEVEL);
    static uint32_t reminderStarted = 0, previousReminderUntil = 0;
    uint32_t until = reminderUntil.load();
    if (until != previousReminderUntil) { previousReminderUntil = until; reminderStarted = now; }
    uint32_t reminderPhase = (now - reminderStarted) % 2000UL;
    bool reminderOn = until && int32_t(until - now) > 0 &&
      (reminderPhase < 200UL || (reminderMissed.load() && reminderPhase >= 300UL && reminderPhase < 450UL));
    // Emergency/grace owns the buzzer; reminders never mask an SOS/fall alarm.
    buzzerWrite(phase ? (phase==2 && now%500<250) : reminderOn);
    writeIndicator(LED_BLUE_PIN,blueOn,LED_BLUE_ON_LEVEL);
    writeIndicator(LED_GREEN_PIN,greenOn,LED_GREEN_ON_LEVEL);
    static uint32_t lastLedLog=0;
    if (now-lastLedLog>=5000) {
      lastLedLog=now;
      Serial.printf("LED STATUS: red=%d green=%d blue=%d alarm=%u measure=%d sending=%d; pin26=%d pin27=%d pin32=%d\n",
                    redOn,greenOn,blueOn,phase,sound.load()==SoundMode::MEASURING,sending,
                    digitalRead(LED_RED_PIN),digitalRead(LED_GREEN_PIN),digitalRead(LED_BLUE_PIN));
    }
    float v[6]; bool readOK=false, attemptedRead=false;
    if (xSemaphoreTake(sensorMutex,pdMS_TO_TICKS(2))==pdTRUE) {
      attemptedRead=true;
      if (!mpuHealthy.load() && now-lastMpuTry>=1000) { lastMpuTry=now; mpuHealthy=initMpu(); }
      if (mpuHealthy.load()) readOK=mpuRead(v);
      xSemaphoreGive(sensorMutex);
      if (!readOK) mpuHealthy=false;
    }
    if (readOK) {
      mpuLastSample=now;
      if (justCleared && now-clearedAt>=FALL_CANCEL_MS) justCleared=false;
      if (!phase && !justCleared && detector.update(now,v[0],v[1],v[2],v[3],v[4],v[5])) createAlert("fall",true);
      else if (phase || justCleared) detector.reset();
      if (now-lastLog>=1000) {
        lastLog=now;
        Serial.printf("IMU g=%.2f,%.2f,%.2f dps=%.1f,%.1f,%.1f stage=%d alarm=%u\n",v[0],v[1],v[2],v[3],v[4],v[5],int(detector.stage),phase);
      }
    } else {
      if (attemptedRead || now-mpuLastSample.load()>100) detector.reset();
      if (now-mpuLastSample.load()>100 && now-lastFaultLog>=5000) {
        lastFaultLog=now;
        Serial.printf("MPU ERROR: addr=0x%02X bus=%d WHO_AM_I=%d age_ms=%lu; SOS van hoat dong.\n",
                      MPU_ADDRESS,mpuBusError.load(),mpuIdentity.load(),(unsigned long)(now-mpuLastSample.load()));
        Serial.printf("LED OUT: RED26=%d GREEN27=%d BLUE32=%d (1=sang neu LED noi GPIO->R->LED->GND).\n",
                      redOn,greenOn,blueOn);
      }
    }
    vTaskDelayUntil(&tick,pdMS_TO_TICKS(10));
  }
}
void startWearable() {
  sensorMutex=xSemaphoreCreateMutex(); alertMutex=xSemaphoreCreateMutex();
  alertCommands=xQueueCreate(4,sizeof(AlertCommand)); simulationCommands=xQueueCreate(4,sizeof(char));
  for (uint8_t pin:{LED_RED_PIN,LED_GREEN_PIN,LED_BLUE_PIN}) pinMode(pin,OUTPUT);
  writeIndicator(LED_RED_PIN,false,LED_RED_ON_LEVEL);
  writeIndicator(LED_GREEN_PIN,false,LED_GREEN_ON_LEVEL);
  writeIndicator(LED_BLUE_PIN,false,LED_BLUE_ON_LEVEL);
  pinMode(SOS_PIN,INPUT_PULLUP);
  if (!sensorMutex || !alertMutex || !alertCommands || !simulationCommands) {
    Serial.println("ERROR: wearable task resources"); while(true) delay(1000);
  }
  loadAlerts();
  emergency=alertJournal.phase!=0; graceStarted=millis();
  scanWearableBus();
  mpuHealthy=initMpu();
  if (xTaskCreatePinnedToCore(wearableTask,"wearable",8192,nullptr,2,&wearableHandle,1)!=pdPASS) {
    Serial.println("ERROR: wearable task"); while(true) delay(1000);
  }
  Serial.println("WEARABLE: giam sat lien tuc; fall thresholds EXPERIMENTAL. Serial SIM disabled by default.");
}
void serialWearable() {
  static String command;
  while (Serial.available()) {
    char c=Serial.read();
    if (c=='\n' || c=='\r') {
      command.trim();
      if (command=="LED_TEST") {
        if (emergency.load()) Serial.println("LED_TEST blocked: giu SOS 2 giay de huy bao dong truoc.");
        else {
          ledTestStarted=millis(); ledTesting=true;
          Serial.println("LED_TEST: ALL_OFF -> RED26 -> GREEN27 -> BLUE32 -> ALL_OFF, moi buoc 1s; SOS van hoat dong.");
        }
      } else if (command.startsWith("TIME ")) {
        const char* text=command.c_str()+5;
        char* end=nullptr; errno=0;
        long long epoch=strtoll(text,&end,10);
        if (!errno && end!=text && *end=='\0' && epoch>=1700000000LL && epoch<=4102444800LL) {
          timeval clockValue{}; clockValue.tv_sec=epoch;
          if (!settimeofday(&clockValue,nullptr)) Serial.printf("TIME SET manually: %lld; TLS CA/hostname van duoc kiem tra.\n",epoch);
          else Serial.println("TIME SET failed");
        } else Serial.println("TIME invalid: use TIME <Unix seconds from trusted computer>.");
      } else if (command=="SIM_FALL" || command=="SIM_SOS") {
        if (ENABLE_SERIAL_SIMULATION) {
          char mode=command=="SIM_FALL"?'F':'S';
          if (xQueueSend(simulationCommands,&mode,0)!=pdTRUE) Serial.println("SIM queue full");
        } else Serial.println("SIM disabled: set ENABLE_SERIAL_SIMULATION=true for bench tests only.");
      }
      command="";
    } else if (command.length()<32) command+=c;
  }
}
