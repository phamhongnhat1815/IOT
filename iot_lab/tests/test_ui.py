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
    assert len(app.metric)==4
    assert app.metric[3].value=="1,500"
    assert [t.label for t in app.tabs]==["Dữ liệu thô","Tiền xử lý"]
    faulthandler.cancel_dump_traceback_later()
    print("UI passed: 4 metrics, 2 tabs, demo 1500 samples",flush=True)


if __name__=="__main__":main()
