from pathlib import Path
from html import escape
from datetime import datetime
import json
import pandas as pd
import altair as alt
import streamlit as st
from pymongo.errors import PyMongoError
from storage import MongoStore
from frames import frames
from physiology import analyze, pulse_reference, oxygen_reference
import demo
import config

st.set_page_config(page_title="Signal Lab",page_icon="〰",layout="wide",initial_sidebar_state="expanded")
st.markdown("""<style>
.block-container{max-width:1250px;padding-top:2rem;padding-bottom:1rem}
h1{font-size:1.8rem!important;letter-spacing:-.04em}h3{font-size:1rem!important}
[data-testid=stMetric]{background:#fff;border:1px solid #e8ecef;border-radius:12px;padding:18px}
[data-testid=stMetricValue]{font-size:1.9rem}header[data-testid=stHeader]{background:transparent}
[data-testid=stAppViewContainer]{background:#f7f8fa}.stCaption{color:#8a929b}
[data-testid=stAppDeployButton]{display:none}
.badge{display:inline-block;padding:5px 11px;border-radius:20px;font-size:.8rem;font-weight:600;margin:2px 4px 4px 0}
.badge.neutral{background:#e9eef4;color:#45566e}.badge.good{background:#e1f3e9;color:#216345}
.badge.warn{background:#fff0cf;color:#805600}.badge.danger{background:#ffe5e3;color:#a82b30}
[data-testid=stMetric]{min-height:115px}[data-testid=stVerticalBlockBorderWrapper]{border-radius:16px}

@media(max-width:768px){
div[data-testid=stHorizontalBlock]:has([data-testid=stMetric]){display:grid!important;grid-template-columns:repeat(1,minmax(0,1fr));gap:12px}
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
    with st.expander("Ngưỡng đồ thị raw"):
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
title.caption("Nhịp mạch · SpO₂ ước tính · Nhiệt độ bề mặt")
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


def badge(label, kind="neutral"):
    st.markdown(f'<span class="badge {kind}">{escape(label)}</span>', unsafe_allow_html=True)


def reference_badge(level):
    if level is None:
        badge("Chưa đủ chất lượng")
    else:
        badge(level + " · tham khảo", {"Bình thường":"good", "Cảnh báo":"warn", "Nguy hiểm":"danger"}[level])


@st.fragment(run_every="2s" if auto else None)
def dashboard():
    try:
        packets = demo.packets() if mode=="Minh họa" else db().packets(selected_device,selected_session)
    except PyMongoError:
        st.error("Mất kết nối MongoDB");return
    samples,temps,info=frames(packets)
    if samples.empty:
        st.info("Đang chờ mẫu…");return
    result=analyze(samples,temps,info)
    temp=result["temperature"]["object"]
    ambient=result["temperature"]["ambient"]
    if mode=="Minh họa":
        st.info("MINH HỌA — Dữ liệu mô phỏng, không phải số đo người thật.")
    st.caption(f'{info["count"]:,}/{info["expected"]:,} cặp · {info["rate"]:g} Hz · {len(packets)} gói · '
               + ("Đủ phiên" if info["complete"] else "Đang nhận / thiếu mẫu"))
    received_times=[p["ts"] for p in packets if isinstance(p.get("ts"),datetime)]
    if received_times:
        st.caption("Phiên đã lưu · nhận gần nhất: " + max(received_times).isoformat(timespec="seconds") + " (thời gian nhận, không phải lúc đang đo)")
    st.caption("Bản nghiên cứu: SpO₂ chưa hiệu chuẩn; GY-906 đo bề mặt. Các mức màu chỉ đối chiếu ngưỡng, không xác nhận sức khỏe.")
    a,b,c=st.columns(3)
    with a:
        with st.container(border=True):
            st.metric("Nhịp mạch ước tính", f'{result["bpm"]:.1f} bpm' if result["bpm_valid"] else "—")
            reference_badge(pulse_reference(result["bpm"]))
            st.caption("Từ khoảng nhịp IR, đối chiếu tự tương quan. Người lớn lúc nghỉ.")
    with b:
        with st.container(border=True):
            st.metric("SpO₂ ước tính", f'{result["spo2"]:.1f} %' if result["spo2_valid"] else "—")
            reference_badge(oxygen_reference(result["spo2"]))
            st.caption("Chưa hiệu chuẩn · Không dùng thay máy đo y tế.")
    with c:
        with st.container(border=True):
            st.metric("Nhiệt độ bề mặt", f'{temp["value"]:.2f} °C' if temp["value"] is not None else "—")
            badge("Dao động nhỏ · kỹ thuật" if temp["stable"] else "Cần kiểm tra phép đo", "neutral")
            if temp["count"]:
                st.caption(f'Trung vị {temp["count"]} lần đọc · {temp["min"]:.2f}–{temp["max"]:.2f} °C')
            else:
                st.caption("Chưa có mẫu vật thể hợp lệ.")
            st.caption("Không áp ngưỡng sốt cho nhiệt độ bề mặt.")
    with st.container(border=True):
        st.subheader("Nhận xét tổng hợp")
        badge("Chưa có kết luận y khoa")
        if result["reference_level"]:
            st.caption("Đối chiếu nhịp mạch/SpO₂: " + result["reference_level"] + " — chỉ là mức tham khảo của các ước tính.")
        else:
            st.caption("Chưa đủ hai ước tính để đối chiếu đầy đủ; không coi thiếu dữ liệu là bình thường.")
        for part in result["summary"]:
            st.write(part)
        if result["spo2_valid"] and result["spo2"] < 95:
            st.warning("SpO₂ thử nghiệm đang thấp: kiểm tra bằng thiết bị đáng tin cậy. Nhịp mạch trong khoảng tham khảo không loại trừ vấn đề oxy. Nếu khó thở rõ, đau ngực, tím tái hoặc ngất, cần hỗ trợ y tế ngay, không chờ web xác nhận.")
        else:
            st.caption("Nếu có triệu chứng đáng lo, cần hỗ trợ y tế dù số hiển thị nằm trong khoảng tham khảo. Không suy bệnh cụ thể từ ba giá trị này.")
    if info["warnings"]:
        st.warning(" · ".join(info["warnings"]))
    for reason in result["reasons"]:
        st.warning(reason)
    analysis_tab,raw_tab,processed_tab=st.tabs(["Phân tích", "Dữ liệu thô", "Tiền xử lý"])
    with analysis_tab:
        if result["curve"]:
            curve=pd.DataFrame(result["curve"])
            st.subheader("Sóng mạch đã lọc")
            plot(curve,"ir_ac","#e47b58",220)
            st.caption("IR bỏ nền và lọc 0,5–5 Hz; số đo được tính từ raw, không dùng bản MinMax. Chưa thẩm định lâm sàng.")
        else:
            st.info("Chờ đủ dữ liệu và chất lượng để phân tích waveform.")
        st.subheader("Các lần đọc nhiệt độ")
        a,b=st.columns(2)
        with a:
            st.caption("Vật thể · trung vị phiên dùng trên thẻ chỉ số")
            plot(temps,"object_temp","#3f9f91",170)
        with b:
            st.caption(f'Môi trường · trung vị {ambient["value"]:.2f} °C' if ambient["value"] is not None else "Môi trường")
            plot(temps,"ambient_temp","#8b9da8",170)
        st.caption("Trung vị không tự biến nhiệt độ bề mặt thành thân nhiệt. Min/max và IQR vẫn giữ các mẫu lệch để kiểm tra.")
        with st.expander("Chất lượng và công thức"):
            st.write("BPM = 60 / trung vị khoảng nhịp (giây), đối chiếu tự tương quan; không phải ECG.")
            st.write("R = (AC_RED / DC_RED) / (AC_IR / DC_IR). AC dùng RMS sau detrend/lọc, DC giữ từ raw.")
            st.write("SpO₂ thử nghiệm = −45,060 R² + 30,354 R + 94,845. Bộ hệ số chưa hiệu chuẩn với module và phép lọc hiện tại.")
            st.json({"method":result["method"],"version":result["version"],"quality":result["quality"],"temperature":result["temperature"]})
    with raw_tab:
        a,b=st.columns(2)
        with a:st.subheader("IR");plot(samples,"ir","#e47b58")
        with b:st.subheader("RED");plot(samples,"red","#8d80c4")
        st.caption("Dữ liệu gốc được giữ nguyên. Các ngưỡng đồ thị tùy chỉnh trong thanh bên không thay đổi mức tham khảo y khoa.")
        st.dataframe(samples,hide_index=True,height=220)
        st.download_button("CSV IR / RED",samples.to_csv(index=False).encode("utf-8-sig"),"ir-red.csv","text/csv")
        st.download_button("CSV nhiệt độ",temps.to_csv(index=False).encode("utf-8-sig"),"temperature.csv","text/csv")
        st.download_button("JSON phân tích",json.dumps({k:v for k,v in result.items() if k not in ("curve",)},ensure_ascii=False,indent=2),"analysis.json","application/json")
    with processed_tab:
        if mode=="Minh họa":
            st.caption("Chỉ hiển thị kết quả khi chạy preprocess.py trên dữ liệu đã lưu.")
        else:
            try:processed=db().packets(selected_device,selected_session,processed=True)
            except PyMongoError:processed=[]
            if not processed:st.caption("Chưa chạy script tiền xử lý riêng. Ba chỉ số nghiên cứu ở trên được tính khi xem phiên.")
            else:
                p=processed[0];f=pd.DataFrame(p.get("frame",[]))
                st.caption("Rolling mean · delta · MinMax · IQR chỉ đánh dấu")
                a,b=st.columns(2)
                with a:st.subheader("IR · rolling mean");plot(f,"ir_mean","#e47b58")
                with b:st.subheader("RED · rolling mean");plot(f,"red_mean","#8d80c4")
                st.dataframe(pd.DataFrame(p.get("temperature_resampled",[])),hide_index=True)
    with st.expander("Ba mức tham khảo và giới hạn"):
        st.markdown("**Nhịp mạch người lớn lúc nghỉ:** 60–100 bpm: Bình thường; ngoài khoảng đó: Cảnh báo; ≤40 hoặc ≥131 bpm: Nguy hiểm theo quy tắc minh họa lấy mốc lệch lớn của pulse NEWS2. Đây không phải tổng NEWS2 hay một kết luận lâm sàng.")
        st.markdown("**SpO₂:** ≥95%: Bình thường; >92 đến <95%: Cảnh báo; ≤92%: Nguy hiểm theo quy tắc minh họa, tham khảo hướng dẫn theo dõi COVID tại nhà của NHS. Nguyên mẫu chưa hiệu chuẩn nên phải xác nhận bằng thiết bị đáng tin cậy.")
        st.markdown("**Nhiệt độ:** trung vị mẫu vật thể; không phân loại sốt/hạ thân nhiệt vì chưa có phép đo thân nhiệt được hiệu chuẩn. IQR≤0,3°C và khoảng dao động≤1°C là tiêu chí ổn định kỹ thuật thử nghiệm, không phải ngưỡng sức khỏe.")
        st.markdown("Nguồn: [AHA](https://www.heart.org/en/health-topics/high-blood-pressure/the-facts-about-high-blood-pressure/all-about-heart-rate-pulse), [RCP NEWS2](https://www.rcp.ac.uk/media/a4ibkkbf/news2-final-report_0_0.pdf), [NHS](https://www.england.nhs.uk/coronavirus/wp-content/uploads/sites/52/2020/12/C1634-suspected-Coronavirus-important-information-to-keep-you-safe-at-home-V8_210422.pdf), [ADI](https://www.analog.com/en/resources/technical-articles/2022/07/16/12/29/guidelines-for-spo2-measurement--maxim-integrated.html).")
    st.caption("Phân tích phiên đã thu; không phải giám sát cấp cứu liên tục. Kết quả này không được ghi đè dữ liệu MongoDB.")


dashboard()
