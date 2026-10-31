"""Optional lab preprocessing, invoked explicitly. Does not infer BPM/SpO2/disease."""
import argparse
import hashlib
from datetime import datetime,timezone,timedelta
import numpy as np
import pandas as pd
from sklearn.preprocessing import MinMaxScaler
from frames import frames
from storage import MongoStore
import config

VERSION="lab-preprocess-v1"


def transform(raw,temps):
    frame=raw.copy()
    if frame.empty:raise ValueError("No samples")
    for key in ("ir","red"):
        values=pd.to_numeric(frame[key],errors="coerce")
        q1,q3=values.quantile([.25,.75]);iqr=q3-q1
        # PPG peaks may be physiological: flag outliers, never silently remove them.
        frame[key+"_iqr_flag"]=((values<q1-1.5*iqr)|(values>q3+1.5*iqr)) if iqr>0 else False
        frame[key+"_mean"]=frame.groupby("segment")[key].transform(lambda s:s.rolling(5,min_periods=1).mean())
        frame[key+"_delta"]=frame.groupby("segment")[key].diff()
        frame[key+"_scaled"]=MinMaxScaler().fit_transform(values.to_numpy().reshape(-1,1)).ravel()
    temperature=[]
    if not temps.empty:
        t=temps.copy();t.index=pd.to_timedelta(t["t"],unit="s")
        out=t[["object_temp","ambient_temp"]].resample("1s").mean()
        for key in list(out.columns):
            missing=out[key].isna()
            run_length=missing.groupby((missing!=missing.shift()).cumsum()).transform("sum")
            filled=out[key].interpolate(limit=1,limit_area="inside")
            out[key]=filled.mask(missing & (run_length>1))
            out[key+"_missing"]=missing
        out["t"]=out.index.total_seconds()
        temperature=out.reset_index(drop=True).replace({np.nan:None}).to_dict("records")
    return frame.replace({np.nan:None}).to_dict("records"),temperature


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--device",required=True);parser.add_argument("--session",required=True)
    args=parser.parse_args();store=MongoStore();store.setup()
    packets=store.packets(args.device,args.session)
    samples,temps,quality=frames(packets)
    processed,temperature=transform(samples,temps)
    key=hashlib.sha256(f"{args.device}|{args.session}|{VERSION}".encode()).hexdigest()
    input_hash=hashlib.sha256("|".join(p["digest"] for p in packets).encode()).hexdigest()
    now=datetime.now(timezone.utc)
    old=store.db.processed_registry.find_one({"_id":key})
    if old and old.get("input_hash")==input_hash:
        print("Same input already processed");return
    doc={"batch_id":key,"ts":now,"meta":{"device_id":args.device},"session_id":args.session,
         "version":VERSION,"input_hash":input_hash,"frame":processed,"temperature_resampled":temperature,
         "quality":quality,"data":{"sample_start_index":0}}
    store.db.processed_timeseries.insert_one(doc)
    store.db.processed_registry.replace_one({"_id":key},{"_id":key,"input_hash":input_hash,
        "expires_at":now+timedelta(days=config.RETENTION_DAYS)},upsert=True)
    print(f"Saved {len(processed)} processed samples; raw unchanged")


if __name__=="__main__":main()
