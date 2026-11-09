"""Headless Streamlit UI check. Does not require MongoDB or MQTT."""
import faulthandler
import os
import sys
from pathlib import Path

def main():
    root=Path(__file__).resolve().parents[1]
    sys.path.insert(0,str(root));os.chdir(root)
    faulthandler.dump_traceback_later(30)
    print("Loading Streamlit test runtime",flush=True)
    from streamlit.testing.v1 import AppTest
    print("Running dashboard",flush=True)
    app=AppTest.from_file(str(root/"web.py"),default_timeout=25).run()
    assert not app.exception,[e.message for e in app.exception]
    assert len(app.metric)==3
    assert app.metric[0].label=="Nhịp mạch ước tính"
    assert app.metric[1].label=="SpO₂ ước tính"
    assert app.metric[2].label=="Nhiệt độ bề mặt"
    assert "bpm" in app.metric[0].value, app.metric[0].value
    assert "°C" in app.metric[2].value
    assert [t.label for t in app.tabs]==["Phân tích","Dữ liệu thô","Tiền xử lý"]
    assert any("MINH HỌA" in e.value for e in app.info)
    assert any("Chưa có kết luận y khoa" in e.value for e in app.markdown)
    faulthandler.cancel_dump_traceback_later()
    print("UI passed: 3 research metrics, 3 tabs, visible demo and clinical limits",flush=True)


if __name__=="__main__":main()
