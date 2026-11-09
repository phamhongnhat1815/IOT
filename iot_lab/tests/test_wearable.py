"""Wearable protocol ordering, command confirmation, and native fall state machine."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock
from pymongo.errors import DuplicateKeyError, OperationFailure

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'iot_lab'))
from alerts import validate_event, save_event, dispatch_commands


def event(state='active'):
    return {'schema_version':1,'device_id':'esp32-01','event_id':'fall-123',
            'revision':1 if state=='active' else 2,'kind':'fall','state':state,
            'uptime_ms':10000,'occurred_at':0,'command_id':'','detector':'pendant_sequence_trial_v1'}


class MemoryCollection:
    def __init__(self): self.rows={}
    def insert_one(self,row):
        if row['_id'] in self.rows: raise DuplicateKeyError('duplicate')
        self.rows[row['_id']]=copy.deepcopy(row)
    def find_one(self,query,projection=None): return self.rows.get(query['_id'])
    def update_one(self,query,update,upsert=False):
        key=query['_id']; old=self.rows.get(key)
        if upsert and old and old['revision']>=query['revision']['$lt']:
            raise DuplicateKeyError('newer row exists')
        if old or upsert:self.rows[key]={'_id':key,**update['$set']}


class MemoryDB:
    def __init__(self):self.collections={}
    def get_collection(self,name,**kwargs):return self.collections.setdefault(name,MemoryCollection())


class WearableProtocolTests(unittest.TestCase):
    def test_validate_topic_and_types(self):
        self.assertEqual(validate_event(json.dumps(event()),'iot/esp32-01/event'),event())
        for key,value in [('revision',True),('state','pending'),('command_id','x/y'),('occurred_at',-1)]:
            d=event();d[key]=value
            with self.assertRaises(ValueError):validate_event(json.dumps(d),'iot/esp32-01/event')
        with self.assertRaises(ValueError):validate_event(json.dumps(event()),'iot/other/event')

    def test_replay_idempotent_and_cleared_never_reopens(self):
        db=MemoryDB();d=event();ack=save_event(db,d)
        self.assertTrue(ack['saved']);self.assertEqual(ack['revision'],1)
        self.assertEqual(save_event(db,d),ack)
        save_event(db,event('cleared'));save_event(db,d)
        self.assertEqual(len(db.get_collection('alert_events').rows),2)
        self.assertEqual(db.get_collection('alert_states').rows['esp32-01:fall-123']['state'],'cleared')

    def test_conflicting_replay_is_not_acknowledged(self):
        db=MemoryDB();save_event(db,event());d=event();d['kind']='sos'
        with self.assertRaises(ValueError):save_event(db,d)

    def test_database_failure_does_not_return_saved_ack(self):
        db=Mock();db.get_collection.return_value.insert_one.side_effect=OperationFailure('write failed')
        with self.assertRaises(OperationFailure):save_event(db,event())

    def test_remote_clear_confirmed_only_by_matching_device_event(self):
        db=MemoryDB();command='abc123';d=event('cleared');d['command_id']=command
        commands=Mock();real=db.get_collection
        db.get_collection=lambda name,**kw:commands if name=='alert_commands' else real(name,**kw)
        save_event(db,d)
        query,update=commands.update_one.call_args.args
        self.assertEqual(query,{'_id':command,'device_id':'esp32-01','event_id':'fall-123'})
        self.assertEqual(update['$set']['status'],'confirmed')

    def test_command_publish_is_nonretained_and_not_a_confirmation(self):
        db=Mock();db.alert_commands.find.return_value.limit.return_value=[{
            '_id':'cmd1','device_id':'esp32-01','event_id':'fall-123','expires_at':200}]
        client=Mock();client.publish.return_value.rc=0
        dispatch_commands(db,client,now=100)
        self.assertFalse(client.publish.call_args.kwargs['retain'])
        self.assertEqual(client.publish.call_args.args[0],'iot/esp32-01/command')
        self.assertEqual(db.alert_commands.update_one.call_args.args[1]['$set']['status'],'sent')

    @unittest.skipUnless(shutil.which('c++'),'native C++ compiler required')
    def test_native_fall_sequence(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary=str(Path(tmp)/'fall_test')
            subprocess.run(['c++','-std=c++17','-I',str(ROOT/'firmware/HealthRawDirect'),
                str(ROOT/'iot_lab/tests/cpp/fall_detector_test.cpp'),'-o',binary],check=True,capture_output=True)
            subprocess.run([binary],check=True,capture_output=True)


if __name__=='__main__':unittest.main()
