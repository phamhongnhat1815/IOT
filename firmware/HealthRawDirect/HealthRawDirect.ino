
#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <time.h>
#include <Wire.h>
#include <LittleFS.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <Adafruit_MLX90614.h>
#include "MAX30105.h"
#include "FirmwareTypes.h"
#include "MqttCloud.h"
#include "WiFiConfig.h"
#include <driver/gpio.h>
#include <esp_sleep.h>
#include <esp_system.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <atomic>
#include <math.h>
#include <errno.h>
#include <Preferences.h>
#include "Reminder.h"

SET_LOOP_TASK_STACK_SIZE(12288);

// ================= SUA THONG TIN CUA M =================


const char* MQTT_SERVER = CLOUD_HOST;
const char* MQTT_USER = CLOUD_USER;
const char* MQTT_PASSWORD = CLOUD_PASSWORD;
const char* DEVICE_ID = "esp32-01"; // letters, digits, '-' or '_'; max 31 characters
constexpr uint16_t MQTT_PORT = CLOUD_PORT;
constexpr uint32_t FINGER_THRESHOLD = 50000;
constexpr uint8_t BUZZER_ON_LEVEL = LOW;
// =======================================================
constexpr uint8_t BUZZER_PIN = 25;
constexpr uint8_t SDA_PIN = 21, SCL_PIN = 22, MAX_ADDRESS = 0x57;
constexpr uint8_t MAX_SAVED_SESSIONS = 8;
constexpr uint32_t CONTACT_STABLE_MS = 1000;
constexpr uint32_t ACK_RETRY_MS = 2000;
constexpr uint16_t MQTT_RESPONSE_TIMEOUT_S=15;
constexpr uint32_t MQTT_RECONNECT_MS=10000;
// A full cloud backlog needs more than 20s; do not starve at batch 25 on every boot.
constexpr uint32_t REPLAY_BUDGET_MS = 300000;
constexpr uint32_t UPLOAD_BUDGET_MS = 300000;
constexpr uint32_t ACK_WAIT_MS = 120000; // Stop early when one batch makes no progress.
constexpr uint32_t MAX_DRAIN_GAP_US = 100000;
constexpr size_t MQTT_BYTES = 2304;

MAX30105 maxSensor;
Adafruit_MLX90614 mlx;
// PubSubClient waits synchronously for CONNACK/packet bytes. Yield while empty so
// a slow broker cannot spin a CPU core and starve its idle task/watchdog.
class CooperativeSecureClient : public WiFiClientSecure {
 public:
  int available() override {
    int bytes=WiFiClientSecure::available();
    if (bytes<=0) delay(1);
    return bytes;
  }
};
CooperativeSecureClient transport;
PubSubClient mqtt(transport);
RawSession session{};
bool maxReady = false, filesystemReady = false, capturing = false;
bool flashProblem = false;
float objectTemp = NAN, ambientTemp = NAN;
uint32_t lastTemperatureMs = 0, lastDrainUs = 0, lastSampleMs = 0;
uint32_t contactSince = 0, lastLog = 0, attempts = 0, latestIR = 0;
uint32_t lostEvents = 0;
String rawTopic, ackTopic;
String reminderTopic, reminderAckTopic;
Preferences reminderPrefs;
Reminder::Cache reminderCache;
bool reminderStorageReady = false;
// One 32-bit atomic snapshot; no 64-bit atomic dependency on ESP32.
std::atomic<uint32_t> reminderSound{0};
std::atomic<uint16_t> expectedAckBatch{0};
std::atomic<bool> ackReceived{false}, packetWasSent{false};
std::atomic<SoundMode> sound{SoundMode::QUIET};
void buzzerWrite(bool on) {
  digitalWrite(BUZZER_PIN, on ? BUZZER_ON_LEVEL : !BUZZER_ON_LEVEL);
}
std::atomic<bool> eventSending{false};
#include "Wearable.h"
SemaphoreHandle_t mqttMutex=nullptr;
TaskHandle_t networkHandle=nullptr;
void fatal(const char* reason) {
  Serial.print("ERROR: "); Serial.println(reason);
  sound.store(SoundMode::QUIET);
  // Preserve SOS/fall task even when measurement or storage needs attention.
  while (true) { serialWearable(); delay(10); }
}

bool identifierValid(const char* value, size_t capacity) {
  size_t length = strnlen(value, capacity);
  if (length == 0 || length >= capacity) return false;
  for (size_t i = 0; i < length; ++i) {
    char c = value[i];
    if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
          (c >= '0' && c <= '9') || c == '-' || c == '_')) return false;
  }
  return true;
}

bool sessionValid() {
  if (session.magic != SESSION_MAGIC || session.version != SESSION_VERSION ||
      session.sampleRate != SAMPLE_HZ || session.batchSize != PAIRS_PER_BATCH ||
      session.pairCount != SESSION_PAIRS || session.temperatureCount < MIN_TEMPERATURES ||
      session.temperatureCount > MAX_TEMPERATURES ||
      !identifierValid(session.deviceId, sizeof(session.deviceId)) ||
      !identifierValid(session.sessionId, sizeof(session.sessionId)) ||
      session.crc != sessionCrc(session)) return false;
  for (uint16_t i = 0; i < SESSION_PAIRS; ++i)
    if (session.pairs[i].ir > 262143 || session.pairs[i].red > 262143) return false;
  for (uint16_t i = 0; i < session.temperatureCount; ++i) {
    const Temperature& t = session.temperatures[i];
    if (t.sampleIndex >= SESSION_PAIRS || !isfinite(t.objectC) || !isfinite(t.ambientC) ||
        t.objectC < -70 || t.objectC > 380 || t.ambientC < -40 || t.ambientC > 125 ||
        (i == 0 && t.sampleIndex != 0) ||
        (i && t.sampleIndex <= session.temperatures[i - 1].sampleIndex)) return false;
  }
  return true;
}

bool loadSession(const String& path) {
  File file = LittleFS.open(path, FILE_READ);
  if (!file || file.size() != sizeof(session)) { if (file) file.close(); return false; }
  size_t count = file.read(reinterpret_cast<uint8_t*>(&session), sizeof(session));
  file.close();
  return count == sizeof(session) && sessionValid();
}

String rootPath(const char* name) {
  String path(name);
  return path.startsWith("/") ? path : String("/") + path;
}

void mountStorage() {
  filesystemReady = LittleFS.begin(false); // NEVER auto-format pending data on mount failure.
  if (filesystemReady) return;
  Serial.println("LittleFS chua mount duoc.");
  Serial.println("LAN DAU: gui FORMAT trong Serial Monitor de khoi tao phan vung file.");
  Serial.println("Neu da co du lieu cho gui: KHONG FORMAT; kiem tra partition/flash truoc.");
  String command;
  while (!filesystemReady) {
    while (Serial.available()) {
      char c = Serial.read();
      if (c == '\r' || c == '\n') {
        command.trim();
        if (command == "FORMAT") {
          if (LittleFS.format()) filesystemReady = LittleFS.begin(false);
          Serial.println(filesystemReady ? "LittleFS OK" : "FORMAT/MOUNT failed");
        }
        command = "";
      } else if (command.length() < 16) command += c;
    }
    delay(10);
  }
}

void recoverTemporaryFiles() {
  // Read directory names first; do not mutate an active directory iterator.
  String paths[16]; uint8_t count = 0;
  File root = LittleFS.open("/");
  for (File file = root.openNextFile(); file; file = root.openNextFile()) {
    String path = rootPath(file.name());
    if (path.startsWith("/raw_") && path.endsWith(".tmp")) {
      if (count < 16) paths[count++] = path; else flashProblem = true;
    }
    file.close();
  }
  root.close();
  for (uint8_t i = 0; i < count; ++i) {
    String ready = paths[i].substring(0, paths[i].length() - 4) + ".ready";
    if (loadSession(paths[i]) && !LittleFS.exists(ready) && LittleFS.rename(paths[i], ready))
      Serial.println("Recovered complete session after interrupted commit");
    else {
      flashProblem = true;
      Serial.println("ERROR: giu nguyen file .tmp khong hop le; khong tu xoa/bao thanh cong.");
    }
  }
}

uint8_t listPending(String* paths, uint8_t capacity) {
  uint8_t count = 0;
  File root = LittleFS.open("/");
  for (File file = root.openNextFile(); file; file = root.openNextFile()) {
    String path = rootPath(file.name());
    if (path.startsWith("/raw_") && path.endsWith(".ready")) {
      if (count < capacity) paths[count++] = path; else flashProblem = true;
    }
    file.close();
  }
  root.close();
  return count;
}

bool commitSession() {
  session.crc = sessionCrc(session);
  if (!sessionValid()) return false;
  String path = String("/raw_") + session.sessionId;
  String tempPath = path + ".tmp", readyPath = path + ".ready";
  if (LittleFS.exists(tempPath) || LittleFS.exists(readyPath)) return false;
  File file = LittleFS.open(tempPath, FILE_WRITE);
  if (!file) return false;
  size_t written = file.write(reinterpret_cast<const uint8_t*>(&session), sizeof(session));
  file.flush(); file.close();
  if (written != sizeof(session) || !loadSession(tempPath)) return false;
  return LittleFS.rename(tempPath, readyPath);
}

bool readRegister(uint8_t address, uint8_t& value) {
  Wire.beginTransmission(MAX_ADDRESS); Wire.write(address);
  if (Wire.endTransmission(false) != 0 || Wire.requestFrom(MAX_ADDRESS, uint8_t(1)) != 1) return false;
  value = Wire.read(); return true;
}

bool readSurfaceTemperature() {
  float object = mlx.readObjectTempC();
  float ambient = mlx.readAmbientTempC();
  lastTemperatureMs = millis();
  if (!isfinite(object) || !isfinite(ambient) || object < -70 || object > 380 || ambient < -40 || ambient > 125) {
    objectTemp = ambientTemp = NAN; return false;
  }
  objectTemp = object; ambientTemp = ambient;
  return true;
}

void resetCapture(const char* reason) {
  if (capturing) { Serial.print("DO LAI: "); Serial.println(reason); }
  capturing = false; contactSince = 0;
  session.pairCount = session.temperatureCount = 0;
  maxSensor.clearFIFO();
  lastDrainUs = micros();
}

void beginCapture() {
  memset(&session, 0, sizeof(session));
  session.magic = SESSION_MAGIC; session.version = SESSION_VERSION;
  session.sampleRate = SAMPLE_HZ; session.batchSize = PAIRS_PER_BATCH;
  session.createdMs = millis();
  snprintf(session.deviceId, sizeof(session.deviceId), "%s", DEVICE_ID);
  snprintf(session.sessionId, sizeof(session.sessionId), "%s-%08lx%08lx-%lu", DEVICE_ID,
           (unsigned long)esp_random(), (unsigned long)esp_random(), (unsigned long)++attempts);
  session.temperatures[0] = {0, lastTemperatureMs, objectTemp, ambientTemp};
  session.temperatureCount = 1;
  capturing = true;
  Serial.print("CAPTURE: "); Serial.println(session.sessionId);
}

bool acceptPair(uint32_t red, uint32_t ir) {
  latestIR = ir; lastSampleMs = millis();
  if (ir <= FINGER_THRESHOLD) {
    if (capturing) { resetCapture("mat tiep xuc ngon tay"); return false; }
    contactSince = 0; return true;
  }
  if (!capturing) {
    if (!contactSince) contactSince = millis();
    if (millis() - contactSince < CONTACT_STABLE_MS || !isfinite(objectTemp) ||
        !isfinite(ambientTemp) || millis() - lastTemperatureMs > 1500UL) return true;
    beginCapture();
  }
  uint16_t index = session.pairCount;
  if (index >= SESSION_PAIRS) return false;
  uint16_t batch = index / PAIRS_PER_BATCH;
  if (index % PAIRS_PER_BATCH == 0) session.batchStartUs[batch] = micros();
  session.pairs[index] = {red, ir};
  session.pairCount++;
  session.batchEndUs[batch] = micros();
  return session.pairCount < SESSION_PAIRS;
}

void drainFifo() {
  if (session.pairCount >= SESSION_PAIRS) return;
  uint32_t now = micros();
  if (capturing && now - lastDrainUs > MAX_DRAIN_GAP_US) {
    ++lostEvents; resetCapture("vong doc bi tre >100ms"); return;
  }
  lastDrainUs = now;
  uint8_t overflow = 0, writePtr = 0, readPtr = 0;
  if (!readRegister(0x05, overflow) || !readRegister(0x04, writePtr) || !readRegister(0x06, readPtr)) {
    ++lostEvents; resetCapture("I2C loi doc FIFO pointers"); return;
  }
  // Any overflow invalidates this acquisition; do not fake continuity.
  if (overflow & 0x1F) { ++lostEvents; resetCapture("FIFO overflow"); return; }
  uint8_t available = (writePtr - readPtr) & 0x1F;
  while (available--) {
    Wire.beginTransmission(MAX_ADDRESS); Wire.write(0x07);
    if (Wire.endTransmission(false) != 0 || Wire.requestFrom(MAX_ADDRESS, uint8_t(6)) != 6) {
      while (Wire.available()) Wire.read();
      ++lostEvents; resetCapture("I2C loi doc mau"); return;
    }
    uint32_t red = uint32_t(Wire.read()) << 16;
    red |= uint32_t(Wire.read()) << 8; red |= Wire.read();
    uint32_t ir = uint32_t(Wire.read()) << 16;
    ir |= uint32_t(Wire.read()) << 8; ir |= Wire.read();
    if (!acceptPair(red & 0x3FFFF, ir & 0x3FFFF)) return;
  }
}

bool acquireSession() {
  captureInterrupted=false;
  sound.store(SoundMode::MEASURING);
  capturing = false; contactSince = 0;
  session.pairCount = session.temperatureCount = 0;
  xSemaphoreTake(sensorMutex,portMAX_DELAY);
  readSurfaceTemperature();
  maxSensor.clearFIFO(); maxSensor.wakeUp();
  xSemaphoreGive(sensorMutex);
  lastDrainUs = micros(); lastSampleMs = millis();
  Serial.println("Dat ngon tay va giu yen ~16 giay. Khong can B=1.");
  while (session.pairCount < SESSION_PAIRS) {
    serialWearable();
    if (captureInterrupted.load() || emergency.load() || !mpuHealthy.load() || millis()-mpuLastSample.load()>100) {
      xSemaphoreTake(sensorMutex,portMAX_DELAY); maxSensor.shutDown(); xSemaphoreGive(sensorMutex);
      capturing=false; sound.store(SoundMode::QUIET);
      Serial.println("CAPTURE ABORT: uu tien SOS/nga/loi MPU; khong luu phien do dang."); return false;
    }
    xSemaphoreTake(sensorMutex,portMAX_DELAY);
    drainFifo();
    xSemaphoreGive(sensorMutex);
    if (session.pairCount >= SESSION_PAIRS) break;
    if (millis() - lastTemperatureMs >= 1000UL) {
      xSemaphoreTake(sensorMutex,portMAX_DELAY);
      bool valid = readSurfaceTemperature();
      if (!valid) resetCapture("nhiet do khong hop le");
      else if (capturing && session.temperatureCount < MAX_TEMPERATURES &&
               session.pairCount > session.temperatures[session.temperatureCount - 1].sampleIndex)
        session.temperatures[session.temperatureCount++] = {session.pairCount, lastTemperatureMs, objectTemp, ambientTemp};
      drainFifo();
      xSemaphoreGive(sensorMutex);
    }
    if (millis() - lastSampleMs > 3000UL) fatal("MAX30102 khong tra mau; kiem tra day/nguon");
    if (millis() - lastLog >= 1000UL) {
      lastLog = millis();
      Serial.printf("IR=%lu F=%d T=%d objectC=%.2f ambientC=%.2f samples=%u/1500 lost_events=%lu\n",
                    (unsigned long)latestIR, latestIR > FINGER_THRESHOLD,
                    isfinite(objectTemp) && isfinite(ambientTemp),objectTemp,ambientTemp,
                    session.pairCount, (unsigned long)lostEvents);
    }
    delay(1);
  }
  xSemaphoreTake(sensorMutex,portMAX_DELAY); maxSensor.shutDown(); xSemaphoreGive(sensorMutex); capturing = false;
  sound.store(SoundMode::QUIET);
  Serial.printf("CAPTURE DONE: %u cap, %u lan nhiet do. Dang luu flash...\n", session.pairCount, session.temperatureCount);
  return true;
}

void initReminders() {
  reminderTopic = String("iot/") + DEVICE_ID + "/control";
  reminderAckTopic = String("iot/") + DEVICE_ID + "/control_ack";
  if (!reminderPrefs.begin("slab-reminder", false)) {
    Serial.println("REMINDER: NVS unavailable; reminders disabled, measurement unchanged."); return;
  }
  uint8_t snapshot[Reminder::SNAPSHOT_BYTES];
  if (!reminderPrefs.isKey("cache")) {
    Reminder::encode(reminderCache,snapshot);
    reminderStorageReady = reminderPrefs.putBytes("cache",snapshot,sizeof(snapshot)) == sizeof(snapshot);
  } else if (reminderPrefs.getBytesLength("cache") == sizeof(snapshot) &&
             reminderPrefs.getBytes("cache",snapshot,sizeof(snapshot)) == sizeof(snapshot)) {
    reminderStorageReady = Reminder::decode(snapshot,sizeof(snapshot),reminderCache);
  }
  Serial.println(reminderStorageReady ? "REMINDER: ready (sound only, no automatic measurement)." :
                 "REMINDER: NVS invalid; preserved, no reminder ACK/sound. Do not erase NVS.");
}

void receiveReminder(byte* bytes,unsigned int length) {
  if (!reminderStorageReady || length>512) return;
  JsonDocument d;
  if (deserializeJson(d,bytes,length) || !d.is<JsonObject>()) return;
  if (strcmp(d["device_id"] | "",DEVICE_ID) || !d["expires_at"].is<uint64_t>()) return;
  const char* id=d["event_id"] | "", *kind=d["event"] | "";
  bool missed=!strcmp(kind,"measurement_missed");
  if (!Reminder::Cache::validId(id) || (!missed && strcmp(kind,"measurement_due"))) return;
  int64_t now=time(nullptr);
  uint64_t expires=d["expires_at"].as<uint64_t>();
  if (now<1700000000LL || expires<=uint64_t(now) || expires>4102444800ULL) return;
  if (!reminderCache.contains(id)) {
    Reminder::Cache candidate=reminderCache;
    if (!candidate.add(id,expires,uint64_t(now))) {
      Serial.println("REMINDER: unexpired ID cache full; wait for retry."); return;
    }
    uint8_t snapshot[Reminder::SNAPSHOT_BYTES];
    Reminder::encode(candidate,snapshot);
    if (reminderPrefs.putBytes("cache",snapshot,sizeof(snapshot)) != sizeof(snapshot)) {
      // A failed/uncertain write must not produce an application ACK or sound.
      reminderStorageReady=false;
      Serial.println("REMINDER: persistence failed; disabled until restart."); return;
    }
    reminderCache=candidate;
    reminderSound.store(Reminder::soundWord(millis(),missed));
    Serial.println(missed ? "REMINDER: missed measurement (sound only)." : "REMINDER: measurement due (sound only).");
  }
  JsonDocument ack;
  ack["device_id"]=DEVICE_ID; ack["event_id"]=id; ack["received"]=true;
  char payload[192]; serializeJson(ack,payload,sizeof(payload));
  mqtt.publish(reminderAckTopic.c_str(),payload,false);
}

void ackCallback(char* topic, byte* bytes, unsigned int length) {
  if (reminderTopic == topic) { receiveReminder(bytes,length); return; }
  String own=String("iot/")+DEVICE_ID;
  if (length<=768 && (String(topic)==own+"/event_ack" || String(topic)==own+"/command")) {
    JsonDocument d;
    if (deserializeJson(d,bytes,length) || strcmp(d["device_id"] | "",DEVICE_ID)) return;
    if (String(topic)==own+"/event_ack") {
      if (d["saved"].is<bool>() && d["saved"].as<bool>() && d["revision"].is<uint32_t>())
        alertAck(d["event_id"] | "",d["revision"].as<uint32_t>());
    } else {
      if (strcmp(d["action"] | "","clear_alarm") || !d["expires_at"].is<int64_t>() ||
          time(nullptr)<1700000000 || d["expires_at"].as<int64_t>()<time(nullptr)) return;
      const char* event=d["event_id"] | "", *id=d["command_id"] | "";
      if (!identifierValid(event,40) || !identifierValid(id,40)) return;
      AlertCommand cmd{}; snprintf(cmd.eventId,40,"%s",event); snprintf(cmd.commandId,40,"%s",id);
      if (xQueueSend(alertCommands,&cmd,0)!=pdTRUE) Serial.println("COMMAND queue full; web must retry.");
    }
    return;
  }
  if (ackTopic != topic || !packetWasSent || length > 512) return;
  JsonDocument ack;
  if (deserializeJson(ack, bytes, length)) return;
  const char* id = ack["session_id"] | "";
  if (!ack["saved"].is<bool>() || !ack["saved"].as<bool>() ||
      !ack["batch_index"].is<unsigned int>() || !ack["sample_count"].is<unsigned int>() ||
      strcmp(id, session.sessionId) != 0 ||
      ack["batch_index"].as<unsigned int>() != expectedAckBatch ||
      ack["sample_count"].as<unsigned int>() != PAIRS_PER_BATCH) return;
  if (ack["device_id"].is<const char*>() && strcmp(ack["device_id"].as<const char*>(), session.deviceId) != 0) return;
  ackReceived = true;
}

bool networkReady(uint32_t budgetStart, uint32_t budgetMs) {
  static uint32_t lastWifiTry = 0, lastMqttTry = 0, lastStatus = 0;
  static uint32_t lastNtpTry = 0;
  static bool wifiTried = false, mqttTried = false, ntpRequested = false;
  static bool wifiWasConnected = false;
  if (millis() - budgetStart >= budgetMs) return false;
  if (WiFi.status() != WL_CONNECTED) {
    wifiWasConnected = false;
    ntpRequested = false;
    // Give an association attempt time to finish before explicitly restarting it.
    if (!wifiTried || millis() - lastWifiTry >= 30000UL) {
      if (wifiTried) WiFi.disconnect(false, false);
      wifiTried = true; lastWifiTry = millis();
      WiFi.mode(WIFI_STA); WiFi.setAutoReconnect(true);
      WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
      Serial.println("WIFI: bat dau ket noi (mang 2.4 GHz, khong captive portal).");
    }
    if (millis() - lastStatus >= 5000UL) {
      lastStatus = millis();
      Serial.printf("WIFI WAIT: status=%d; kiem tra SSID/password/song Wi-Fi.\n", int(WiFi.status()));
    }
    return false;
  }
  if (!wifiWasConnected) {
    wifiWasConnected = true;
    Serial.print("WIFI OK: IP="); Serial.print(WiFi.localIP());
    Serial.printf(" RSSI=%d\n", WiFi.RSSI());
  }
  // Certificate verification needs a valid clock. Never bypass TLS verification.
  if (time(nullptr) < 1700000000) {
    if (!ntpRequested || millis() - lastNtpTry >= 30000UL) {
      ntpRequested = true; lastNtpTry = millis();
      configTime(0, 0, "pool.ntp.org", "time.google.com", "time.cloudflare.com");
      Serial.println("TLS: dang dong bo gio NTP...");
    }
    if (millis() - lastStatus >= 5000UL) {
      lastStatus = millis();
      Serial.println("NTP WAIT: chua co gio; kiem tra Internet/UDP 123, thu hotspot dien thoai.");
    }
    return false;
  }
  if (!mqtt.connected()) {
    if (!mqttTried || millis() - lastMqttTry >= MQTT_RECONNECT_MS) {
      mqttTried = true; lastMqttTry = millis();
      char clientId[40];
      snprintf(clientId, sizeof(clientId), "slab-%08lx%08lx", (unsigned long)(ESP.getEfuseMac() >> 32), (unsigned long)ESP.getEfuseMac());
      uint32_t connectStarted=millis();
      Serial.printf("MQTT CONNECT: cho CONNACK toi da %us (SOS/MPU van chay).\n",MQTT_RESPONSE_TIMEOUT_S);
      bool connected = strlen(MQTT_USER) ? mqtt.connect(clientId, MQTT_USER, MQTT_PASSWORD) : mqtt.connect(clientId);
      if (connected) {
        bool ok=true;
        if (ackTopic.length()) ok=mqtt.subscribe(ackTopic.c_str(),1);
        String own=String("iot/")+DEVICE_ID;
        ok=mqtt.subscribe((own+"/event_ack").c_str(),1) && ok;
        ok=mqtt.subscribe((own+"/command").c_str(),1) && ok;
        ok=mqtt.subscribe(reminderTopic.c_str(),1) && ok;
        if (!ok) mqtt.disconnect();
        Serial.printf("MQTT connected=%d\n", mqtt.connected());
      } else {
        Serial.printf("MQTT state=%d server=%s:%u WiFi=%d RSSI=%d\n",
                      mqtt.state(), MQTT_SERVER, MQTT_PORT, int(WiFi.status()), int(WiFi.RSSI()));
        Serial.print("ESP_IP="); Serial.print(WiFi.localIP());
        Serial.print(" MASK="); Serial.print(WiFi.subnetMask());
        Serial.print(" GATEWAY="); Serial.println(WiFi.gatewayIP());
        char tlsError[192]{};
        int tlsCode=transport.lastError(tlsError,sizeof(tlsError));
        if (tlsCode<0) Serial.printf("TLS ERROR: code=%d detail=%s\n",tlsCode,tlsError);
        else Serial.printf("TLS STATUS: result=%d (khong phai ma loi TLS).\n",tlsCode);
        if (mqtt.state()==-4)
          Serial.printf("MQTT CONNACK TIMEOUT: responseTimeout=%us totalAttemptMs=%lu; broker chua tra loi CONNECT.\n",
                        MQTT_RESPONSE_TIMEOUT_S,(unsigned long)(millis()-connectStarted));
        static uint32_t lastProbe=0;
        if (mqtt.state()==-2 && (!lastProbe || millis()-lastProbe>=30000UL)) {
          lastProbe=millis();
          IPAddress brokerIP;
          if (!WiFi.hostByName(MQTT_SERVER,brokerIP)) {
            Serial.println("NET DIAG: DNS FAIL; chua phan giai duoc hostname broker.");
          } else {
            Serial.print("NET DIAG: DNS OK IP="); Serial.println(brokerIP);
            WiFiClient probe;
            errno=0;
            bool tcpOK=probe.connect(brokerIP,MQTT_PORT,5000);
            int socketError=errno;
            Serial.printf("NET DIAG: TCP8883=%s errno=%d epoch=%lld heap=%lu\n",
                          tcpOK?"OK":"FAIL",socketError,(long long)time(nullptr),(unsigned long)ESP.getFreeHeap());
            probe.stop();
            Serial.println(tcpOK?"TCP OK: can kiem tra TLS/CA/gio/loi handshake tren ESP32.":
                                  "TCP FAIL: duong mang ESP32 chua mo duoc socket den broker; thu mang khac.");
          }
        }
      }
      lastMqttTry=millis(); // Backoff starts after the attempt, not before a blocking handshake.
    }
    return mqtt.connected();
  }
  mqtt.loop();
  return mqtt.connected();
}

bool makePayload(uint16_t batch, char* output, size_t capacity) {
  uint16_t first = batch * PAIRS_PER_BATCH;
  const Temperature* temperature = &session.temperatures[0];
  for (uint16_t i = 1; i < session.temperatureCount; ++i)
    if (session.temperatures[i].sampleIndex < first + PAIRS_PER_BATCH) temperature = &session.temperatures[i];
  JsonDocument doc;
  doc["schema_version"] = 2;
  doc["device_id"] = session.deviceId; doc["session_id"] = session.sessionId;
  doc["batch_index"] = batch + 1; doc["batch_total"] = SESSION_BATCHES;
  doc["sample_start_index"] = first; doc["sample_count"] = PAIRS_PER_BATCH;
  doc["sample_rate_hz"] = session.sampleRate;
  doc["object_temp"] = temperature->objectC; doc["ambient_temp"] = temperature->ambientC;
  doc["temperature_at_ms"] = temperature->readMs;
  doc["start_read_us"] = session.batchStartUs[batch]; doc["end_read_us"] = session.batchEndUs[batch];
  doc["clock"] = "device_uptime"; doc["clock_synced"] = false;
  doc["gap_detected"] = false;
  JsonArray red = doc["red"].to<JsonArray>(), ir = doc["ir"].to<JsonArray>();
  for (uint16_t i = first; i < first + PAIRS_PER_BATCH; ++i) {
    red.add(session.pairs[i].red); ir.add(session.pairs[i].ir);
  }
  if (doc.overflowed() || measureJson(doc) + 1 > capacity) return false;
  serializeJson(doc, output, capacity);
  return true;
}

bool uploadSession(uint32_t budgetStart, uint32_t budgetMs) {
  xSemaphoreTake(mqttMutex,portMAX_DELAY);
  rawTopic = String("iot/") + session.deviceId + "/raw";
  ackTopic = String("iot/") + session.deviceId + "/ack";
  // A new file may have another device_id. Reconnect to guarantee the right subscription.
  mqtt.disconnect(); xSemaphoreGive(mqttMutex);
  for (uint16_t batch = 0; batch < SESSION_BATCHES; ++batch) {
    char payload[MQTT_BYTES];
    if (!makePayload(batch, payload, sizeof(payload))) { flashProblem = true; return false; }
    xSemaphoreTake(mqttMutex,portMAX_DELAY);
    expectedAckBatch = batch + 1; ackReceived = packetWasSent = false;
    xSemaphoreGive(mqttMutex);
    uint32_t lastSend = 0, batchWaitStart = millis(); bool attempted = false;
    while (!ackReceived && millis() - budgetStart < budgetMs &&
           (!packetWasSent || millis() - batchWaitStart < ACK_WAIT_MS)) {
      serialWearable();
      reportMeasurementWait();
      xSemaphoreTake(mqttMutex,portMAX_DELAY);
      if (networkReady(budgetStart, budgetMs) &&
          (!attempted || millis() - lastSend >= ACK_RETRY_MS)) {
        attempted = true; lastSend = millis();
        if (mqtt.publish(rawTopic.c_str(), payload)) {
          if (!packetWasSent) {
            batchWaitStart = millis();
            Serial.printf("SENT batch=%u; cho collector luu MongoDB va tra ACK.\n", expectedAckBatch.load());
          }
          packetWasSent = true;
        }
      }
      publishAlert();
      xSemaphoreGive(mqttMutex);
      delay(5);
    }
    if (!ackReceived) {
      xSemaphoreTake(mqttMutex,portMAX_DELAY);
      Serial.printf("UPLOAD STOP: WiFi=%d timeReady=%d MQTT=%d sent=%d; %s\n",
                    int(WiFi.status()), time(nullptr) >= 1700000000, mqtt.connected(), packetWasSent.load(),
                    packetWasSent ? "Kiem tra collector/MongoDB/ACK topic." : "Chua gui: kiem tra Wi-Fi/NTP/MQTT.");
      Serial.printf("UPLOAD PAUSED: batch=%u, elapsed=%lu ms; giu file flash.\n",
                    expectedAckBatch.load(), (unsigned long)(millis() - budgetStart));
      xSemaphoreGive(mqttMutex);
      return false;
    }
    Serial.printf("ACK %s %u/30 (%u cap)\n", session.sessionId, expectedAckBatch.load(), PAIRS_PER_BATCH);
  }
  xSemaphoreTake(mqttMutex,portMAX_DELAY); expectedAckBatch = 0; packetWasSent = false; xSemaphoreGive(mqttMutex);
  return true;
}

bool flushPending(uint32_t budgetMs) {
  String paths[MAX_SAVED_SESSIONS];
  uint8_t count = listPending(paths, MAX_SAVED_SESSIONS);
  if (!count) return true;
  uint32_t started = millis();
  Serial.printf("UPLOAD: %u phien dang cho\n", count);
  for (uint8_t i = 0; i < count; ++i) {
    if (!loadSession(paths[i])) {
      flashProblem = true; Serial.println("ERROR: file flash loi CRC/schema, giu file de kiem tra."); continue;
    }
    if (!uploadSession(started, budgetMs)) return false;
    // All 30 application ACKs matched this file. A power loss before remove only causes safe retries.
    if (!LittleFS.remove(paths[i])) { flashProblem = true; return false; }
    Serial.println("Da xac nhan du 1500 cap; xoa file da gui.");
  }
  String remaining[MAX_SAVED_SESSIONS];
  return listPending(remaining, MAX_SAVED_SESSIONS) == 0 && !flashProblem;
}

void networkTask(void*) {
  for (;;) {
    if (xSemaphoreTake(mqttMutex,pdMS_TO_TICKS(20))==pdTRUE) {
      networkReady(millis(),1000);
      publishAlert();
      xSemaphoreGive(mqttMutex);
    }
    xSemaphoreTake(alertMutex,portMAX_DELAY);
    eventSending=alertJournal.count>0;
    xSemaphoreGive(alertMutex);
    vTaskDelay(pdMS_TO_TICKS(20));
  }
}

bool measurementRequested=true, measurementSensorsOK=false;
uint32_t lastReplayAttempt=0;

void setup() {
  gpio_deep_sleep_hold_dis(); gpio_hold_dis(static_cast<gpio_num_t>(BUZZER_PIN));
  buzzerWrite(false); pinMode(BUZZER_PIN,OUTPUT);
  Serial.setTxBufferSize(2048); Serial.begin(9600); delay(200);
  Serial.println("BOOT: WEARABLE_CONTINUOUS_V1");
  Serial.println("TRANSPORT: MQTT_CLOUD_TLS_V1");
  Wire.begin(SDA_PIN,SCL_PIN); Wire.setClock(100000); Wire.setTimeOut(10);
  startWearable();
  mqttMutex=xSemaphoreCreateMutex();
  if (!mqttMutex) fatal("MQTT mutex");
  if (strcmp(CLOUD_HOST,"YOUR_MQTT_HOST")==0 || !strlen(CLOUD_USER) || !strlen(CLOUD_PASSWORD) ||
      !strstr(CLOUD_CA,"-----BEGIN CERTIFICATE-----") || !identifierValid(DEVICE_ID,32))
    fatal("Cau hinh MqttCloud.h/DEVICE_ID; SOS va MPU van chay.");
  transport.setConnectionTimeout(5000); transport.setHandshakeTimeout(8); transport.setCACert(CLOUD_CA);
  initReminders();
  mqtt.setServer(MQTT_SERVER,MQTT_PORT); mqtt.setCallback(ackCallback);
  mqtt.setSocketTimeout(MQTT_RESPONSE_TIMEOUT_S); mqtt.setKeepAlive(30);
  if (!mqtt.setBufferSize(MQTT_BYTES+128)) fatal("MQTT buffer");
  if (xTaskCreatePinnedToCore(networkTask,"network",12288,nullptr,1,&networkHandle,0)!=pdPASS) fatal("network task");
  mountStorage(); recoverTemporaryFiles();
  xSemaphoreTake(sensorMutex,portMAX_DELAY);
  bool tempOK=mlx.begin(0x5A,&Wire);
  maxReady=maxSensor.begin(Wire,I2C_SPEED_STANDARD);
  if (maxReady) {
    maxSensor.setup(60,4,2,400,411,4096);
    maxSensor.shutDown(); maxSensor.disableFIFORollover(); maxSensor.clearFIFO();
    uint8_t fifo=0,spo2=0,mode=0;
    measurementSensorsOK=tempOK && readRegister(0x08,fifo) && readRegister(0x0A,spo2) &&
      readRegister(0x09,mode) && (fifo&0xE0)==0x40 && (spo2&0x1F)==0x0F && (mode&0x07)==0x03;
  }
  xSemaphoreGive(sensorMutex);
  Serial.printf("MEASUREMENT INIT: MAX=%d MLX=%d config100Hz=%d\n",maxReady,tempOK,measurementSensorsOK);
  if (!measurementSensorsOK) Serial.println("MEASUREMENT ERROR: kiem tra MAX30102/GY906; SOS/MPU van chay.");
  Serial.println("READY: RESET yeu cau 1 luot do; sau do giam sat lien tuc, khong deep sleep.");
}

void reportMeasurementWait() {
  static uint32_t last=0;
  if (millis()-last<5000) return;
  last=millis();
  if (!measurementRequested) {
    Serial.println("MEASUREMENT DONE: da thu 1 luot; tiep tuc giam sat. RESET de yeu cau luot moi."); return;
  }
  uint8_t phase=0,count=0;
  xSemaphoreTake(alertMutex,portMAX_DELAY);
  phase=alertJournal.phase; count=alertJournal.count;
  xSemaphoreGive(alertMutex);
  if (flashProblem || wearableFault.load()) Serial.printf("MEASUREMENT BLOCKED: rawFlashError=%d alertStorageError=%d; can sua luu tru, RESET khong xoa loi.\n",flashProblem,wearableFault.load());
  else if (!measurementSensorsOK) Serial.println("MEASUREMENT BLOCKED: MAX30102/MLX90614 init/config loi; xem MEASUREMENT INIT.");
  else if (!mpuHealthy.load()) Serial.println("MEASUREMENT BLOCKED: MPU chua san sang; xem MPU ERROR.");
  else if (phase) Serial.printf("MEASUREMENT WAIT: alarm=%u; giu SOS 2 giay de huy/tat bao dong.\n",phase);
  else if (count) Serial.printf("MEASUREMENT WAIT: con %u su kien cho ACK; bat collector va kiem tra MQTT.\n",count);
  else Serial.println("MEASUREMENT REQUESTED: gui het raw backlog truoc, sau do thu MAX30102 + nhiet do.");
}

void loop() {
  serialWearable();
  reportMeasurementWait();
  if (flashProblem || wearableFault.load()) { sound.store(SoundMode::QUIET); delay(10); return; }
  String pending[MAX_SAVED_SESSIONS];
  uint8_t count=listPending(pending,MAX_SAVED_SESSIONS);
  if (count) {
    if (!lastReplayAttempt || millis()-lastReplayAttempt>=30000UL) {
      sound.store(SoundMode::WAITING);
      Serial.println("REPLAY FIRST: gui phien cu; SOS/MPU van hoat dong.");
      bool sent=flushPending(REPLAY_BUDGET_MS);
      xSemaphoreTake(mqttMutex,portMAX_DELAY); expectedAckBatch=0; packetWasSent=false; xSemaphoreGive(mqttMutex);
      sound.store(SoundMode::QUIET); lastReplayAttempt=millis();
      Serial.println(sent?"REPLAY DONE":"REPLAY PENDING: giu flash, tu thu lai; khong do moi.");
    }
    delay(10); return;
  }
  if (measurementRequested && !pendingAlerts() && measurementSensorsOK && mpuHealthy.load()) {
    if (LittleFS.totalBytes()-LittleFS.usedBytes()<sizeof(session)+16384UL) fatal("Flash gan day; khong ghi de.");
    if (acquireSession()) {
      if (!commitSession()) { flashProblem=true; Serial.println("ERROR: khong luu duoc phien; giu file de kiem tra."); }
      else { measurementRequested=false; lastReplayAttempt=0; Serial.println("FLASH SAVED. Gui truoc khi do luot moi."); }
    }
  }
  delay(10);
}
