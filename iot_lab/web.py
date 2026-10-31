from pathlib import Path
import json
import pandas as pd
import altair as alt
import streamlit as st
from pymongo.errors import PyMongoError
from storage import MongoStore
from frames import frames
import demo
import config

st.set_page_config(page_title="Signal Lab",page_icon="〰",layout="wide",initial_sidebar_state="collapsed")
st.markdown("""<style>
.block-container{max-width:1250px;padding-top:2rem;padding-bottom:1rem}
h1{font-size:1.8rem!important;letter-spacing:-.04em}h3{font-size:1rem!important}
[data-testid=stMetric]{background:#fff;border:1px solid #e8ecef;border-radius:12px;padding:18px}
[data-testid=stMetricValue]{font-size:1.9rem}header[data-testid=stHeader]{background:transparent}
[data-testid=stAppViewContainer]{background:#f7f8fa}.stCaption{color:#8a929b}
[data-testid=stAppDeployButton]{display:none}
@media(max-width:768px){
div[data-testid=stHorizontalBlock]:has([data-testid=stMetric]){display:grid!important;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
div[data-testid=stHorizontalBlock]:has([data-testid=stMetric])>div{width:100%!important;min-width:0!important}
[data-testid=stMetric]{padding:12px}[data-testid=stMetricValue]{font-size:1.5rem}
}
</style>""",unsafe_allow_html=True)


@st.cache_resource
def db():return MongoStore()


settings_file=config.ROOT/"data"/"thresholds.json"
def load_limits():
    try:return json.loads(settings_file.read_text(encoding="utf-8"))
    except (OSError,ValueError):return {}


with st.sidebar:
    st.subheader("Signal Lab")
    mode=st.radio("Nguồn",["Minh họa","MongoDB"],label_visibility="collapsed")
    hours=st.selectbox("Khoảng dữ liệu",[1,6,24,168],index=2,format_func=lambda h:f"{h} giờ")
    auto=st.toggle("Tự cập nhật",value=True)
    with st.expander("Ngưỡng"):
        limits=load_limits()
        with st.form("limits"):
            updated={}
            for key,label in (("ir","IR"),("red","RED"),("object_temp","Vật thể °C"),("ambient_temp","Môi trường °C")):
                old=limits.get(key,{})
                on=st.checkbox(label,value=old.get("enabled",False),key=key+"on")
                a,b=st.columns(2)
                low=a.text_input("Tối thiểu",str(old.get("min","")),key=key+"lo")
                high=b.text_input("Tối đa",str(old.get("max","")),key=key+"hi")
                updated[key]={"enabled":on,"min":low,"max":high}
            if st.form_submit_button("Lưu",width="stretch"):
                try:
                    for item in updated.values():
                        low=float(item["min"]) if item["min"] else None
                        high=float(item["max"]) if item["max"] else None
                        import math
                        if any(v is not None and not math.isfinite(v) for v in (low,high)):raise ValueError()
                        if item["enabled"] and low is None and high is None:raise ValueError()
                        if low is not None and high is not None and low>=high:raise ValueError()
                    settings_file.parent.mkdir(exist_ok=True)
                    temporary=settings_file.with_suffix(".tmp")
                    temporary.write_text(json.dumps(updated),encoding="utf-8");temporary.replace(settings_file)
                    st.success("Đã lưu")
                except (ValueError,OSError):st.error("Kiểm tra giới hạn dưới / trên.")

limits=load_limits()
title,status=st.columns([4,1])
title.title("Signal Lab")
status.caption("MINH HỌA" if mode=="Minh họa" else "MQTT → MONGODB")

selected_device=None;selected_session=None
if mode=="MongoDB":
    try:
        devices=db().devices()
        if not devices:st.info("Chưa có dữ liệu. Chạy collector và bật ESP32.");st.stop()
        a,b=st.columns([1,3])
        selected_device=a.selectbox("Thiết bị",devices,label_visibility="collapsed")
        sessions=db().sessions(selected_device,hours)
        if not sessions:st.info("Không có phiên trong khoảng đã chọn.");st.stop()
        selected_session=b.selectbox("Phiên",[s["_id"] for s in sessions],label_visibility="collapsed")
    except PyMongoError:
        st.error("Chưa kết nối MongoDB. Kiểm tra dịch vụ MongoDB và file .env.");st.stop()
    except ValueError:
        st.error("Kiểm tra MONGO_URI trong iot_lab/.env rồi khởi động lại web.");st.stop()


def plot(df,key,color,height=200):
    if df.empty or key not in df or df[key].dropna().empty:
        st.caption("Chưa có dữ liệu");return
    frame=df.dropna(subset=[key]).copy()
    if "segment" not in frame:frame["segment"]=0
    chart=alt.Chart(frame).mark_line(color=color,strokeWidth=1.5).encode(
        x=alt.X("t:Q",title="Giây"),y=alt.Y(f"{key}:Q",title=None,scale=alt.Scale(zero=False)),
        detail="segment:N",order="t:Q",tooltip=[alt.Tooltip("t:Q",title="Giây",format=".2f"),alt.Tooltip(f"{key}:Q",title=key,format=".2f")])
    limit=limits.get(key,{})
    if limit.get("enabled"):
        values=[float(limit[k]) for k in ("min","max") if limit.get(k,"")!=""]
        if values:
            rules=alt.Chart(pd.DataFrame({"v":values})).mark_rule(color=color,strokeDash=[5,5],opacity=.5).encode(y="v:Q")
            chart=chart+rules
    st.altair_chart(chart.properties(height=height),width="stretch")


@st.fragment(run_every="2s" if auto else None)
def dashboard():
    try:packets=demo.packets() if mode=="Minh họa" else db().packets(selected_device,selected_session)
    except PyMongoError:st.error("Mất kết nối MongoDB");return
    samples,temps,info=frames(packets)
    if samples.empty:st.info("Đang chờ mẫu…");return
    a,b,c,d=st.columns(4)
    a.metric("IR",f'{samples.iloc[-1]["ir"]:,.0f}')
    b.metric("RED",f'{samples.iloc[-1]["red"]:,.0f}')
    to=temps["object_temp"].dropna() if not temps.empty else pd.Series(dtype=float)
    c.metric("Vật thể",f"{to.iloc[-1]:.2f} °C" if len(to) else "—")
    d.metric(f'Mẫu / {info["expected"]:,}',f'{info["count"]:,}')
    if info["warnings"]:st.warning(" · ".join(info["warnings"]))
    raw_tab,processed_tab=st.tabs(["Dữ liệu thô","Tiền xử lý"])
    with raw_tab:
        a,b=st.columns(2)
        with a:st.subheader("IR");plot(samples,"ir","#e47b58")
        with b:st.subheader("RED");plot(samples,"red","#8d80c4")
        st.subheader("Nhiệt độ")
        a,b=st.columns(2)
        with a:st.caption("Vật thể (°C)");plot(temps,"object_temp","#3f9f91",150)
        with b:st.caption("Môi trường (°C)");plot(temps,"ambient_temp","#8b9da8",150)
        st.caption(f'{info["rate"]:g} Hz · {len(packets)} gói · {"Đủ mẫu" if info["complete"] else "Chưa đủ mẫu"} · Ngưỡng tùy chỉnh trong thanh bên')
    with processed_tab:
        if mode=="Minh họa":st.caption("Chỉ hiển thị kết quả khi chạy preprocess.py trên dữ liệu đã lưu.")
        else:
            try:processed=db().packets(selected_device,selected_session,processed=True)
            except PyMongoError:processed=[]
            if not processed:st.caption("Chưa xử lý. Dữ liệu gốc được giữ nguyên.")
            else:
                p=processed[0];f=pd.DataFrame(p.get("frame",[]))
                st.caption("Rolling mean · delta · MinMax · IQR chỉ đánh dấu")
                a,b=st.columns(2)
                with a:st.subheader("IR · rolling mean");plot(f,"ir_mean","#e47b58")
                with b:st.subheader("RED · rolling mean");plot(f,"red_mean","#8d80c4")
                st.dataframe(pd.DataFrame(p.get("temperature_resampled",[])),hide_index=True)
    with st.expander("Bảng & tải dữ liệu"):
        st.dataframe(samples,hide_index=True,height=220)
        st.download_button("CSV IR / RED",samples.to_csv(index=False).encode("utf-8-sig"),"ir-red.csv","text/csv")
        st.download_button("CSV nhiệt độ",temps.to_csv(index=False).encode("utf-8-sig"),"temperature.csv","text/csv")
        latency=[p.get("e2e_ms") for p in packets if p.get("e2e_ms") is not None]
        st.caption(f"Publish → Python: {pd.Series(latency).median():.0f} ms (median)" if latency else "Độ trễ đầu-cuối: chưa đo được (ESP32 chưa đồng bộ thời gian UTC).")


dashboard()
