import copy
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import mongomock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from monitoring import Monitor, identity, occurrence_state, exceeded, DEFAULT_LIMITS, LOCAL
import demo

UTC = timezone.utc


class MonitoringTests(unittest.TestCase):
    def setUp(self):
        self.db = mongomock.MongoClient(tz_aware=True).signal_lab
        self.monitor = Monitor(SimpleNamespace(db=self.db))
        self.monitor.setup()
        self.due = datetime(2026, 11, 6, 1, 0, tzinfo=UTC)  # 08:00 local
        self.schedule = {"_id": "s1", "device_id": "esp32-01", "hour": "08:00", "weekdays": [4],
                         "grace_minutes": 30, "enabled": True, "active_from": self.due-timedelta(days=1)}
        self.db.schedules.insert_one(self.schedule)
        self.client = Mock()
        self.client.is_connected.return_value = True
        self.client.publish.return_value.is_published.return_value = True

    def test_due_deduplicates_and_requires_device_ack(self):
        self.monitor.schedule_tick(self.due)
        self.monitor.schedule_tick(self.due+timedelta(seconds=15))
        self.assertEqual(self.db.notifications.count_documents({}), 1)
        row = self.db.notifications.find_one()
        self.assertEqual(row["mqtt_status"], "pending")
        self.monitor.dispatch(self.client, self.due)
        self.assertEqual(self.db.notifications.find_one()["mqtt_status"], "published")
        topic, body = self.client.publish.call_args.args
        self.assertEqual(topic, "iot/esp32-01/control")
        self.assertFalse(self.client.publish.call_args.kwargs["retain"])
        self.assertEqual(json.loads(body)["expires_at"], int((self.due+timedelta(minutes=30)).timestamp()))
        self.monitor.confirm("iot/other/control_ack", json.dumps({"device_id": "other", "event_id": row["_id"], "received": True}).encode())
        self.assertEqual(self.db.notifications.find_one()["mqtt_status"], "published")
        self.monitor.confirm("iot/esp32-01/control_ack", json.dumps({"device_id": "esp32-01", "event_id": row["_id"], "received": True}).encode())
        self.assertEqual(self.db.notifications.find_one()["mqtt_status"], "confirmed")
        self.monitor.dispatch(self.client, self.due+timedelta(seconds=60))
        self.assertEqual(self.client.publish.call_count, 1)

    def test_retry_expiry_and_missed_event_are_separate(self):
        self.monitor.schedule_tick(self.due)
        self.monitor.dispatch(self.client, self.due)
        self.monitor.dispatch(self.client, self.due+timedelta(seconds=15))
        self.assertEqual(self.client.publish.call_count, 1)
        self.monitor.dispatch(self.client, self.due+timedelta(seconds=30))
        self.assertEqual(self.client.publish.call_count, 2)
        now = self.due+timedelta(minutes=31)
        self.monitor.schedule_tick(now)
        self.monitor.dispatch(self.client, now)
        self.assertEqual(self.db.occurrences.find_one()["status"], "missed")
        self.assertEqual(self.db.notifications.find_one({"kind": "measurement_due"})["mqtt_status"], "expired")
        self.assertEqual(self.db.notifications.count_documents({"kind": "measurement_missed"}), 1)
        self.monitor.schedule_tick(now+timedelta(seconds=15))
        self.assertEqual(self.db.notifications.count_documents({"kind": "measurement_missed"}), 1)

    def test_fast_device_ack_cannot_be_overwritten_by_publish_status(self):
        self.monitor.schedule_tick(self.due)
        def publish(topic, payload, **kwargs):
            event = json.loads(payload)
            self.monitor.confirm("iot/esp32-01/control_ack", json.dumps({
                "device_id": "esp32-01", "event_id": event["event_id"], "received": True}).encode())
            response = Mock()
            response.is_published.return_value = True
            return response
        self.client.publish.side_effect = publish
        self.monitor.dispatch(self.client, self.due)
        self.assertEqual(self.db.notifications.find_one()["mqtt_status"], "confirmed")

    def test_poor_measurement_is_not_missed_and_can_later_succeed(self):
        self.monitor.schedule_tick(self.due)
        self.db.session_summaries.insert_one({"_id": "session", "device_id": "esp32-01", "first_received": self.due,
                                             "complete": True, "good": False})
        self.monitor.schedule_tick(self.due+timedelta(minutes=31))
        self.assertEqual(self.db.occurrences.find_one()["status"], "poor")
        self.assertEqual(self.db.notifications.count_documents({"kind": "measurement_missed"}), 0)
        self.assertEqual(self.db.notifications.find_one()["mqtt_status"], "cancelled")
        self.db.session_summaries.update_one({"_id": "session"}, {"$set": {"good": True}})
        self.monitor.schedule_tick(self.due+timedelta(minutes=32))
        self.assertEqual(self.db.occurrences.find_one()["status"], "success")

    def test_late_or_other_device_session_does_not_satisfy_schedule(self):
        for device, first in [("other", self.due), ("esp32-01", self.due+timedelta(minutes=31))]:
            self.db.session_summaries.insert_one({"device_id": device, "first_received": first, "complete": True, "good": True})
        self.monitor.schedule_tick(self.due+timedelta(minutes=32))
        self.assertEqual(self.db.occurrences.find_one()["status"], "missed")

    def test_restart_catches_up_without_sending_expired_commands(self):
        self.monitor.schedule_tick(self.due+timedelta(hours=4))
        self.monitor.dispatch(self.client, self.due+timedelta(hours=4))
        self.assertEqual(self.db.occurrences.find_one()["status"], "missed")
        self.client.publish.assert_not_called()

    def test_incomplete_measurement_has_own_state(self):
        sessions = [{"complete": False}]
        deadline = self.due+timedelta(minutes=30)
        self.assertEqual(occurrence_state(self.due, deadline, sessions), "receiving")
        self.assertEqual(occurrence_state(deadline, deadline, sessions), "poor")

    def test_thresholds_only_accept_valid_results(self):
        result = {"bpm": 150., "bpm_valid": False, "spo2": 90., "spo2_valid": False,
                  "temperature": {"object": {"value": 45., "stable": False}}}
        limits = copy.deepcopy(DEFAULT_LIMITS)
        limits["object_temp"]["enabled"] = True
        self.assertEqual(list(exceeded(result, limits)), [])
        result["bpm_valid"] = result["spo2_valid"] = True
        self.assertEqual([r[0] for r in exceeded(result, limits)], ["bpm", "spo2"])

    def test_scan_real_demo_pipeline_deduplicates_alerts_and_preserves_raw(self):
        packets = demo.packets()
        self.db.raw_inbox.insert_many(copy.deepcopy(packets))
        before = list(self.db.raw_inbox.find())
        self.db.monitor_settings.insert_one({"_id": "limits", "values": {"bpm": {"enabled": True, "low": 10, "high": 20}}})
        self.monitor.scan_sessions(self.due)
        self.monitor.scan_sessions(self.due+timedelta(seconds=15))
        self.assertEqual(self.db.notifications.count_documents({"kind": "threshold"}), 1)
        self.assertEqual(self.db.notifications.find_one()["mqtt_status"], "not_required")
        self.assertEqual(list(self.db.raw_inbox.find()), before)
        self.assertTrue(self.db.session_summaries.find_one()["complete"])
        self.assertTrue(self.db.session_summaries.find_one()["good"])

    def test_delete_cancels_outbox_but_preserves_history(self):
        self.monitor.schedule_tick(self.due)
        self.monitor.delete_schedule("s1")
        self.assertEqual(self.db.schedules.count_documents({}), 0)
        self.assertEqual(self.db.notifications.find_one()["mqtt_status"], "cancelled")
        self.assertEqual(self.db.occurrences.find_one()["status"], "cancelled")

    def test_ack_before_attempt_and_invalid_shapes_are_not_accepted(self):
        self.monitor.schedule_tick(self.due)
        row = self.db.notifications.find_one()
        self.monitor.confirm("iot/esp32-01/control_ack", json.dumps({"device_id": "esp32-01", "event_id": row["_id"], "received": True}).encode())
        self.assertEqual(self.db.notifications.find_one()["mqtt_status"], "pending")
        for body in ([], None, {"device_id": "wrong"}):
            with self.assertRaises(ValueError):
                self.monitor.confirm("iot/esp32-01/control_ack", json.dumps(body).encode())

    def test_local_timezone(self):
        self.assertEqual(self.due.astimezone(LOCAL).strftime("%H:%M"), "08:00")


if __name__ == "__main__":
    unittest.main()
