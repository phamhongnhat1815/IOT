import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from overview_state import next_appointment, main_action

UTC = timezone.utc


class OverviewStateTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 7, 0, 30, tzinfo=UTC)  # Saturday 07:30 local
        self.schedule = {"enabled": True, "hour": "08:00", "weekdays": [5],
                         "active_from": self.now - timedelta(days=2), "device_id": "esp32-01"}

    def test_next_time_uses_local_weekday_and_repeats_next_week(self):
        upcoming = next_appointment([self.schedule], self.now)
        self.assertEqual(upcoming["due_at"], datetime(2026, 11, 7, 1, tzinfo=UTC))
        next_week = next_appointment([self.schedule], upcoming["due_at"])
        self.assertEqual(next_week["due_at"], upcoming["due_at"] + timedelta(days=7))

    def test_disabled_and_not_yet_active_schedules_are_not_shown(self):
        self.assertIsNone(next_appointment([{**self.schedule, "enabled": False}], self.now))
        delayed = {**self.schedule, "active_from": self.now + timedelta(days=1)}
        self.assertEqual(next_appointment([delayed], self.now)["due_at"], datetime(2026, 11, 14, 1, tzinfo=UTC))

    def test_empty_schedule_does_not_invent_an_appointment(self):
        self.assertIsNone(next_appointment([], self.now))

    def test_current_due_takes_priority_over_old_poor_session(self):
        result = {"bpm_valid": False, "spo2_valid": False}
        _, title, _ = main_action(result, {"complete": True}, {"current": {"status": "due"}})
        self.assertEqual(title, "Đã đến giờ đo")

    def test_missing_quality_and_connection_have_distinct_actions(self):
        _, missing, _ = main_action(None, {}, {})
        _, poor, _ = main_action({"bpm_valid": False, "spo2_valid": False}, {"complete": True}, {})
        _, failed, _ = main_action(None, {}, {"error": True})
        self.assertNotEqual(missing, poor)
        self.assertNotEqual(failed, missing)


if __name__ == "__main__":
    unittest.main()
