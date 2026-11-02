import math
from datetime import datetime,timezone,timedelta
from model import validate


def packets():
    now=datetime.now(timezone.utc);result=[]
    for batch in range(30):
        ir=[];red=[]
        for j in range(50):
            t=(batch*50+j)/100;p=(t*1.16)%1
            wave=math.exp(-((p-.23)/.085)**2)+.22*math.exp(-((p-.5)/.12)**2)
            # Deterministic ADC-scale noise prevents an unrealistically exact flat
            # diastolic plateau after integer quantization. Still explicitly synthetic.
            noise=3*math.sin(2*math.pi*17.3*t)+2*math.cos(2*math.pi*23.1*t)
            ir.append(round(81000+1200*wave+120*math.sin(t)+noise))
            red.append(round(69000+850*wave+90*math.sin(t+.2)-.7*noise))
        result.append(validate({"device_id":"demo","session_id":"demo-15s","batch_index":batch+1,
             "batch_total":30,"sample_start_index":batch*50,"sample_rate_hz":100,
             "ir":ir,"red":red,"object_temp":round(34.1+.1*math.sin(batch/6),2),
             "ambient_temp":round(28.4+.05*math.sin(batch/7),2),"temperature_at_ms":batch//2*1000},
             "iot/demo/raw",now-timedelta(seconds=15-batch*.5)))
    return result
