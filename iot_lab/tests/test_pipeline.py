import copy
import json
import sys
import unittest
from datetime import datetime,timezone
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from model import validate
from frames import frames
import demo


class PipelineTests(unittest.TestCase):
    def setUp(self):self.p=copy.deepcopy(demo.packets()[0]["data"])

    def test_demo_has_1500_samples_and_15_temperatures(self):
        raw,temp,q=frames(demo.packets())
        self.assertEqual(len(raw),1500);self.assertEqual(len(temp),15)
        self.assertTrue(q["complete"]);self.assertEqual(q["rate"],100)

    def test_reject_noninteger_or_out_of_range(self):
        for value in (True,float("nan"),-1,262144,1.1):
            p=copy.deepcopy(self.p);p["ir"][0]=value
            with self.assertRaises(ValueError):validate(p,"iot/demo/raw")

    def test_reject_device_topic_and_array_mismatch(self):
        with self.assertRaises(ValueError):validate(self.p,"iot/other/raw")
        self.p["red"].pop()
        with self.assertRaises(ValueError):validate(self.p,"iot/demo/raw")

    def test_retry_same_identity_and_hash(self):
        first=validate(self.p,"iot/demo/raw")
        self.p["sent_at_ms"]=1000
        retry=validate(self.p,"iot/demo/raw")
        self.assertEqual(first["_id"],retry["_id"])
        self.assertEqual(first["digest"],retry["digest"])
        self.p["ir"][0]+=1
        changed=validate(self.p,"iot/demo/raw")
        self.assertEqual(first["_id"],changed["_id"])
        self.assertNotEqual(first["digest"],changed["digest"])

    def test_latency_requires_clock_sync(self):
        now=datetime.fromtimestamp(1700000000,tz=timezone.utc)
        self.p["sent_at_ms"]=1699999999950
        self.assertIsNone(validate(self.p,"iot/demo/raw",now)["e2e_ms"])
        self.p["clock_synced"]=True
        self.assertEqual(validate(self.p,"iot/demo/raw",now)["e2e_ms"],50)

    def test_gap_is_not_interpolated(self):
        packets=demo.packets();del packets[5]
        raw,temp,q=frames(packets)
        self.assertEqual(len(raw),1450);self.assertFalse(q["complete"])
        self.assertEqual(raw.iloc[250]["index"],300)
        self.assertGreater(raw.iloc[250]["segment"],raw.iloc[249]["segment"])

    def test_legacy_ppg_raw(self):
        original={"boot_id":"boot","window_id":0,"window_offset":0,"sample_rate_hz":100,
                  "object_temp":34,"ambient_temp":28,"temperature_read_ms":1000,
                  "ppg_raw":{"ir":[80000]*50,"red":[70000]*50}}
        result=validate(json.dumps(original),"iot/esp32-01/raw")
        self.assertEqual(result["data"]["batch_total"],30)
        self.assertEqual(result["data"]["session_id"],"boot:w0")

    def test_optional_preprocessing_preserves_raw_and_gaps(self):
        from preprocess import transform
        packets=demo.packets();del packets[5]
        raw,temps,_=frames(packets);before=raw.copy(deep=True)
        processed,temp=transform(raw,temps)
        self.assertTrue(raw.equals(before));self.assertEqual(len(processed),1450)
        self.assertIsNone(processed[250]["ir_delta"])
        self.assertGreaterEqual(min(p["ir_scaled"] for p in processed),0)
        self.assertLessEqual(max(p["ir_scaled"] for p in processed),1.000001)


if __name__=="__main__":unittest.main()
