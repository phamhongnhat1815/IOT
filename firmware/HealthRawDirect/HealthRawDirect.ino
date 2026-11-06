
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
#include <Preferences.h>

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
// A full cloud backlog needs more than 20s; do not starve at batch 25 on every boot.
constexpr uint32_t REPLAY_BUDGET_MS = 300000;
constexpr uint32_t UPLOAD_BUDGET_MS = 300000;
constexpr uint32_t ACK_WAIT_MS = 30000; // Stop early when one batch makes no progress.
constexpr uint32_t MAX_DRAIN_GAP_US = 100000;
constexpr size_t MQTT_BYTES = 2304;

MAX30105 maxSensor;
Adafruit_MLX90614 mlx;
WiFiClientSecure transport;
PubSubClient mqtt(transport);
RawSession session{};
bool maxReady = false, filesystemReady = false, capturing = false;
bool flashProblem = false;
float objectTemp = NAN, ambientTemp = NAN;
uint32_t lastTemperatureMs = 0, lastDrainUs = 0, lastSampleMs = 0;
uint32_t contactSince = 0, lastLog = 0, attempts = 0, latestIR = 0;
uint32_t lostEvents = 0;
String rawTopic, ackTopic;
uint16_t expectedAckBatch = 0;
bool ackReceived = false, packetWasSent = false;
String controlTopic, controlAckTopic;
String controlEvents[16];
uint8_t nextControlSlot = 0;
Preferences reminderPrefs;
bool reminderPrefsReady = false;
bool waitForFingerRemoval = false;
uint32_t idleContactSince = 0, lastIdleSample = 0, lastReplayTry = 0;
TaskHandle_t buzzerHandle = nullptr;
std::atomic<SoundMode> sound{SoundMode::QUIET};
std::atomic<bool> soundFinished{true};

void buzzerWrite(bool on) {
  digitalWrite(BUZZER_PIN, on ? BUZZER_ON_LEVEL : !BUZZER_ON_LEVEL);
}

void buzzerTask(void*) {
  SoundMode previous = SoundMode::QUIET;
  uint32_t started = millis();
  for (;;) {
    SoundMode mode = sound.load();
    if (mode != previous) { previous = mode; started = millis(); }
    uint32_t elapsed = millis() - started;
    bool on = false, finished = false;
    switch (mode) {
      case SoundMode::QUIET: break;
      case SoundMode::DUE:
        on = elapsed % 2000UL < 200UL;
        finished = elapsed >= 10000UL; break;
      case SoundMode::MISSED:
        on = elapsed % 2000UL < 150UL ||
             (elapsed % 2000UL >= 300UL && elapsed % 2000UL < 450UL);
        finished = elapsed >= 10000UL; break;
      case SoundMode::WAITING: on = elapsed % 1000UL < 150UL; break;
      case SoundMode::MEASURING: {
        // Two 100ms beeps, 100ms apart, then 1000ms silence. Non-blocking.
        uint32_t phase = elapsed % 1300UL;
        on = phase < 100UL || (phase >= 200UL && phase < 300UL);
        break;
      }
      case SoundMode::SUCCESS: on = elapsed < 2000UL; finished = elapsed >= 2000UL; break;
      case SoundMode::OFFLINE:
        on = elapsed < 120UL || (elapsed >= 270UL && elapsed < 390UL);
        finished = elapsed >= 650UL; break;
      case SoundMode::ERROR:
        on = elapsed < 150UL || (elapsed >= 300UL && elapsed < 450UL) ||
             (elapsed >= 600UL && elapsed < 750UL);
        finished = elapsed >= 1000UL; break;
    }
    buzzerWrite(on);
    if (finished) { sound.store(SoundMode::QUIET); soundFinished.store(true); }
    vTaskDelay(pdMS_TO_TICKS(10));
  }
}

void sleepWithSignal(SoundMode mode) {
  if (maxReady) maxSensor.shutDown();
  mqtt.disconnect();
  WiFi.disconnect(true);
  WiFi.mode(WIFI_OFF);
  soundFinished.store(false);
  sound.store(mode);
  while (!soundFinished.load()) delay(10);
  if (buzzerHandle) { vTaskDelete(buzzerHandle); buzzerHandle = nullptr; }
  buzzerWrite(false);
  if (filesystemReady) LittleFS.end();
  Serial.println("SLEEP. Bam RESET hoac tat/bat nguon de chay lai.");
  Serial.flush();
  gpio_hold_en(static_cast<gpio_num_t>(BUZZER_PIN));
  gpio_deep_sleep_hold_en();
  esp_sleep_disable_wakeup_source(ESP_SLEEP_WAKEUP_ALL);
  esp_deep_sleep_start();
}

void fatal(const char* reason) {
  Serial.print("ERROR: "); Serial.println(reason);
  sleepWithSignal(SoundMode::ERROR);
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

void acquireSession() {
  WiFi.mode(WIFI_OFF); // No networking or flash writes during ADC acquisition.
  sound.store(SoundMode::MEASURING);
  capturing = false; contactSince = 0;
  session.pairCount = session.temperatureCount = 0;
  readSurfaceTemperature();
  maxSensor.clearFIFO(); maxSensor.wakeUp();
  lastDrainUs = micros(); lastSampleMs = millis();
  Serial.println("Dat ngon tay va giu yen ~16 giay. Khong can B=1.");
  while (session.pairCount < SESSION_PAIRS) {
    drainFifo();
    if (session.pairCount >= SESSION_PAIRS) break;
    if (millis() - lastTemperatureMs >= 1000UL) {
      bool valid = readSurfaceTemperature();
      if (!valid) resetCapture("nhiet do khong hop le");
      else if (capturing && session.temperatureCount < MAX_TEMPERATURES &&
               session.pairCount > session.temperatures[session.temperatureCount - 1].sampleIndex)
        session.temperatures[session.temperatureCount++] = {session.pairCount, lastTemperatureMs, objectTemp, ambientTemp};
      drainFifo();
    }
    if (millis() - lastSampleMs > 3000UL) fatal("MAX30102 khong tra mau; kiem tra day/nguon");
    if (millis() - lastLog >= 1000UL) {
      lastLog = millis();
      Serial.printf("IR=%lu F=%d T=%d samples=%u/1500 lost_events=%lu\n",
                    (unsigned long)latestIR, latestIR > FINGER_THRESHOLD,
                    isfinite(objectTemp) && isfinite(ambientTemp), session.pairCount, (unsigned long)lostEvents);
    }
    delay(1);
  }
  maxSensor.shutDown(); capturing = false;
  sound.store(SoundMode::QUIET);
  Serial.printf("CAPTURE DONE: %u cap, %u lan nhiet do. Dang luu flash...\n", session.pairCount, session.temperatureCount);
}

void ackCallback(char* topic, byte* bytes, unsigned int length) {
  if (controlTopic == topic) {
    if (length > 512) return;
    JsonDocument command;
    if (deserializeJson(command, bytes, length)) return;
    const char* target = command["device_id"] | "";
    const char* eventId = command["event_id"] | "";
    const char* event = command["event"] | "";
    uint32_t expires = command["expires_at"] | 0UL;
    if (strcmp(target, DEVICE_ID) != 0 || strlen(eventId) != 64 ||
        time(nullptr) < 1700000000 || expires <= uint32_t(time(nullptr)) ||
        (strcmp(event, "measurement_due") != 0 && strcmp(event, "measurement_missed") != 0)) return;
    bool duplicate = false;
    for (const String& saved : controlEvents) if (saved == eventId) duplicate = true;
    if (!duplicate) {
      controlEvents[nextControlSlot] = eventId;
      if (reminderPrefsReady) {
        char key[12]; snprintf(key, sizeof(key), "event%u", nextControlSlot);
        reminderPrefs.putString(key, controlEvents[nextControlSlot]);
      }
      nextControlSlot = (nextControlSlot + 1) % 16;
      if (reminderPrefsReady) reminderPrefs.putUChar("next", nextControlSlot);
      soundFinished.store(false);
      sound.store(strcmp(event, "measurement_due") == 0 ? SoundMode::DUE : SoundMode::MISSED);
    }
    JsonDocument ack;
    ack["event_id"] = eventId; ack["device_id"] = DEVICE_ID; ack["received"] = true;
    char payload[192]; serializeJson(ack, payload, sizeof(payload));
    mqtt.publish(controlAckTopic.c_str(), payload, false);
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
  static uint32_t lastWifiTry = 0, lastMqttTry = 0;
  static bool wifiTried = false, mqttTried = false;
  static bool ntpRequested = false;
  if (millis() - budgetStart >= budgetMs) return false;
  if (WiFi.status() != WL_CONNECTED) {
    if (!wifiTried || millis() - lastWifiTry >= 7000UL) {
      wifiTried = true; lastWifiTry = millis();
      WiFi.mode(WIFI_STA); WiFi.setAutoReconnect(true);
      WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    }
    return false;
  }
  // Certificate verification needs a valid clock. Never bypass TLS verification.
  if (time(nullptr) < 1700000000) {
    if (!ntpRequested) {
      ntpRequested = true;
      configTime(0, 0, "pool.ntp.org", "time.google.com");
      Serial.println("TLS: dang dong bo gio NTP...");
    }
    return false;
  }
  if (!mqtt.connected()) {
    if (!mqttTried || millis() - lastMqttTry >= 3000UL) {
      mqttTried = true; lastMqttTry = millis();
      char clientId[40];
      snprintf(clientId, sizeof(clientId), "slab-%08lx%08lx", (unsigned long)(ESP.getEfuseMac() >> 32), (unsigned long)ESP.getEfuseMac());
      bool connected = strlen(MQTT_USER) ? mqtt.connect(clientId, MQTT_USER, MQTT_PASSWORD) : mqtt.connect(clientId);
      if (connected) {
        if (!mqtt.subscribe(ackTopic.c_str(), 1) || !mqtt.subscribe(controlTopic.c_str(), 1)) mqtt.disconnect();
        Serial.printf("MQTT connected=%d\n", mqtt.connected());
      } else {
        Serial.printf("MQTT state=%d server=%s:%u WiFi=%d RSSI=%d\n",
                      mqtt.state(), MQTT_SERVER, MQTT_PORT, int(WiFi.status()), int(WiFi.RSSI()));
        Serial.print("ESP_IP="); Serial.print(WiFi.localIP());
        Serial.print(" MASK="); Serial.print(WiFi.subnetMask());
        Serial.print(" GATEWAY="); Serial.println(WiFi.gatewayIP());
      }
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
  rawTopic = String("iot/") + session.deviceId + "/raw";
  ackTopic = String("iot/") + session.deviceId + "/ack";
  // A new file may have another device_id. Reconnect to guarantee the right subscription.
  mqtt.disconnect();
  for (uint16_t batch = 0; batch < SESSION_BATCHES; ++batch) {
    char payload[MQTT_BYTES];
    if (!makePayload(batch, payload, sizeof(payload))) { flashProblem = true; return false; }
    expectedAckBatch = batch + 1; ackReceived = packetWasSent = false;
    uint32_t lastSend = 0, batchWaitStart = millis(); bool attempted = false;
    while (!ackReceived && millis() - budgetStart < budgetMs &&
           millis() - batchWaitStart < ACK_WAIT_MS) {
      if (networkReady(budgetStart, budgetMs) &&
          (!attempted || millis() - lastSend >= ACK_RETRY_MS)) {
        attempted = true; lastSend = millis();
        if (mqtt.publish(rawTopic.c_str(), payload)) packetWasSent = true;
      }
      delay(5);
    }
    if (!ackReceived) {
      Serial.printf("UPLOAD PAUSED: batch=%u, elapsed=%lu ms; giu file flash.\n",
                    expectedAckBatch, (unsigned long)(millis() - budgetStart));
      return false;
    }
    Serial.printf("ACK %s %u/30 (%u cap)\n", session.sessionId, expectedAckBatch, PAIRS_PER_BATCH);
  }
  expectedAckBatch = 0; packetWasSent = false;
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

void setup() {
  gpio_deep_sleep_hold_dis(); gpio_hold_dis(static_cast<gpio_num_t>(BUZZER_PIN));
  buzzerWrite(false); pinMode(BUZZER_PIN, OUTPUT);
  Serial.setTxBufferSize(1024); Serial.begin(9600);
  delay(200);
  if (xTaskCreate(buzzerTask, "buzzer", 2048, nullptr, 2, &buzzerHandle) != pdPASS) {
    Serial.println("ERROR: buzzer task"); while (true) delay(1000);
  }
  Serial.println("BOOT: RAW_FLASH_ACK_V1");
  Serial.println("TRANSPORT: MQTT_CLOUD_TLS_V1");
  if (strcmp(CLOUD_HOST, "YOUR_MQTT_HOST") == 0 || !strlen(CLOUD_USER) ||
      !strlen(CLOUD_PASSWORD) || !strstr(CLOUD_CA, "-----BEGIN CERTIFICATE-----"))
    fatal("Chay configure_mqtt_cloud.py tren may tinh, sau do nap lai. Khong FORMAT.");
  if (strcmp(WIFI_SSID, "TEN_WIFI") == 0 || strcmp(MQTT_SERVER, "IP_LAN_MAY_CHAY_MOSQUITTO") == 0 ||
      !identifierValid(DEVICE_ID, sizeof(session.deviceId))) fatal("Dien Wi-Fi, IP MQTT va DEVICE_ID o dau file");
  transport.setConnectionTimeout(5000);
  transport.setHandshakeTimeout(8);
  transport.setCACert(CLOUD_CA);
  mqtt.setServer(MQTT_SERVER, MQTT_PORT); mqtt.setCallback(ackCallback);
  rawTopic = String("iot/") + DEVICE_ID + "/raw";
  ackTopic = String("iot/") + DEVICE_ID + "/ack";
  controlTopic = String("iot/") + DEVICE_ID + "/control";
  controlAckTopic = String("iot/") + DEVICE_ID + "/control_ack";
  reminderPrefsReady = reminderPrefs.begin("signal-reminder", false);
  if (reminderPrefsReady) {
    nextControlSlot = reminderPrefs.getUChar("next", 0) % 16;
    for (uint8_t i = 0; i < 16; ++i) {
      char key[12]; snprintf(key, sizeof(key), "event%u", i);
      controlEvents[i] = reminderPrefs.getString(key, "");
    }
  }
  mqtt.setSocketTimeout(2); mqtt.setKeepAlive(30);
  if (!mqtt.setBufferSize(MQTT_BYTES + 128)) fatal("MQTT buffer");
  mountStorage(); recoverTemporaryFiles();
  // Replay old sessions even if the sensors are currently disconnected.
  String pending[MAX_SAVED_SESSIONS];
  if (flashProblem) fatal("Flash co file loi; giu du lieu, KHONG bat dau do moi.");
  if (listPending(pending, MAX_SAVED_SESSIONS) > 0) {
    Serial.println("REPLAY FIRST: gui het phien cu truoc khi do moi.");
    sound.store(SoundMode::WAITING);
    bool replayed = flushPending(REPLAY_BUDGET_MS);
    if (!replayed || flashProblem) {
      Serial.println("REPLAY PENDING: giu flash; thu lai khi cho online, KHONG do de du lieu.");
      if (flashProblem) fatal("Flash loi; giu file de kiem tra");
    } else {
      Serial.println("REPLAY DONE: da gui het phien cu.");
    }
  } else {
    Serial.println("NO PENDING: bat dau do ngay.");
  }
  sound.store(SoundMode::QUIET);
  mqtt.disconnect(); WiFi.disconnect(true); WiFi.mode(WIFI_OFF);
  if (listPending(pending, MAX_SAVED_SESSIONS) >= MAX_SAVED_SESSIONS ||
      LittleFS.totalBytes() - LittleFS.usedBytes() < sizeof(session) + 16384UL)
    fatal("Flash gan day. Bat lai khi broker/collector online de gui phien cu; khong ghi de du lieu.");
  if (!Wire.begin(SDA_PIN, SCL_PIN)) fatal("I2C begin");
  Wire.setClock(100000); Wire.setTimeOut(10);
  // Initialize MLX before enabling MAX sampling, avoiding startup FIFO overflow.
  if (!mlx.begin(0x5A, &Wire)) fatal("Khong tim thay GY-906/MLX90614 tai 0x5A");
  if (!maxSensor.begin(Wire, I2C_SPEED_STANDARD)) fatal("Khong tim thay MAX30102 tai 0x57");
  maxReady = true;
  maxSensor.setup(60, 4, 2, 400, 411, 4096);
  maxSensor.shutDown(); maxSensor.disableFIFORollover(); maxSensor.clearFIFO();
  uint8_t fifo = 0, spo2 = 0, mode = 0;
  if (!readRegister(0x08, fifo) || !readRegister(0x0A, spo2) || !readRegister(0x09, mode) ||
      (fifo & 0xE0) != 0x40 || (spo2 & 0x1F) != 0x0F || (mode & 0x07) != 0x03)
    fatal("Cau hinh MAX doc lai khong khop 100Hz RED+IR");
  maxSensor.wakeUp(); maxSensor.clearFIFO();
  Serial.println("ONLINE IDLE: cho nhac MQTT; dat ngon tay de do. Can cap nguon thuong xuyen.");
}

void loop() {
  // Idle stays online. Acquisition still disables Wi-Fi to preserve the raw sampling contract.
  networkReady(millis(), 1000UL);
  if (millis() - lastIdleSample < 100UL) { delay(5); return; }
  lastIdleSample = millis();
  String pending[MAX_SAVED_SESSIONS];
  if (millis() - lastReplayTry >= 30000UL) {
    lastReplayTry = millis();
    if (listPending(pending, MAX_SAVED_SESSIONS)) {
      maxSensor.shutDown();
      bool sent = flushPending(30000UL);
      if (flashProblem) fatal("Flash loi; giu du lieu");
      sound.store(sent ? SoundMode::SUCCESS : SoundMode::OFFLINE);
      rawTopic = String("iot/") + DEVICE_ID + "/raw";
      ackTopic = String("iot/") + DEVICE_ID + "/ack";
      mqtt.disconnect();
      maxSensor.wakeUp(); maxSensor.clearFIFO();
      return;
    }
  }
  // Networking can stall idle polling longer than the FIFO capacity. Drop idle-only
  // samples before polling contact; acquisition has its own strict FIFO handling.
  maxSensor.clearFIFO();
  uint32_t ir = maxSensor.getIR();
  if (ir <= FINGER_THRESHOLD) { waitForFingerRemoval = false; idleContactSince = 0; return; }
  if (waitForFingerRemoval) return;
  if (!idleContactSince) idleContactSince = millis();
  if (millis() - idleContactSince < CONTACT_STABLE_MS) return;
  if (listPending(pending, MAX_SAVED_SESSIONS)) return; // Never overwrite an unsent session.
  if (LittleFS.totalBytes() - LittleFS.usedBytes() < sizeof(session) + 16384UL)
    fatal("Flash gan day; khong ghi de");
  mqtt.disconnect();
  acquireSession();
  if (!commitSession()) fatal("Luu/kiem tra flash that bai; giu du lieu");
  sound.store(SoundMode::WAITING);
  bool uploaded = flushPending(UPLOAD_BUDGET_MS);
  if (flashProblem) fatal("Flash loi; giu du lieu");
  sound.store(uploaded ? SoundMode::SUCCESS : SoundMode::OFFLINE);
  waitForFingerRemoval = true; idleContactSince = 0;
  lastReplayTry = millis();
  rawTopic = String("iot/") + DEVICE_ID + "/raw";
  ackTopic = String("iot/") + DEVICE_ID + "/ack";
  mqtt.disconnect();
  maxSensor.wakeUp(); maxSensor.clearFIFO();
}
