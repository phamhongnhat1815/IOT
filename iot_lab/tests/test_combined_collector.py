"""Both MQTT contracts must remain reachable after the dashboard merge."""
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import mongomock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from collector import configure_callbacks


class CombinedCollectorTests(unittest.TestCase):
    def test_alarm_and_reminder_routes_are_both_kept(self):
        client, monitor, store = Mock(), Mock(), Mock()
        store.db = mongomock.MongoClient(tz_aware=True).integration
        configure_callbacks(client, store, monitor, "iot/+/raw")
        client.on_connect(client, None, None, SimpleNamespace(is_failure=False), None)
        self.assertEqual({call.args[0] for call in client.subscribe.call_args_list},
                         {"iot/+/raw", "iot/+/event", "iot/+/control_ack"})
        event = {"schema_version": 1, "device_id": "esp32-01", "event_id": "sos-123",
                 "revision": 1, "kind": "sos", "state": "active", "uptime_ms": 100,
                 "occurred_at": 0, "command_id": "", "detector": "pendant_sequence_trial_v1"}
        message = SimpleNamespace(topic="iot/esp32-01/event", payload=json.dumps(event).encode(), qos=1, mid=1)
        client.on_message(client, None, message)
        self.assertEqual(store.db.alert_states.find_one()["kind"], "sos")
        self.assertEqual(client.publish.call_args.args[0], "iot/esp32-01/event_ack")
        store.save_raw.assert_not_called()
        ack = SimpleNamespace(topic="iot/esp32-01/control_ack", payload=b"{}", qos=1, mid=2)
        client.on_message(client, None, ack)
        monitor.confirm.assert_called_once_with(ack.topic, ack.payload)


if __name__ == "__main__":
    unittest.main()
