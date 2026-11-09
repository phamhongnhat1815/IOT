"""Alarm control remains available even if there are no measurement sessions."""
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import mongomock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import storage


class AlertUITests(unittest.TestCase):
    def test_alarm_without_measurements_and_clear_is_only_a_request(self):
        from streamlit.testing.v1 import AppTest
        import streamlit as st
        st.cache_resource.clear()
        store=storage.MongoStore.__new__(storage.MongoStore)
        store.client=mongomock.MongoClient(tz_aware=True)
        store.db=store.client.signal_lab_alarm_test
        row={'_id':'esp32-01:fall-123','device_id':'esp32-01','event_id':'fall-123',
             'kind':'fall','state':'active','received_at':datetime.now(timezone.utc)}
        store.db.alert_states.insert_one(row)
        with patch('storage.MongoStore',return_value=store):
            app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'web.py'),default_timeout=25).run()
            app.radio[0].set_value('MongoDB').run()
            self.assertFalse(app.exception,[e.message for e in app.exception])
            self.assertTrue(any('SOS' in e.value for e in app.subheader))
            button=next(b for b in app.button if b.label=='Yêu cầu tắt báo động')
            button.click().run()
            self.assertFalse(app.exception,[e.message for e in app.exception])
            self.assertTrue(any('Chờ collector' in e.value for e in app.info))
            self.assertFalse(any('ESP32 đã xác nhận tắt' in e.value for e in app.success))
        st.cache_resource.clear()


if __name__=='__main__':unittest.main()
