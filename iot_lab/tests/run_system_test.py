"""Isolated integration tests: real local MQTT sockets + real collector callbacks.

MongoDB uses mongomock (no Atlas writes); time is advanced explicitly. No .env
broker settings or production devices are used. Run this script directly.
"""
import asyncio
import copy
import json
import logging
import math
import sys
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import mongomock
import paho.mqtt.client as mqtt
from amqtt.broker import Broker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import collector
import storage
from frames import frames
from model import validate
from monitoring import Monitor, LOCAL, identity
from physiology import analyze

UTC = timezone.utc
REPORT = []


def until(predicate, message, timeout=8):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(.02)
    raise AssertionError(message)


class LocalBroker:
    def __enter__(self):
        self.ready = threading.Event()
        self.error = None
        def serve():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            async def start():
                self.broker = Broker({"listeners": {"default": {"type": "tcp", "bind": "127.0.0.1:0"}},
                    "plugins": {"amqtt.plugins.authentication.AnonymousAuthPlugin": {"allow_anonymous": True}}})
                await self.broker.start()
                self.port = self.broker._servers["default"].instance.sockets[0].getsockname()[1]
            try:
                self.loop.run_until_complete(start())
            except BaseException as exc:
                self.error = exc
                self.ready.set()
                return
            self.ready.set()
            self.loop.run_forever()
            pending = asyncio.all_tasks(self.loop)
            for task in pending:
                task.cancel()
            if pending:
                self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            self.loop.close()
        self.thread = threading.Thread(target=serve, daemon=True)
        self.thread.start()
        assert self.ready.wait(10), "Test broker did not start"
        if self.error:
            raise self.error
        return self

    def __exit__(self, *args):
        try:
            asyncio.run_coroutine_threadsafe(self.broker.shutdown(), self.loop).result(10)
        finally:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(10)


class FakeDevice:
    def __init__(self, device, port):
        assert device.startswith("TEST-")
        self.device = device
        self.port = port
        self.commands, self.raw_acks, self.errors = [], [], []
        self.seen = set()
        self.beeps = 0
        self.auto_ack = True
        self.ready = threading.Event()
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="fake-"+uuid4().hex)
        self.client.on_connect = lambda c, *_: c.subscribe([(f"iot/{device}/control", 1), (f"iot/{device}/ack", 1)])
        self.client.on_subscribe = lambda *_: self.ready.set()
        def receive(c, _, msg):
            try:
                body = json.loads(msg.payload)
                if msg.topic.endswith("/ack"):
                    self.raw_acks.append(body)
                    return
                assert body["device_id"] == device
                assert body["event"] in ("measurement_due", "measurement_missed")
                assert body["expires_at"] > int(time.time())
                self.commands.append(body)
                if body["event_id"] not in self.seen:
                    self.seen.add(body["event_id"])
                    self.beeps += 1  # Simulation only: no real buzzer.
                if self.auto_ack:
                    self.ack(body["event_id"])
            except BaseException as exc:
                self.errors.append(str(exc))
        self.client.on_message = receive
        self.client.connect("127.0.0.1", port, 30)
        self.client.loop_start()
        assert self.ready.wait(8), "Fake ESP32 did not subscribe"

    def ack(self, event_id, target=None):
        self.client.publish(f"iot/{self.device}/control_ack", json.dumps({
            "event_id": event_id, "device_id": target or self.device, "received": True}), qos=1)

    def publish(self, body):
        result = self.client.publish(f"iot/{self.device}/raw", json.dumps(body), qos=1)
        result.wait_for_publish(timeout=5)
        assert result.is_published()

    def close(self):
        self.client.disconnect()
        self.client.loop_stop()


def raw_packet(device, session, batch, kind="good"):
    ir, red = [], []
    ratio = 1.0 if kind == "low_oxygen" else .5
    for i in range((batch-1)*50, batch*50):
        t = i/100
        wave = math.sin(2*math.pi*80/60*t) + .15*math.sin(4*math.pi*80/60*t)
        ir.append(80000 if kind == "poor" else round(80000+1200*wave))
        red.append(round(70000+1200*ratio*70000/80000*wave))
    return {"device_id": device, "session_id": session, "schema_version": 2,
            "batch_index": batch, "batch_total": 30, "sample_start_index": (batch-1)*50,
            "sample_count": 50, "sample_rate_hz": 100, "ir": ir, "red": red,
            "object_temp": 34.2, "ambient_temp": 28.5, "temperature_at_ms": ((batch-1)//2)*1000,
            "gap_detected": False, "clock_synced": False}


class SystemTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        logging.basicConfig(level=logging.ERROR)
        cls.broker = LocalBroker().__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.broker.__exit__(None, None, None)

    def setUp(self):
        self.store = storage.MongoStore.__new__(storage.MongoStore)
        self.store.client = mongomock.MongoClient(tz_aware=True)
        self.store.db = self.store.client["signal_lab_test_"+uuid4().hex]
        self.monitor = Monitor(self.store)
        self.monitor.setup()
        self.device_id = "TEST-" + uuid4().hex[:12]
        self.now = datetime.now(UTC).replace(microsecond=0)
        self.clock = self.now
        self.validate_patch = patch.object(collector, "validate", side_effect=lambda payload, topic: validate(payload, topic, now=self.clock))
        self.validate_patch.start()
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="collector-test-"+uuid4().hex,
                                  clean_session=False, manual_ack=True)
        collector.configure_callbacks(self.client, self.store, self.monitor, raw_topic="iot/+/raw")
        self.subscriptions = []
        self.client.on_subscribe = lambda c, u, mid, reasons, p: self.subscriptions.append(reasons)
        self.client.connect("127.0.0.1", self.broker.port, 30)
        self.client.loop_start()
        until(lambda: len(self.subscriptions) >= 2, "Collector subscription failed")
        self.device = FakeDevice(self.device_id, self.broker.port)
        self.others = []

    def tearDown(self):
        self.device.close()
        for device in self.others:
            device.close()
        self.client.disconnect()
        self.client.loop_stop()
        self.validate_patch.stop()
        if self.device.errors:
            raise AssertionError(self.device.errors)

    def schedule(self, grace=2):
        due = self.now.replace(second=0)
        key = "TEST_SCHEDULE_"+uuid4().hex
        self.store.db.schedules.insert_one({"_id": key, "device_id": self.device_id,
            "hour": due.astimezone(LOCAL).strftime("%H:%M"), "weekdays": [due.astimezone(LOCAL).weekday()],
            "grace_minutes": grace, "enabled": True, "active_from": due-timedelta(seconds=1), "created_at": due-timedelta(seconds=1)})
        return key, due

    def send_session(self, kind="good", batches=30):
        session = "TEST_SESSION_"+uuid4().hex
        for batch in range(1, batches+1):
            body = raw_packet(self.device_id, session, batch, kind)
            self.device.publish(body)
            until(lambda: any(a.get("session_id") == session and a.get("batch_index") == batch for a in self.device.raw_acks), "No durable raw application ACK")
        return session

    def test_01_command_requires_application_ack_and_retry_is_deduplicated(self):
        _, due = self.schedule()
        self.device.auto_ack = False
        self.monitor.schedule_tick(self.now)
        self.monitor.dispatch(self.client, self.now)
        until(lambda: len(self.device.commands) == 1, "No due command")
        row = self.store.db.notifications.find_one()
        self.assertEqual(row["mqtt_status"], "published")
        self.device.ack(row["_id"], target="WRONG-DEVICE")
        time.sleep(.1)
        self.assertEqual(self.store.db.notifications.find_one()["mqtt_status"], "published")
        self.device.auto_ack = True
        self.monitor.dispatch(self.client, self.now+timedelta(seconds=31))
        until(lambda: self.store.db.notifications.find_one()["mqtt_status"] == "confirmed", "No application ACK")
        self.assertEqual(len(self.device.commands), 2)
        self.assertEqual(self.device.beeps, 1)
        self.monitor.dispatch(self.client, self.now+timedelta(seconds=62))
        self.assertEqual(self.store.db.notifications.count_documents({}), 1)

    def test_02_full_raw_session_completes_schedule_without_alert(self):
        _, due = self.schedule()
        session = self.send_session()
        self.monitor.scan_sessions(self.now)
        self.monitor.schedule_tick(self.now+timedelta(minutes=3))
        summary = self.store.db.session_summaries.find_one({"session_id": session})
        self.assertTrue(summary["complete"] and summary["good"])
        self.assertEqual(self.store.db.occurrences.find_one()["status"], "success")
        self.assertEqual(self.store.db.notifications.count_documents({"kind": "measurement_missed"}), 0)
        self.assertEqual(self.store.db.notifications.count_documents({"kind": "threshold"}), 0)
        self.assertEqual(self.store.db.raw_timeseries.count_documents({}), 30)
        self.assertEqual(len(self.device.raw_acks), 30)
        # Replay has the same identity and must not duplicate stored data.
        self.device.publish(raw_packet(self.device_id, session, 1))
        until(lambda: len(self.device.raw_acks) == 31, "No replay ACK")
        self.assertEqual(self.store.db.raw_inbox.count_documents({}), 30)
        self.assertEqual(self.store.db.raw_timeseries.count_documents({}), 30)

    def test_03_poor_and_partial_sessions_are_not_missed(self):
        self.schedule()
        session = self.send_session(kind="poor")
        self.monitor.scan_sessions(self.now)
        self.monitor.schedule_tick(self.now+timedelta(minutes=3))
        self.assertEqual(self.store.db.occurrences.find_one()["status"], "poor")
        self.assertFalse(self.store.db.session_summaries.find_one({"session_id": session})["good"])
        self.assertEqual(self.store.db.notifications.count_documents({"kind": "measurement_missed"}), 0)
        self.assertEqual(self.store.db.notifications.count_documents({"kind": "threshold"}), 0)

    def test_04_missing_measurement_sends_missed_then_expires(self):
        self.schedule()
        self.monitor.schedule_tick(self.now)
        self.monitor.dispatch(self.client, self.now)
        until(lambda: self.store.db.notifications.find_one()["mqtt_status"] == "confirmed", "No due ACK")
        later = self.now+timedelta(minutes=3)
        self.monitor.schedule_tick(later)
        self.monitor.dispatch(self.client, later)
        until(lambda: self.store.db.notifications.find_one({"kind": "measurement_missed"})["mqtt_status"] == "confirmed", "No missed ACK")
        self.assertEqual([c["event"] for c in self.device.commands], ["measurement_due", "measurement_missed"])
        self.assertEqual(self.store.db.occurrences.find_one()["status"], "missed")
        restarted = Monitor(self.store)
        restarted.schedule_tick(later)
        self.assertEqual(self.store.db.notifications.count_documents({}), 2)
        self.monitor.notify("TEST_EXPIRED", "measurement_due", self.device_id, "expired", self.now, self.now-timedelta(seconds=1))
        self.monitor.dispatch(self.client, later)
        self.assertEqual(self.store.db.notifications.find_one({"_id": "TEST_EXPIRED"})["mqtt_status"], "expired")
        self.assertEqual(len(self.device.commands), 2)

    def test_05_low_oxygen_alert_is_once_per_session_and_channel(self):
        self.send_session(kind="low_oxygen")
        self.monitor.scan_sessions(self.now)
        self.monitor.scan_sessions(self.now)
        rows = list(self.store.db.notifications.find({"kind": "threshold"}))
        self.assertEqual(len(rows), 1)
        self.assertIn("SpO₂", rows[0]["message"])
        self.assertEqual(rows[0]["mqtt_status"], "not_required")

    def test_06_invalid_raw_is_quarantined_without_application_ack(self):
        bad = raw_packet(self.device_id, "TEST_INVALID", 1)
        bad["red"].pop()
        self.device.publish(bad)
        until(lambda: self.store.db.quarantine.count_documents({}) == 1, "Invalid packet not quarantined")
        self.assertEqual(self.store.db.raw_inbox.count_documents({}), 0)
        self.assertFalse(self.device.raw_acks)

    def test_07_offline_device_receives_retry_after_reconnect(self):
        self.schedule()
        self.device.client.disconnect()
        until(lambda: not self.device.client.is_connected(), "Device did not disconnect")
        self.monitor.schedule_tick(self.now)
        self.monitor.dispatch(self.client, self.now)
        self.assertEqual(self.store.db.notifications.find_one()["mqtt_status"], "published")
        self.assertFalse(self.device.commands)
        self.device.ready.clear()
        self.device.client.loop_stop()
        self.device.client.reconnect()
        self.device.client.loop_start()
        until(self.device.ready.is_set, "Device did not reconnect")
        self.monitor.dispatch(self.client, self.now+timedelta(seconds=31))
        until(lambda: self.store.db.notifications.find_one()["mqtt_status"] == "confirmed", "Retry was not acknowledged")
        self.assertEqual(self.device.beeps, 1)

    def test_08_cancelled_schedule_does_not_send_commands(self):
        key, _ = self.schedule()
        self.monitor.schedule_tick(self.now)
        self.monitor.delete_schedule(key)
        self.monitor.dispatch(self.client, self.now)
        self.assertFalse(self.device.commands)
        self.assertEqual(self.store.db.notifications.find_one()["mqtt_status"], "cancelled")

    def test_09_partial_packets_have_receiving_then_poor_state(self):
        self.schedule()
        self.send_session(batches=1)
        self.monitor.scan_sessions(self.now)
        self.monitor.schedule_tick(self.now)
        self.assertEqual(self.store.db.occurrences.find_one()["status"], "receiving")
        self.monitor.schedule_tick(self.now+timedelta(minutes=3))
        self.assertEqual(self.store.db.occurrences.find_one()["status"], "poor")
        self.assertEqual(self.store.db.notifications.count_documents({"kind": "measurement_missed"}), 0)

    def test_10_web_schedule_to_mqtt_measurement_and_back_to_web(self):
        from streamlit.testing.v1 import AppTest
        import streamlit as st
        # Seed one older real-format session so the device is selectable in the UI.
        for batch in range(1, 31):
            record = validate(raw_packet(self.device_id, "TEST_OLD", batch), f"iot/{self.device_id}/raw", now=self.now-timedelta(hours=1))
            self.store.save_raw(record)
        self.store.project_pending()
        st.cache_resource.clear()

        with patch.object(storage, "MongoStore", return_value=self.store):
            app = AppTest.from_file(str(ROOT/"web.py"), default_timeout=25).run()
            app.radio[0].set_value("MongoDB").run()
            self.assertFalse(app.exception, [e.message for e in app.exception])
            due = (self.now+timedelta(minutes=1)).replace(second=0)
            app.time_input[0].set_value(due.astimezone(LOCAL).time().replace(tzinfo=None))
            next(b for b in app.button if b.label == "Lưu lịch").click().run()
            self.assertFalse(app.exception, [e.message for e in app.exception])
            self.assertEqual(self.store.db.schedules.count_documents({}), 1)
            self.clock = due+timedelta(seconds=1)
            self.monitor.schedule_tick(self.clock)
            self.monitor.dispatch(self.client, self.clock)
            until(lambda: self.store.db.notifications.find_one()["mqtt_status"] == "confirmed", "Web-created schedule not delivered to fake ESP32")
            self.send_session()
            self.monitor.scan_sessions(self.clock)
            self.monitor.schedule_tick(self.clock)
            self.assertEqual(self.store.db.occurrences.find_one()["status"], "success")
            app.run()
            self.assertFalse(app.exception, [e.message for e in app.exception])
            self.assertTrue(any("ESP32 đã xác nhận" in c.value for c in app.caption))
            self.assertTrue(any("Đo thành công" in str(d.value) for d in app.dataframe))
        st.cache_resource.clear()

    def test_11_worker_runs_without_an_open_web_session(self):
        self.schedule()
        stop = threading.Event()
        worker = threading.Thread(target=self.monitor.run, args=(self.client, stop), daemon=True)
        worker.start()
        try:
            until(lambda: self.store.db.monitor_state.find_one({"_id": "worker"}), "No background worker heartbeat")
            until(lambda: self.store.db.notifications.find_one()["mqtt_status"] == "confirmed", "Background reminder not delivered")
        finally:
            stop.set()
            worker.join(5)
        self.assertFalse(worker.is_alive())

    def test_12_database_write_failure_never_produces_saved_ack(self):
        from pymongo.errors import PyMongoError
        packet = raw_packet(self.device_id, "TEST_DB_FAILURE", 1)
        with patch.object(self.store, "save_raw", side_effect=PyMongoError("Simulated test DB outage")):
            self.device.publish(packet)
            until(lambda: not self.client.is_connected(), "Collector did not disconnect after DB failure")
            self.assertFalse(self.device.raw_acks)
            self.assertEqual(self.store.db.raw_inbox.count_documents({}), 0)
        self.client.loop_stop()
        self.subscriptions.clear()
        self.client.reconnect()
        self.client.loop_start()
        until(lambda: len(self.subscriptions) >= 2, "Collector did not resubscribe")
        self.device.publish(packet)
        until(lambda: self.device.raw_acks, "Recovered DB did not produce an application ACK")
        self.assertEqual(self.store.db.raw_inbox.count_documents({}), 1)

    def test_13_wrong_device_measurement_does_not_complete_schedule(self):
        self.schedule()
        other = FakeDevice("TEST-OTHER-"+uuid4().hex[:8], self.broker.port)
        self.others.append(other)
        for batch in range(1, 31):
            other.publish(raw_packet(other.device, "TEST_OTHER_SESSION", batch))
        until(lambda: len(other.raw_acks) == 30, "Other fake device did not receive all ACKs")
        self.monitor.scan_sessions(self.now)
        later = self.now+timedelta(minutes=3)
        self.monitor.schedule_tick(later)
        self.assertEqual(self.store.db.occurrences.find_one()["status"], "missed")
        self.assertEqual(self.store.db.notifications.find_one({"kind": "measurement_missed"})["device_id"], self.device_id)


class JsonResult(unittest.TextTestResult):
    def addSuccess(self, test):
        super().addSuccess(test)
        REPORT.append({"test": test.id().split(".")[-1], "status": "PASS"})
    def addFailure(self, test, err):
        super().addFailure(test, err)
        REPORT.append({"test": test.id().split(".")[-1], "status": "FAIL", "error": str(err[1])})
    def addError(self, test, err):
        super().addError(test, err)
        REPORT.append({"test": test.id().split(".")[-1], "status": "ERROR", "error": str(err[1])})


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2, resultclass=JsonResult)
    result = runner.run(unittest.defaultTestLoader.loadTestsFromTestCase(SystemTests))
    output = ROOT/"data"/"test-results"
    output.mkdir(parents=True, exist_ok=True)
    (output/"system-test.json").write_text(json.dumps({"tests": REPORT, "mqtt": "real TCP loopback broker",
        "database": "mongomock, isolated, not persistent MongoDB", "clock": "controlled test time",
        "hardware": "simulated Python device, no ESP32 firmware execution", "success": result.wasSuccessful()}, ensure_ascii=False, indent=2), encoding="utf-8")
    raise SystemExit(0 if result.wasSuccessful() else 1)
