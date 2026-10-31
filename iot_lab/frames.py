import pandas as pd


def frames(packets):
    """Expand arrays for plotting; leave gaps visible and do not invent samples."""
    rows=[];temps=[];seen=set();temp_seen=set();segment=0;previous_end=None;warnings=[]
    ordered=sorted(packets,key=lambda r:r["data"]["sample_start_index"])
    rates={r["data"]["sample_rate_hz"] for r in ordered}
    if len(rates)>1:warnings.append("Tốc độ mẫu thay đổi")
    for r in ordered:
        p=r["data"];start=p["sample_start_index"];hz=p["sample_rate_hz"]
        if p.get("gap_detected") or (previous_end is not None and previous_end!=start):
            segment+=1;warnings.append("Thiếu mẫu / gián đoạn")
        for j,(ir,red) in enumerate(zip(p["ir"],p["red"])):
            idx=start+j
            if idx in seen:warnings.append("Chồng mẫu");continue
            seen.add(idx);rows.append({"index":idx,"t":idx/hz,"ir":ir,"red":red,"segment":segment})
        mark=p.get("temperature_at_ms")
        if mark is None:mark=r["ts"].isoformat()
        if mark not in temp_seen and (p.get("object_temp") is not None or p.get("ambient_temp") is not None):
            temps.append({"t":start/hz,"object_temp":p.get("object_temp"),"ambient_temp":p.get("ambient_temp"),"temperature_at_ms":mark})
            temp_seen.add(mark)
        previous_end=start+len(p["ir"])
    expected=ordered[0]["data"]["batch_total"]*ordered[0]["data"]["sample_count"] if ordered else 0
    return (pd.DataFrame(rows,columns=["index","t","ir","red","segment"]),
            pd.DataFrame(temps,columns=["t","object_temp","ambient_temp","temperature_at_ms"]),
            {"expected":expected,"count":len(rows),"complete":seen==set(range(expected)) and expected>0 and not warnings,
             "rate":next(iter(rates),0),"warnings":sorted(set(warnings))})
