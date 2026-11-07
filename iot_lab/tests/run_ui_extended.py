"""Expanded UI checks. All storage and raw threshold files are isolated."""
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone, time
from pathlib import Path
from unittest.mock import patch

import mongomock
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import config
import demo
import storage
from monitoring import Monitor
from preprocess import transform
from frames import frames


def element(items, label):
    return next(item for item in items if item.label == label)


def clean(app):
    assert not app.exception, [e.message for e in app.exception]


def has_rule(value):
    if isinstance(value, dict):
        return value.get("type") == "rule" or any(has_rule(item) for item in value.values())
    if isinstance(value, list):
        return any(has_rule(item) for item in value)
    return False


def main():
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    store = storage.MongoStore.__new__(storage.MongoStore)
    store.client = mongomock.MongoClient(tz_aware=True)
    store.db = store.client.signal_lab_ui_extended
    packets = demo.packets()
    for record in packets:
        store.db.raw_timeseries.insert_one({**record, "batch_id": record["_id"]})
        old = {**record, "_id": record["_id"]+"-old", "batch_id": record["_id"]+"-old",
               "session_id": "TEST_OLD", "ts": record["ts"]-timedelta(hours=3)}
        store.db.raw_timeseries.insert_one(old)
        other = {**record, "_id": record["_id"]+"-other", "batch_id": record["_id"]+"-other",
                 "meta": {"device_id": "TEST-OTHER"}, "session_id": "TEST_OTHER",
                 "ts": record["ts"]-timedelta(hours=3)}
        store.db.raw_timeseries.insert_one(other)
    samples, temps, _ = frames(packets)
    processed, temperatures = transform(samples, temps)
    store.db.processed_timeseries.insert_one({"batch_id": "TEST_PROCESSED", "meta": {"device_id": "demo"},
        "session_id": "demo-15s", "ts": datetime.now(timezone.utc), "data": {"sample_start_index": 0},
        "frame": processed, "temperature_resampled": temperatures})
    monitor = Monitor(store)
    monitor.setup()
    monitor.notify("TEST_UI_NOTICE", "measurement_due", "demo", "TEST_UI reminder", datetime.now(timezone.utc),
                   datetime.now(timezone.utc)+timedelta(minutes=30))
    st.cache_resource.clear()
    with tempfile.TemporaryDirectory(prefix="signal-ui-test-") as temp:
        with patch.object(storage, "MongoStore", return_value=store), patch.object(config, "ROOT", Path(temp)):
            app = AppTest.from_file(str(ROOT/"web.py"), default_timeout=25).run()
            app.radio[0].set_value("MongoDB").run()
            clean(app)
            # Device without a recent session: no fabricated zero/healthy measurements.
            element(app.selectbox, "Thiết bị").set_value("TEST-OTHER").run()
            element(app.selectbox, "Khoảng thời gian").set_value(1).run()
            clean(app)
            assert all(metric.value == "—" for metric in app.metric)
            assert any("Chưa có kết quả đo" in m.value for m in app.markdown)
            element(app.selectbox, "Thiết bị").set_value("demo").run()
            assert len(element(app.selectbox, "Phiên đo").options) == 1
            element(app.selectbox, "Khoảng thời gian").set_value(24).run()
            assert len(element(app.selectbox, "Phiên đo").options) == 2
            element(app.selectbox, "Phiên đo").set_value("TEST_OLD").run()
            clean(app)
            element(app.selectbox, "Phiên đo").set_value("demo-15s").run()
            assert any("ir_mean" in frame.value.columns for frame in app.dataframe)
            element(app.toggle, "Tự cập nhật").set_value(False).run()
            clean(app)
            # Form validation must reject writes, not merely show text.
            element(app.multiselect, "Ngày lặp lại").set_value([])
            element(app.button, "Lưu lịch").click().run()
            assert app.error and store.db.schedules.count_documents({}) == 0
            element(app.multiselect, "Ngày lặp lại").set_value(list(range(7)))
            element(app.text_input, "Mã thiết bị").set_value("INVALID DEVICE!")
            element(app.button, "Lưu lịch").click().run()
            assert app.error and store.db.schedules.count_documents({}) == 0
            element(app.text_input, "Mã thiết bị").set_value("demo")
            element(app.button, "Lưu lịch").click().run()
            clean(app)
            schedule = store.db.schedules.find_one()
            element(app.selectbox, "Chỉnh sửa lịch").set_value(schedule["_id"]).run()
            element(app.time_input, "Giờ đo").set_value(time(9, 15))
            element(app.number_input, "Khoảng chờ trước khi coi là bỏ lịch (phút)").set_value(5)
            element(app.checkbox, "Bật lịch").uncheck()
            element(app.button, "Lưu lịch").click().run()
            clean(app)
            saved = store.db.schedules.find_one()
            assert saved["hour"] == "09:15" and saved["grace_minutes"] == 5 and not saved["enabled"]
            element(app.checkbox, "Bật lịch").check()
            element(app.button, "Lưu lịch").click().run()
            assert store.db.schedules.find_one()["enabled"]
            # Invalid threshold range must not replace stored settings.
            app.number_input(key="bpmhigh").set_value(30.)
            element(app.button, "Lưu ngưỡng cảnh báo").click().run()
            assert app.error and store.db.monitor_settings.count_documents({}) == 0
            app.number_input(key="bpmhigh").set_value(100.)
            element(app.button, "Lưu ngưỡng cảnh báo").click().run()
            assert store.db.monitor_settings.count_documents({}) == 1
            element(app.checkbox, "Chỉ hiện chưa đọc").check().run()
            element(app.button, "Đánh dấu đã đọc").click().run()
            clean(app)
            assert store.db.notifications.find_one()["read"]
            assert not any(button.label == "Đánh dấu đã đọc" for button in app.button)
            # The filesystem config is redirected to a disposable directory.
            element(app.checkbox, "IR").check()
            element(app.text_input, "IR — dưới").set_value("40000")
            element(app.text_input, "IR — trên").set_value("120000")
            element(app.button, "Lưu đường ngưỡng").click().run()
            clean(app)
            settings = Path(temp)/"data"/"thresholds.json"
            before = settings.read_text(encoding="utf-8")
            assert json.loads(before)["ir"]["enabled"]
            charts = list(app.get("arrow_vega_lite_chart")) + list(app.get("vega_lite_chart"))
            assert any(has_rule(json.loads(chart.proto.spec)) for chart in charts), f"Saved plot thresholds did not refresh with auto-update disabled; chart count={len(charts)}"
            element(app.text_input, "IR — dưới").set_value("130000")
            element(app.button, "Lưu đường ngưỡng").click().run()
            clean(app)
            assert app.error and settings.read_text(encoding="utf-8") == before
            # Restore a valid form state and verify persisted state survives rerun.
            element(app.text_input, "IR — dưới").set_value("40000")
            element(app.button, "Lưu đường ngưỡng").click().run()
            app.run()
            clean(app)
            assert store.db.schedules.count_documents({}) == 1
            assert store.db.notifications.find_one()["read"]
    st.cache_resource.clear()
    print("Extended UI PASS: sources/devices/sessions/time filter, no data, auto update toggle, processed data, invalid/valid schedule forms, edit/re-enable, invalid/valid thresholds, unread filter, raw plot settings, persisted state. No production writes.")


if __name__ == "__main__":
    main()
