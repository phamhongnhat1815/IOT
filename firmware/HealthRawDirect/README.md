# ESP32 wearable — continuous monitoring (experimental)

[Hướng dẫn nạp, chạy và thử bằng tiếng Việt](HUONG_DAN_THU.md).

ESP32 WROOM / Dev Module + MAX30102 + MLX90614 + MPU6050 GY-521 + three LEDs + momentary SOS button + active buzzer. This firmware replaces the previous capture/upload/deep-sleep workflow. No new Arduino library is required: MPU6050 registers are read over Wire directly.

## Wiring

Disconnect USB before wiring. Logic on SDA/SCL must be 3.3 V. Check module supply requirements and actual board labels.

| Component | ESP32 |
|---|---|
| MAX30102, MLX90614, MPU6050 SDA | GPIO21 (shared) |
| MAX30102, MLX90614, MPU6050 SCL | GPIO22 (shared) |
| All GND | Common GND |
| MPU6050 GY-521 VCC | 3V3 for the module discussed in this project |
| MPU6050 AD0 | GND, address 0x68 |
| MPU6050 INT/XDA/XCL | Unconnected (polling) |
| Red LED anode via individual 330-ohm resistor | GPIO26 |
| Green LED anode via individual 330-ohm resistor | GPIO27 |
| Blue LED anode via individual 330-ohm resistor | GPIO32 |
| All LED cathodes | GND |
| SOS button | Between GPIO33 and GND; internal pull-up, active LOW |
| Buzzer I/O | GPIO25; active LOW as in previous firmware |
| Buzzer VCC; MAX/MLX supply | Keep the supply already verified for each actual module |

Each ordinary indicator LED needs its own series resistor, e.g. GPIO -> 330 ohms -> LED anode, LED cathode -> GND. Never share one resistor among the three LEDs. GPIO pins are for control, not direct power for a high-current buzzer.

## Dependencies and upload

Arduino-ESP32 3.3.12; SparkFun MAX3010x, Adafruit MLX90614 + BusIO, PubSubClient, ArduinoJson 7.x. Keep `FirmwareTypes.h`, `FallDetector.h`, `WearableConfig.h`, `Wearable.h`, `MpuProfile.h`, `AlertJournal.h`, private `WiFiConfig.h` and private `MqttCloud.h` beside `HealthRawDirect.ino`.

MQTT and Wi-Fi configuration stays unchanged. `iot_lab/configure_mqtt_cloud.py` generates MqttCloud.h. Upload speed 115200 if 921600 is unreliable. Keep the existing flash partition and **Erase All Flash = Disabled**. Serial Monitor **9600 baud**. Do NOT erase NVS or FORMAT to fix network errors: raw sessions live in LittleFS and alert state/outbox lives in NVS.

## Behavior

- Every boot/RESET requests ONE measurement. Pending raw sessions and alert events must be ACKed first; active alarms must be dismissed. After the measurement, upload then remain awake monitoring; press RESET for the next measurement.
- Blue LED stays on while waiting for a finger/acquiring. Green LED blinks 150 ms on / 850 ms off during raw upload or pending alert delivery. No measurement/upload buzzer sounds.
- Short press/release SOS: immediate red blinking + pulsed buzzer, persist/send SOS event.
- Suspected fall: red blinking, silent 6-second cancellation window, then red + buzzer and persist/send fall event.
- Hold SOS for 2 seconds during grace/alarm: cancel/dismiss, continue monitoring. This does NOT switch off power. Holding an idle button does not generate SOS on release.
- Web dismissals require the correct alarm ID, an unexpired command, and a device-confirmed cleared event. Acknowledging database storage does not turn off the local alarm.
- Network work runs on a separate task/core; MPU/button/output task continues during DNS/TLS/replay. All Wire access is serialized. A stale/failed MPU read invalidates the movement chain and aborts a measurement; SOS remains available. No claim of uninterrupted sensing across a physical RESET, flash-write stalls, bus faults or hardware power loss.
- Emergency interrupts a partial measurement; that RAM session is discarded and a fresh capture can start only after alarm dismissal and backlog ACKs. MAX FIFO gaps/overflow still invalidate raw sessions; raw binary flash layout remains unchanged.
- Raw session replay retries after a failed bounded 300-second upload pass, without sleeping. Event publish retries every 2 seconds until a matching application ACK; these are retries of one event, not periodic no-fall telemetry.

## Experimental fall detector

100 Hz sampling, +/-8g accelerometer, +/-1000 degrees/s gyro, hardware low-pass filter. `WearableConfig.h` contains the **user-approved experimental starting values**, not values validated for elderly neck-pendant users:

| Feature | Trial value |
|---|---|
| Low acceleration candidate | <0.65g |
| Impact | >2.5g |
| Rotation | >150 degrees/s |
| Orientation change | >=45 degrees |
| Post-impact stillness acceleration | abs(norm(a)-1g) <0.20g |
| Post-impact stillness rotation | <25 degrees/s |
| Candidate-to-impact window | 1000ms |
| Post-impact window | 3000ms |
| Continuous stillness required | 800ms |

Candidate comes from low acceleration, fast rotation OR impact. Impact must occur within the window, then stillness plus either orientation change or peak rotation. Free fall is not mandatory. The six-second user-cancel timer starts AFTER this chain identifies a suspected fall. A gap >100ms resets the chain. After cancellation, a six-second rearm interval prevents the same movement immediately retriggering. This simple first version can miss slow/sliding falls and can mistake a dropped pendant for a fall; it is not a validated protection device.

Do not copy waist-mounted dataset thresholds as if they were validated for a hanging pendant. Sources informing the approach (not the numerical trial values): [SisFall](https://www.mdpi.com/1424-8220/17/1/198), [sensor location study](https://pmc.ncbi.nlm.nih.gov/articles/PMC10205068/), [TDK MPU datasheet](https://invensense.tdk.com/wp-content/uploads/2015/02/MPU-6000-Datasheet.pdf). Lifeline uses accelerometer plus barometer, which this hardware does not have: [manufacturer explanation](https://www.lifeline.com/medical-alert-systems/fall-detection/).

## Persistence and limits

A CRC-checked, explicitly encoded V3 NVS snapshot holds current grace/alarm state and an ordered 32-record outbox. The encoded length depends on actual queued records; no struct padding is written. Valid legacy 16/32-record layouts are migrated into the separate journal_v3 key while keeping the original journal key unchanged. Active alarm is restored after RESET; grace restarts with a full six seconds. Each alarm has an ID and revisions (active=1, cleared=2). Never overwrite unacknowledged records. Full queue retains the current alarm snapshot, reports an error, and waits for backlog to drain; dismissing may need another hold after space is available. Corrupt NVS is preserved and reported, not silently reset. A confirmed event can be acknowledged/removed locally only after durable server storage; the active alarm snapshot remains until dismissal.

Collector stores immutable `alert_events`, revision-protected `alert_states`, and `alert_commands` in MongoDB. Alert records currently have no automatic TTL. Existing raw data TTL behavior stays unchanged. Expired or offline web commands are shown as unconfirmed; a stale clear for one alarm cannot clear a newer alarm.

## Start Python and web

Stop the old collector (Ctrl+C) before starting ONE updated collector. In `iot_lab` on Mac:

```bash
.venv/bin/python check_connection.py --init
.venv/bin/python collector.py
```

In a second terminal in `iot_lab`:

```bash
.venv/bin/python -m streamlit run web.py
```

Open http://127.0.0.1:8501, choose **MongoDB**. The alarm panel appears even when no raw measurement/device exists yet. Web control needs a MongoDB account allowed to write `alert_commands`; read-only users can view but cannot issue commands. Collector must remain running to forward web commands and save/ACK events.

Broker ACL must allow the device to publish `iot/<device>/raw`, `iot/<device>/event`, and subscribe to `iot/<device>/ack`, `iot/<device>/event_ack`, `iot/<device>/command`. Collector needs the complementary permissions. Old ACL limited to raw/ack must be extended.

## Bench tests

1. At boot, check for `WEARABLE`, `READY`, and regular `IMU g=... dps=...`. At rest norm(acceleration) should be about 1g; gyro bias should be checked before tuning. `MPU ERROR` means fall detection is unavailable; the red LED is reserved for alarm/grace, not sensor errors. Boot `I2C SCAN` lists responding addresses and errors include WHO_AM_I/bus status. `LED OUT` reports the commanded pin levels, assuming active-HIGH LEDs to GND.
2. Tap SOS: red + buzzer immediately; web receives SOS. Hold 2s: alarm stops; web eventually shows device-confirmed clearance.
3. For software injection, set `ENABLE_SERIAL_SIMULATION=true` in WearableConfig.h, upload, set Serial line ending Newline, send `SIM_FALL` or `SIM_SOS`. SIM_FALL tests grace/output/network/persistence, NOT movement recognition. Hold 2s during grace to cancel; otherwise alarm starts after 6s. Restore false for normal use.
4. Request dismissal on web: it must stay pending until the actual device clearance event arrives. Test also with Wi-Fi disabled and an expired command.
5. Disconnect Internet, trigger SOS, RESET: local alarm must return. Reconnect: same event ID is retried and stored without duplicate history. Old active retries must never reopen an already cleared alarm on web.
6. During PPG acquisition and network reconnect, test the SOS button and observe LEDs. Deliberate I2C failure must be visible, not treated as no fall.
7. Collect normal activities (walking, bending, sitting, lying down, picking up the pendant to measure). Review data before tuning. Do not ask an elderly user to fall; dropping a padded empty enclosure on a low padded surface is only a movement test, not human-fall validation.

Offline automated checks:

```bash
cd iot_lab
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python tests/test_ui.py
```

Native C++ sequence tests use the same FallDetector.h as the ESP32. Software tests and compilation cannot verify wiring, real fall sensitivity, MQTT ACL, or actual end-to-end delivery.

### Sensor identity and network diagnostics

WHO_AM_I 116 decimal = 0x74 is explicitly supported as MPU6515 (MPU6500 register family). Only IDs 0x68/0x70/0x74 are accepted; acceleration/gyro full scales, power, rate and filters are read back before enabling detection. MPU6500/6515 use an additional acceleration filter register 0x1D. Sources: [Linux model/register mapping](https://github.com/torvalds/linux/blob/master/drivers/iio/imu/inv_mpu6050/inv_mpu_core.c), [WHO_AM_I constants](https://linux.googlesource.com/linux/kernel/git/torvalds/linux/+/441c63ff42c4e666304cdd32d23b5fc6bc1ea3cc/drivers/iio/imu/inv_mpu6050/inv_mpu_iio.h).

On connection failure, `NET DIAG` periodically resolves DNS and tests TCP reachability to the configured broker port (no sensor payload). TCP success alone is not MQTT or TLS success. TLS CA/hostname validation remains enabled. `LED OUT: ... BLUE32=0` means the blue LED should be off for GPIO -> resistor -> LED -> GND wiring. RED=1 in this version means grace/alarm state, not an MPU error; hold SOS for 2s to dismiss, including alarms restored after reset.

### NVS upgrade and manual time

`JOURNAL MIGRATED V3` means a legacy snapshot was validated (CRC + record schema) and copied without truncation; the original key remains. `JOURNAL READ: ... decoded=0` means data could not be safely decoded. Do not FORMAT or erase NVS. A corrupt V3 snapshot never falls back to an older legacy snapshot because this could reopen/replay obsolete state.

If NTP is blocked, obtain fresh Unix seconds from a trusted Mac using `date +%s`. In Serial Monitor (Newline), send `TIME <those seconds>`, e.g. by replacing the placeholder with the actual fresh value. The firmware validates the range and sets the device clock; TLS CA and hostname validation stay enabled. This is manual clock setting, not NTP verification, and does not clear alarm backlog or storage faults. Do not use a hard-coded stale date.

### MQTT response timing

CONNACK/socket response timeout is 15 seconds (formerly 2); reconnect backoff is 10 seconds after the attempt ends. The secure client yields when no bytes are available, retaining the independent SOS/IMU task. Positive NetworkClientSecure::lastError values can be successful socket descriptors in Arduino-ESP32 3.3.12, so only negative values are labeled TLS errors. `EVENT SENT` is not durable confirmation; `EVENT ACK` reports the remaining journal count after persistence of the ACK removal succeeds.
