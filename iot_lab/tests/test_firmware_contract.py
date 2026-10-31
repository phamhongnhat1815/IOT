"""Check the firmware v2 MQTT contract against the real Python validator/ACK."""
import json
import sys
import unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from model import validate
from frames import frames
from collector import acknowledgement


def packet(batch):
    first=(batch-1)*50
    return {"schema_version":2,"device_id":"esp32-01","session_id":"esp32-01-aabbccdd11223344-1",
            "batch_index":batch,"batch_total":30,"sample_start_index":first,"sample_count":50,
            "sample_rate_hz":100,"object_temp":34.25,"ambient_temp":28.5,
            "temperature_at_ms":5000+(first//100)*1000,
            "start_read_us":5000000+first*10000,"end_read_us":5000000+(first+49)*10000,
            "clock":"device_uptime","clock_synced":False,"gap_detected":False,
            "red":[70000+i for i in range(50)],"ir":[81000+i for i in range(50)]}


class FirmwareContractTests(unittest.TestCase):
    def test_30_batches_give_1500_pairs_and_matching_acks(self):
        records=[]
        for batch in range(1,31):
            record=validate(json.dumps(packet(batch)),"iot/esp32-01/raw")
            records.append(record)
            ack=acknowledgement(record)
            self.assertIs(ack["saved"],True)
            self.assertEqual(ack["session_id"],packet(batch)["session_id"])
            self.assertEqual(ack["device_id"],"esp32-01")
            self.assertEqual(ack["batch_index"],batch)
            self.assertEqual(ack["sample_count"],50)
        raw,temp,quality=frames(records)
        self.assertEqual(len(raw),1500);self.assertEqual(len(temp),15)
        self.assertTrue(quality["complete"])

    def test_flash_replay_keeps_database_identity_across_restart(self):
        body=json.dumps(packet(9))
        now=datetime.now(timezone.utc)
        first=validate(body,"iot/esp32-01/raw",now)
        retry=validate(body,"iot/esp32-01/raw",now+timedelta(days=1))
        self.assertEqual(first["_id"],retry["_id"])
        self.assertEqual(first["digest"],retry["digest"])
        self.assertIsNone(retry["e2e_ms"])

    def test_wrong_sample_count_cannot_reach_ack_generation(self):
        body=packet(1);body["sample_count"]=1500
        with self.assertRaises(ValueError):validate(body,"iot/esp32-01/raw")


if __name__=="__main__":unittest.main()
