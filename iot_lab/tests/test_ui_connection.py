"""UI regression for unavailable MongoDB; never connects to production."""
import sys
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import storage
import streamlit as st
from pymongo.errors import ServerSelectionTimeoutError
from streamlit.testing.v1 import AppTest


def main():
    store = Mock()
    store.devices.side_effect = ServerSelectionTimeoutError("test unavailable")
    st.cache_resource.clear()
    with patch.object(storage, "MongoStore", return_value=store):
        app = AppTest.from_file(str(ROOT / "web.py"), default_timeout=25).run()
        assert not app.exception
        assert app.selectbox[0].disabled
        assert any("Thấp hơn ngưỡng tham khảo 95" in w.value for w in app.warning)
        assert any("Dữ liệu thô" in m.value for m in app.markdown)
        app.radio[0].set_value("MongoDB").run()
        assert not app.exception
        assert store.devices.call_count == 1
        assert not store.db.mock_calls, store.db.mock_calls
        assert any("Chưa có thiết bị" in m.value for m in app.markdown)
        assert any(b.label == "Thử kết nối lại" for b in app.button)
        app.run()
        assert store.devices.call_count == 1, "Must not retry on unrelated reruns"
        next(b for b in app.button if b.label == "Thử kết nối lại").click().run()
        assert store.devices.call_count == 2
        assert not app.exception
    st.cache_resource.clear()
    print("PASS: demo warning, disabled filter, raw labels, failure isolation, explicit retry")


if __name__ == "__main__":
    main()
