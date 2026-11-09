"""Exercise MongoDB UI interactions against an in-memory DB, never production."""
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import mongomock

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
import storage
import demo
from monitoring import Monitor


def main():
    from streamlit.testing.v1 import AppTest
    import streamlit as st
    store = storage.MongoStore.__new__(storage.MongoStore)
    store.client = mongomock.MongoClient(tz_aware=True)
    store.db = store.client.signal_lab_test
    for record in demo.packets():
        store.db.raw_timeseries.insert_one({**record, "batch_id": record["_id"]})
    monitor = Monitor(store)
    monitor.setup()
    monitor.notify("test_notice", "measurement_due", "demo", "Đến giờ đo", datetime.now(timezone.utc), datetime.now(timezone.utc)+timedelta(minutes=30))
    st.cache_resource.clear()
    with patch.object(storage, "MongoStore", return_value=store):
        app = AppTest.from_file(str(root / "web.py"), default_timeout=25).run()
        app.radio[0].set_value("MongoDB").run()
        assert not app.exception, [e.message for e in app.exception]
        assert len(app.metric) == 3
        save = next(b for b in app.button if b.label == "Lưu lịch")
        save.click().run()
        assert not app.exception, [e.message for e in app.exception]
        schedule = store.db.schedules.find_one()
        assert schedule and schedule["device_id"] == "demo"
        next(s for s in app.selectbox if s.label == "Chỉnh sửa lịch").set_value(schedule["_id"]).run()
        assert not app.exception, [e.message for e in app.exception]
        next(c for c in app.checkbox if c.label == "Bật lịch").uncheck()
        next(b for b in app.button if b.label == "Lưu lịch").click().run()
        assert not app.exception, [e.message for e in app.exception]
        assert store.db.schedules.find_one()["enabled"] is False
        next(b for b in app.button if b.label == "Đánh dấu đã đọc").click().run()
        assert not app.exception, [e.message for e in app.exception]
        assert store.db.notifications.find_one({"_id": "test_notice"})["read"]
        next(b for b in app.button if b.label == "Lưu ngưỡng cảnh báo").click().run()
        assert not app.exception, [e.message for e in app.exception]
        assert store.db.monitor_settings.find_one({"_id": "limits"})
        next(c for c in app.checkbox if c.label == "Tôi muốn xóa lịch đang chọn").check().run()
        next(b for b in app.button if b.label == "Xóa lịch").click().run()
        assert not app.exception, [e.message for e in app.exception]
        assert store.db.schedules.count_documents({}) == 0
        print("Mongo UI passed: demo -> MongoDB, create/disable/delete schedule, mark read, save thresholds; no real DB writes")
    st.cache_resource.clear()


if __name__ == "__main__":
    main()
