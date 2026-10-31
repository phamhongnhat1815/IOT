"""Validation only. No pulse, SpO2 or diagnostic algorithm."""
import hashlib
import json
import math
import re
from datetime import datetime, timezone

IDENTIFIER = re.compile(r"^[a-zA-Z0-9_.:-]{1,100}$")


def finite(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (float,int)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name}: invalid number")
    return value


def integer(value, name, low, high):
    if isinstance(value,bool) or not isinstance(value,int) or not low <= value <= high:
        raise ValueError(f"{name}: invalid integer")
    return value


def validate(message, topic, now=None):
    if isinstance(message,(str,bytes)):
        if len(message)>64000: raise ValueError("message too large")
        message=json.loads(message)
    if not isinstance(message,dict): raise ValueError("JSON object required")
    path=topic.split("/")
    if len(path)!=3 or path[0]!="iot" or path[2]!="raw" or not IDENTIFIER.fullmatch(path[1]):
        raise ValueError("topic must be iot/<device_id>/raw")
    if "raw_batch" in message:
        p=dict(message["raw_batch"])
    elif "ppg_raw" in message:
        # Compatibility with the old payload, once it is sent to this broker/topic.
        raw=message["ppg_raw"]
        if isinstance(raw,str): raw=json.loads(raw)
        p={"device_id":path[1],"session_id":f'{message.get("boot_id", "")}:w{message.get("window_id", "")}',
           "batch_index":integer(message.get("window_offset"),"window_offset",0,100000)//len(raw["ir"])+1,
           "batch_total":message.get("window_samples",1500)//len(raw["ir"]),
           "sample_start_index":message.get("window_offset"),"sample_rate_hz":message.get("sample_rate_hz"),
           "ir":raw["ir"],"red":raw["red"],"gap_detected":raw.get("gap_detected",False),
           "object_temp":message.get("object_temp"),"ambient_temp":message.get("ambient_temp"),
           "temperature_at_ms":message.get("temperature_read_ms")}
        if not message.get("boot_id") or "window_id" not in message: raise ValueError("missing boot/window metadata")
    else:
        p=dict(message)
    device=p.get("device_id",path[1]); session=p.get("session_id")
    if device!=path[1] or not isinstance(session,str) or not IDENTIFIER.fullmatch(session):
        raise ValueError("device/topic mismatch or invalid session_id")
    ir,red=p.get("ir"),p.get("red")
    if not isinstance(ir,list) or not isinstance(red,list) or not 1<=len(ir)<=500 or len(ir)!=len(red):
        raise ValueError("IR/RED arrays must have equal length (1..500)")
    for value in ir+red: integer(value,"ADC sample",0,262143)
    count=len(ir)
    if "sample_count" in p and p["sample_count"]!=count: raise ValueError("sample_count mismatch")
    rate=finite(p.get("sample_rate_hz"),"sample_rate_hz",1,3200)
    batch=integer(p.get("batch_index"),"batch_index",1,200)
    total=integer(p.get("batch_total"),"batch_total",1,200)
    start=integer(p.get("sample_start_index"),"sample_start_index",0,100000)
    if batch>total or start!=(batch-1)*count: raise ValueError("batch order/offset mismatch")
    to=p.get("object_temp");ta=p.get("ambient_temp")
    if to is not None: finite(to,"object_temp",-70,380)
    if ta is not None: finite(ta,"ambient_temp",-40,125)
    now=now or datetime.now(timezone.utc)
    sent=p.get("sent_at_ms")
    if sent is not None: integer(sent,"sent_at_ms",0,4102444800000)
    temp_ms=p.get("temperature_at_ms")
    if temp_ms is not None: integer(temp_ms,"temperature_at_ms",0,0xFFFFFFFF)
    data={"device_id":device,"session_id":session,"batch_index":batch,"batch_total":total,
          "sample_start_index":start,"sample_count":count,"sample_rate_hz":rate,
          "ir":ir,"red":red,"object_temp":to,"ambient_temp":ta,
          "temperature_at_ms":temp_ms,"gap_detected":p.get("gap_detected") is True,
          "start_read_us":p.get("start_read_us"),"end_read_us":p.get("end_read_us")}
    identity=f"{device}|{session}|{batch}"
    # sent_at_ms may change on retransmission; do not include transport time in content hash.
    digest=hashlib.sha256(json.dumps(data,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    latency=None
    if p.get("clock_synced") is True and sent is not None:
        age=now.timestamp()*1000-sent
        if age>=0: latency=round(age,2)
    return {"_id":hashlib.sha256(identity.encode()).hexdigest(),"digest":digest,"ts":now,
            "meta":{"device_id":device},"session_id":session,"data":data,
            "e2e_ms":latency,"clock_synced":p.get("clock_synced") is True}
