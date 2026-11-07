"""Small Vietnamese Streamlit dashboard; background work belongs to collector.py."""
from datetime import datetime, timezone, timedelta
from html import escape
import json
import math
import pandas as pd
import altair as alt
import streamlit as st
from pymongo.errors import PyMongoError
from storage import MongoStore
from frames import frames
from physiology import analyze
from monitoring import Monitor, LOCAL, DAYS, local_time, DEFAULT_LIMITS
from overview_state import next_appointment, main_action
import demo
import config
from dashboard_ui import styles, icon, badge, section, empty_state, chart_heading, page_header, panel_empty

st.set_page_config(page_title="Signal Lab", layout="wide")
styles()

@st.cache_resource
def database():
    return MongoStore()


def get_monitor():
    return Monitor(database())


settings_file = config.ROOT / "data" / "thresholds.json"
def load_limits():
    try:
        return json.loads(settings_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def plot(df, key, color="#3974d5", height=220):
    if df.empty or key not in df or df[key].dropna().empty:
        st.caption("Chưa có dữ liệu")
        return
    frame = df.dropna(subset=[key]).copy()
    if "segment" not in frame:
        frame["segment"] = 0
    chart = alt.Chart(frame).mark_line(color=color, strokeWidth=1.8, clip=True).encode(
        x=alt.X("t:Q", title="Thời gian (giây)"),
        y=alt.Y(f"{key}:Q", title=None, scale=alt.Scale(zero=False)),
        detail="segment:N", order="t:Q", tooltip=[alt.Tooltip("t:Q", title="Thời gian (s)", format=".2f"), alt.Tooltip(f"{key}:Q", title=key, format=".2f")])
    rule = load_limits().get(key, {})
    if rule.get("enabled"):
        values = [float(rule[k]) for k in ("min", "max") if rule.get(k, "") != ""]
        if values:
            chart += alt.Chart(pd.DataFrame({"v": values})).mark_rule(strokeDash=[4, 4], color="#888888").encode(y="v:Q")
    chart = chart.properties(height=height).configure_view(stroke=None).configure_axis(
        labelFont="Segoe UI", titleFont="Segoe UI", labelFontSize=11,
        titleFontSize=11, titleFontWeight="normal", labelColor="#8190a5", titleColor="#8190a5",
        gridColor="#edf1f7", domain=False, ticks=False, labelPadding=8, titlePadding=14,
    ).configure(background="#ffffff")
    st.altair_chart(chart, width="stretch", theme=None)


with st.sidebar:
    st.markdown(f'<div class="sl-brand"><span class="sl-brand-mark">{icon("pulse", 25)}</span><div><strong>Signal Lab</strong><small>Hệ thống theo dõi chỉ số</small></div></div><div class="sl-eyebrow">NGUỒN & PHIÊN ĐO</div>', unsafe_allow_html=True)
    mode = st.radio("Nguồn dữ liệu", ["Minh họa", "MongoDB"])
    hours = st.selectbox("Khoảng thời gian", [1, 6, 24, 168], index=2, format_func=lambda x: f"{x} giờ", disabled=mode == "Minh họa")
    if mode == "Minh họa":
        st.caption("Không áp dụng cho phiên minh họa cố định.")
    device = session = None
    connection_error = None
    devices = []
    if mode == "MongoDB":
        try:
            if st.session_state.get("mongo_connection_failed"):
                raise ValueError("Connection retry requested by user")
            with st.spinner("Đang kết nối MongoDB…"):
                devices = database().devices()
            if devices:
                device = st.selectbox("Thiết bị", devices)
                sessions = database().sessions(device, hours)
                session_labels = {s["_id"]: f"{local_time(s['ts'])} · {s['_id']}" for s in sessions}
                if sessions:
                    session = st.selectbox("Phiên đo", list(session_labels), format_func=lambda x: session_labels[x])
                else:
                    st.caption("Chưa có phiên trong khoảng đã chọn.")
            else:
                st.caption("Chưa có thiết bị gửi dữ liệu.")
        except (PyMongoError, ValueError):
            st.session_state["mongo_connection_failed"] = True
            connection_error = "Không kết nối được MongoDB. Kiểm tra cấu hình .env và kết nối mạng."
        if connection_error and st.button("Thử kết nối lại"):
            st.session_state.pop("mongo_connection_failed", None)
            st.rerun()
    auto = st.toggle("Tự cập nhật", value=True)
    st.markdown('<div class="sl-sidebar-footer">ESP32 · MAX30102 · GY-906<br>Giờ Việt Nam · UTC+7</div>', unsafe_allow_html=True)

page_header("Dữ liệu minh họa" if mode == "Minh họa" else "Nguồn dữ liệu · MongoDB",
            datetime.now(LOCAL).strftime("%d/%m/%Y"))
if connection_error:
    st.error(connection_error)
    st.caption("Đã dừng tự thử kết nối. Bấm Thử kết nối lại trong thanh bên khi cơ sở dữ liệu sẵn sàng.")

refresh_enabled = auto and not connection_error

overview, schedules_tab, notifications_tab, data_tab = st.tabs(["Tổng quan", "Lịch đo", "Thông báo", "Dữ liệu"])


def read_session():
    packets = demo.packets() if mode == "Minh họa" else database().packets(device, session) if session and not connection_error else []
    samples, temps, info = frames(packets)
    result = analyze(samples, temps, info) if not samples.empty else None
    return packets, samples, temps, info, result


def load_overview_context():
    context = {"next": None, "current": None, "notices": [], "unread_count": 0, "error": False}
    if mode == "Minh họa" or connection_error:
        context["error"] = bool(connection_error)
        return context
    now = datetime.now(timezone.utc)
    scope = {"device_id": device} if device else {}
    try:
        monitor = get_monitor()
        schedules = list(monitor.db.schedules.find({**scope, "enabled": True}))
        context["next"] = next_appointment(schedules, now)
        enabled_ids = [row["_id"] for row in schedules]
        context["current"] = monitor.db.occurrences.find_one({**scope,
            "schedule_id": {"$in": enabled_ids}, "status": {"$in": ["due", "receiving", "poor"]},
            "due_at": {"$lte": now}, "deadline": {"$gte": now}}, sort=[("due_at", 1)])
        unread = {**scope, "read": False}
        context["unread_count"] = monitor.db.notifications.count_documents(unread)
        context["notices"] = list(monitor.db.notifications.find(unread).sort("created_at", -1).limit(2))
    except (PyMongoError, ValueError):
        context["error"] = True
    return context


def overview_planning(context):
    planning, notices = st.columns(2, gap="large")
    with planning:
        with st.container(key="overview_schedule"):
            section("Lịch đo tiếp theo", symbol="calendar")
            appointment = context["next"]
            if mode == "Minh họa":
                panel_empty("Chưa sử dụng lịch đo thật", "Chọn MongoDB để xem lịch của thiết bị.", "calendar")
            elif context["error"]:
                st.caption("Chưa tải được lịch đo. Thử lại khi kết nối ổn định.")
            elif appointment:
                due = appointment["due_at"].astimezone(LOCAL)
                st.markdown(f'<div class="sl-next-time">{due.strftime("%H:%M")}</div>', unsafe_allow_html=True)
                st.caption(DAYS[due.weekday()] + " · " + due.strftime("%d/%m/%Y") + " · " + appointment["device_id"])
                st.caption("Thay đổi trong tab Lịch đo.")
            else:
                panel_empty("Chưa có lịch sắp tới", "Thiết lập giờ đo hằng tuần trong tab Lịch đo.", "calendar")
    with notices:
        with st.container(key="overview_notices"):
            section("Thông báo cần chú ý", symbol="bell")
            if mode == "Minh họa":
                panel_empty("Chưa sử dụng thông báo thật", "Thông báo từ thiết bị sẽ xuất hiện khi dùng MongoDB.", "bell")
            elif context["error"]:
                st.caption("Chưa tải được thông báo. Thử lại khi kết nối ổn định.")
            elif not context["notices"]:
                panel_empty("Bạn đã xem hết thông báo", "Các nhắc đo và cảnh báo mới sẽ xuất hiện tại đây.", "bell")
            else:
                for notice in context["notices"]:
                    title = KIND_LABELS.get(notice["kind"], "Thông báo")
                    message = notice["message"]
                    if len(message) > 140:
                        message = message[:137] + "…"
                    st.markdown(f'<div class="sl-notice-preview"><strong>{escape(title)}</strong><small>{escape(local_time(notice["created_at"]))}</small><p>{escape(message)}</p></div>', unsafe_allow_html=True)
                st.caption(f'{context["unread_count"]} thông báo chưa đọc · Xem đầy đủ trong tab Thông báo.')


@st.fragment(run_every="2s" if refresh_enabled else None)
def show_overview():
    try:
        packets, samples, temps, info, result = read_session()
    except (PyMongoError, ValueError):
        st.error("Không tải được phiên đo từ MongoDB.")
        return
    context = load_overview_context()
    tone, title, description = main_action(result, info, context)
    if mode == "Minh họa":
        title = "Bạn đang xem dữ liệu minh họa"
        description = "Các chỉ số bên dưới là mô phỏng. Chọn MongoDB để theo dõi thiết bị và lịch đo thật."
        tone = "neutral"
    st.markdown(f'<div class="sl-action {tone}"><span class="sl-action-mark">{icon("pulse", 20)}</span><div><strong>{escape(title)}</strong><p>{escape(description)}</p></div></div>', unsafe_allow_html=True)
    times = [p["ts"] for p in packets if isinstance(p.get("ts"), datetime)]
    section("Kết quả đo", (device or ("Thiết bị mô phỏng" if mode == "Minh họa" else "Chưa có thiết bị")) + (" · Nhận lúc " + local_time(max(times)) if times else " · Chưa có phiên đo"))
    limits = DEFAULT_LIMITS if mode == "Minh họa" or connection_error else None
    if limits is None:
        try:
            limits = get_monitor().limits()
        except (PyMongoError, ValueError):
            st.caption("Chưa tải được ngưỡng cảnh báo đã cấu hình.")
            limits = {}
    with st.container(key="overview_results"):
        columns = st.columns(3)
        for col, channel, label, unit in [(columns[0], "bpm", "Nhịp mạch ước tính", "bpm"), (columns[1], "spo2", "SpO₂ ước tính", "%")]:
            valid = result is not None and result[channel + "_valid"]
            with col:
                with st.container(key="metric_" + channel):
                    symbol = "pulse" if channel == "bpm" else "oxygen"
                    st.markdown(f'<div class="sl-reading-top"><span class="sl-reading-icon {symbol}">{icon(symbol, 23)}</span><span class="sl-channel-label">{"NHỊP MẠCH" if channel == "bpm" else "OXY MÁU"}</span></div>', unsafe_allow_html=True)
                    st.metric(label, f"{result[channel]:.1f} {unit}" if valid else "—")
                    rule = limits.get(channel, {})
                    if valid and rule.get("enabled"):
                        value = result[channel]
                        if value < rule["low"] or value > rule["high"]:
                            direction = "Thấp hơn" if value < rule["low"] else "Cao hơn"
                            bound = rule["low"] if value < rule["low"] else rule["high"]
                            st.warning(f"{direction} ngưỡng tham khảo {bound:g} {unit}.")
                            if channel == "spo2":
                                st.caption("SpO₂ chưa hiệu chuẩn; cần kiểm chứng bằng thiết bị đo đáng tin cậy.")
                    if not valid and result:
                        st.caption(" ".join(result["reasons"]))
                    st.markdown(f'<div class="sl-reading-footer">{"Ước tính từ phiên đo" if valid else "Chưa có kết quả"}</div>', unsafe_allow_html=True)
        temp = result["temperature"]["object"] if result else {"value": None, "count": 0, "stable": False}
        with columns[2]:
            with st.container(key="metric_temp"):
                st.markdown(f'<div class="sl-reading-top"><span class="sl-reading-icon temperature">{icon("temperature", 23)}</span><span class="sl-channel-label">NHIỆT ĐỘ</span></div>', unsafe_allow_html=True)
                st.metric("Nhiệt độ bề mặt", f"{temp['value']:.2f} °C" if temp["value"] is not None else "—")
                note = "Chưa có kết quả" if temp["value"] is None else "Phép đo chưa ổn định" if not temp["stable"] else "Trung vị các lần đọc"
                st.markdown(f'<div class="sl-reading-footer">{note}</div>', unsafe_allow_html=True)
                rule = limits.get("object_temp", {})
                if temp["stable"] and temp["value"] is not None and rule.get("enabled"):
                    if temp["value"] < rule["low"] or temp["value"] > rule["high"]:
                        st.warning(f"Ngoài ngưỡng nhiệt độ bề mặt {rule['low']:g}–{rule['high']:g} °C.")
    st.caption("SpO₂ chưa hiệu chuẩn. Nhiệt độ là nhiệt độ bề mặt. Chưa có kết luận y khoa.")
    overview_planning(context)
    if result is None:
        return
    with st.expander("Biểu đồ và chi tiết phiên đo"):
        st.caption(f"Phiên: {session or 'Minh họa'}")
        st.caption(f"{info['count']:,}/{info['expected']:,} cặp IR/RED · {info['rate']:g} Hz · {len(packets)} gói")
        for warning in info["warnings"]:
            st.write(warning)
        for reason in result["reasons"]:
            st.write(reason)
        filtered = bool(result["curve"])
        chart = pd.DataFrame(result["curve"]) if filtered else samples
        left, right = st.columns(2)
        with left:
            chart_heading("Tín hiệu IR", "Sau lọc" if filtered else "Dữ liệu thô")
            plot(chart, "ir_ac" if filtered else "ir")
        with right:
            chart_heading("Tín hiệu RED", "Sau lọc" if filtered else "Dữ liệu thô", "#7a75c5")
            plot(chart, "red_ac" if filtered else "red", "#7a75c5")
        left, right = st.columns(2)
        with left:
            st.caption("Nhiệt độ vật thể")
            plot(temps, "object_temp", height=170)
        with right:
            st.caption("Nhiệt độ môi trường")
            plot(temps, "ambient_temp", height=170)
        for part in result["summary"]:
            st.write(part)


def schedule_panel():
    section("Lịch đo", "Thiết lập giờ nhắc và các ngày đo lặp lại cho từng thiết bị.")
    if mode != "MongoDB":
        empty_state("Chưa kết nối lịch đo", "Chọn nguồn MongoDB trong thanh bên để tạo lịch và đồng bộ nhắc đo với ESP32.", "calendar")
        return
    if connection_error:
        st.error("Không đọc hoặc lưu được lịch vào MongoDB.")
        return
    try:
        monitor = get_monitor()
        rows = list(monitor.db.schedules.find().sort("created_at", -1))
        st.markdown(badge(f"{sum(r['enabled'] for r in rows)} lịch đang bật", "blue") + " " + badge(f"{len(rows)} lịch đã tạo"), unsafe_allow_html=True)
        st.caption("Lịch chạy trong collector, kể cả khi đóng web. ESP32 phải được nạp firmware chờ online và có kết nối MQTT.")
        selected = st.selectbox("Chỉnh sửa lịch", [None] + [r["_id"] for r in rows],
            key="schedule_selection", format_func=lambda x: "Thêm lịch mới" if x is None else next(f"{r['device_id']} · {r['hour']}" for r in rows if r["_id"] == x))
        current = next((r for r in rows if r["_id"] == selected), {})
        with st.form("schedule_" + str(selected)):
            st.markdown("**Chỉnh sửa lịch**" if selected else "**Tạo lịch đo mới**")
            first, second = st.columns(2)
            target = first.text_input("Mã thiết bị", value=current.get("device_id", device or "esp32-01"))
            hour = second.time_input("Giờ đo", value=datetime.strptime(current.get("hour", "08:00"), "%H:%M").time(), step=60)
            weekdays = st.multiselect("Ngày lặp lại", list(range(7)), default=current.get("weekdays", list(range(7))), format_func=lambda x: DAYS[x])
            grace = st.number_input("Khoảng chờ trước khi coi là bỏ lịch (phút)", min_value=1, max_value=1440, value=current.get("grace_minutes", 30))
            enabled = st.checkbox("Bật lịch", value=current.get("enabled", True))
            save = st.form_submit_button("Lưu lịch", type="primary")
        if save:
            monitor.save_schedule(target.strip(), hour.strftime("%H:%M"), weekdays, int(grace), enabled, selected)
            st.success("Đã lưu. Lịch áp dụng cho các giờ hẹn tiếp theo.")
            st.rerun()
        if selected and st.checkbox("Tôi muốn xóa lịch đang chọn"):
            if st.button("Xóa lịch"):
                monitor.delete_schedule(selected)
                st.rerun()
        if rows:
            section("Danh sách lịch", "Giờ hẹn được hiển thị theo múi giờ Việt Nam, UTC+7.")
            st.dataframe(pd.DataFrame([{"Thiết bị": r["device_id"], "Giờ đo": r["hour"],
                "Ngày": ", ".join(DAYS[d] for d in r["weekdays"]), "Chờ (phút)": r["grace_minutes"],
                "Trạng thái": "Bật" if r["enabled"] else "Tắt"} for r in rows]), hide_index=True, width="stretch")
        st.caption("Khớp lịch bằng giờ máy chủ nhận gói đầu tiên trong khoảng giờ hẹn đến hết thời gian chờ. Firmware chưa gửi giờ đo tuyệt đối; phiên lưu offline rồi gửi lại có thể được khớp theo giờ gửi lại.")
        st.caption("Sửa hoặc tắt lịch sẽ hủy các lệnh nhắc đang chờ của lịch đó, giữ lịch sử cũ.")
    except ValueError as exc:
        st.error(str(exc))
    except PyMongoError:
        st.error("Không đọc hoặc lưu được lịch vào MongoDB.")


STATE_LABELS = {"due": "Chưa đo — đến giờ", "receiving": "Đang nhận dữ liệu", "success": "Đo thành công",
                "poor": "Đã đo, cần đo lại", "missed": "Bỏ lịch đo", "cancelled": "Đã hủy"}
MQTT_LABELS = {"pending": "Chờ gửi", "published": "Broker đã nhận; chờ ESP32", "confirmed": "ESP32 đã xác nhận",
               "expired": "Hết hạn; chưa có xác nhận", "cancelled": "Đã hủy nhắc", "not_required": "Chỉ thông báo trên web"}
KIND_LABELS = {"measurement_due": "Đến giờ đo", "measurement_missed": "Bỏ lịch đo", "threshold": "Vượt ngưỡng"}

@st.fragment(run_every="5s" if refresh_enabled else None)
def notifications_panel():
    section("Trung tâm thông báo", "Theo dõi nhắc đo, bỏ lịch và các chỉ số nằm ngoài ngưỡng cấu hình.")
    if mode != "MongoDB":
        empty_state("Chưa có thông báo từ thiết bị", "Chuyển sang MongoDB để xem lịch sử thông báo và xác nhận nhận lệnh từ ESP32.", "bell")
        return
    if connection_error:
        st.error("Không đọc được thông báo từ MongoDB.")
        return
    try:
        monitor = get_monitor()
        heartbeat = monitor.db.monitor_state.find_one({"_id": "worker"})
        if not heartbeat or datetime.now(timezone.utc) - heartbeat["heartbeat"] > timedelta(seconds=90):
            st.warning("Collector chưa chạy hoặc đã ngừng kiểm tra lịch. Chạy run_collector.bat để nhận nhắc và cảnh báo.")
        else:
            st.caption("Collector kiểm tra gần nhất: " + local_time(heartbeat["heartbeat"]))
        st.caption("Thiết bị: " + device if device else "Tất cả thiết bị")
        only_unread = st.checkbox("Chỉ hiện chưa đọc")
        query = {"read": False} if only_unread else {}
        if device:
            query["device_id"] = device
        rows = list(monitor.db.notifications.find(query).sort("created_at", -1).limit(100))
        if not rows:
            empty_state("Không có thông báo" if not only_unread else "Đã đọc hết thông báo", "Thông báo mới sẽ xuất hiện tại đây khi đến giờ đo, bỏ lịch hoặc có chỉ số vượt ngưỡng.", "bell")
        for row in rows:
            with st.container(border=True):
                title = KIND_LABELS.get(row['kind'], row['kind'])
                tone = "amber" if row["kind"] in ("threshold", "measurement_missed") else "blue"
                st.markdown(f'<div class="sl-notice-top"><strong>{escape(title)} · {escape(row["device_id"])}</strong>{badge("Đã đọc" if row["read"] else "Chưa đọc", "neutral" if row["read"] else tone)}</div>', unsafe_allow_html=True)
                st.text(row["message"])
                st.caption(local_time(row["created_at"]) + " · " + ("Đã đọc" if row["read"] else "Chưa đọc"))
                st.caption("Gửi MQTT: " + MQTT_LABELS.get(row["mqtt_status"], row["mqtt_status"]))
                if row.get("published_at"):
                    st.caption("Broker xác nhận: " + local_time(row["published_at"]))
                st.caption("ESP32 xác nhận: " + local_time(row.get("confirmed_at")))
                if not row["read"] and st.button("Đánh dấu đã đọc", key="read_" + row["_id"]):
                    monitor.db.notifications.update_one({"_id": row["_id"]}, {"$set": {"read": True}})
                    st.rerun()
        section("Kết quả lịch hẹn", "Đối chiếu các phiên đã nhận với từng khung giờ hẹn.")
        occurrences = list(monitor.db.occurrences.find({"device_id": device} if device else {}).sort("due_at", -1).limit(50))
        if occurrences:
            st.dataframe(pd.DataFrame([{"Thiết bị": r["device_id"], "Giờ hẹn": local_time(r["due_at"]),
                "Hạn đo": local_time(r["deadline"]), "Trạng thái": STATE_LABELS.get(r["status"], r["status"])} for r in occurrences]), hide_index=True, width="stretch")
        else:
            st.caption("Chưa đến giờ hẹn nào.")
        st.caption("ACK của ESP32 xác nhận đã nhận lệnh nhắc, không xác nhận người dùng đã đo. Nhắc hết hạn sẽ không gửi tiếp.")
    except (PyMongoError, ValueError):
        st.error("Không đọc được thông báo từ MongoDB.")


def alert_settings():
    with st.expander("Cấu hình cảnh báo vượt ngưỡng"):
        if mode != "MongoDB":
            st.caption("Chọn MongoDB để lưu cấu hình cảnh báo thật.")
            return
        if connection_error:
            st.caption("Chưa có kết nối để đọc hoặc lưu ngưỡng cảnh báo.")
            return
        try:
            monitor = get_monitor()
            limits = monitor.limits()
            st.caption("Chỉ áp dụng cho phiên hoàn tất được xử lý sau khi lưu. Không thay đổi thuật toán BPM/SpO₂. Nhiệt độ bề mặt mặc định tắt cảnh báo.")
            with st.form("alert_limits"):
                updated = {}
                for key, label in [("bpm", "BPM"), ("spo2", "SpO₂ (%)"), ("object_temp", "Nhiệt độ bề mặt (°C)")]:
                    rule = limits[key]
                    enabled = st.checkbox("Cảnh báo " + label, value=rule["enabled"])
                    left, right = st.columns(2)
                    low = left.number_input(label + " — tối thiểu", value=float(rule["low"]), key=key+"low")
                    high = right.number_input(label + " — tối đa", value=float(rule["high"]), key=key+"high")
                    updated[key] = {"enabled": enabled, "low": low, "high": high}
                save = st.form_submit_button("Lưu ngưỡng cảnh báo", type="primary")
            if save:
                if any(not math.isfinite(r["low"]) or not math.isfinite(r["high"]) or r["low"] >= r["high"] for r in updated.values()):
                    st.error("Ngưỡng dưới phải nhỏ hơn ngưỡng trên; các giá trị phải hữu hạn.")
                else:
                    monitor.db.monitor_settings.replace_one({"_id": "limits"}, {"_id": "limits", "values": updated}, upsert=True)
                    st.success("Đã lưu ngưỡng cảnh báo.")
        except (PyMongoError, ValueError):
            st.error("Không đọc hoặc lưu được ngưỡng cảnh báo.")


def raw_plot_settings():
    with st.expander("Cấu hình đường ngưỡng đồ thị thô"):
        limits = load_limits()
        st.caption("Các đường này chỉ để đối chiếu đồ thị, không thay đổi thuật toán hay cấu hình cảnh báo.")
        if st.session_state.pop("raw_limits_saved", False):
            st.success("Đã lưu đường ngưỡng.")
        with st.form("raw_limits"):
            updated = {}
            for key, label in [("ir", "IR"), ("red", "RED"), ("object_temp", "Vật thể °C"), ("ambient_temp", "Môi trường °C")]:
                old = limits.get(key, {})
                enabled = st.checkbox(label, value=old.get("enabled", False), key="raw_limit_"+key+"_enabled")
                left, right = st.columns(2)
                low = left.text_input(label + " — dưới", str(old.get("min", "")), key="raw_limit_"+key+"_min")
                high = right.text_input(label + " — trên", str(old.get("max", "")), key="raw_limit_"+key+"_max")
                updated[key] = {"enabled": enabled, "min": low, "max": high}
            save = st.form_submit_button("Lưu đường ngưỡng")
        if save:
            try:
                for item in updated.values():
                    low = float(item["min"]) if item["min"] else None
                    high = float(item["max"]) if item["max"] else None
                    if any(v is not None and not math.isfinite(v) for v in (low, high)) or (item["enabled"] and low is None and high is None) or (low is not None and high is not None and low >= high):
                        raise ValueError()
                settings_file.parent.mkdir(exist_ok=True)
                temporary = settings_file.with_suffix(".tmp")
                temporary.write_text(json.dumps(updated), encoding="utf-8")
                temporary.replace(settings_file)
                st.session_state["raw_limits_saved"] = True
                st.rerun()
            except (ValueError, OSError):
                st.error("Kiểm tra giới hạn dưới/trên và quyền ghi file.")


@st.fragment(run_every="2s" if refresh_enabled else None)
def show_data():
    try:
        packets, samples, temps, info, result = read_session()
        if result is None:
            empty_state("Chưa có dữ liệu để xuất", "Chọn một phiên đo để xem các mẫu IR/RED, nhiệt độ và tải dữ liệu phân tích.")
            return
        section("Dữ liệu phiên đo", "Kiểm tra mẫu gốc và xuất dữ liệu để phân tích độc lập.")
        left, right = st.columns(2)
        with left:
            chart_heading("Tín hiệu IR", "Dữ liệu thô")
            plot(samples, "ir")
        with right:
            chart_heading("Tín hiệu RED", "Dữ liệu thô", "#647987")
            plot(samples, "red", "#647987")
        st.dataframe(samples, hide_index=True, height=250, width="stretch")
        downloads = st.columns(3)
        downloads[0].download_button("CSV IR / RED", samples.to_csv(index=False).encode("utf-8-sig"), "ir-red.csv", "text/csv", width="stretch")
        downloads[1].download_button("CSV nhiệt độ", temps.to_csv(index=False).encode("utf-8-sig"), "temperature.csv", "text/csv", width="stretch")
        downloads[2].download_button("JSON phân tích", json.dumps({k: v for k, v in result.items() if k != "curve"}, ensure_ascii=False, indent=2), "analysis.json", "application/json", width="stretch")
        with st.expander("Dữ liệu tiền xử lý"):
            processed = database().packets(device, session, processed=True) if mode == "MongoDB" and session else []
            if not processed:
                st.caption("Chưa có bản tiền xử lý. Chạy preprocess.py riêng; BPM/SpO₂ vẫn được tính trực tiếp từ raw.")
            else:
                frame = pd.DataFrame(processed[0].get("frame", []))
                left, right = st.columns(2)
                with left:
                    st.caption("IR · rolling mean")
                    plot(frame, "ir_mean")
                with right:
                    st.caption("RED · rolling mean")
                    plot(frame, "red_mean")
                st.dataframe(frame, hide_index=True, height=220)
                st.dataframe(pd.DataFrame(processed[0].get("temperature_resampled", [])), hide_index=True)
    except (PyMongoError, ValueError):
        st.error("Không tải được dữ liệu phiên đo.")


with overview:
    show_overview()
with schedules_tab:
    schedule_panel()
with notifications_tab:
    notifications_panel()
    alert_settings()
with data_tab:
    show_data()
    raw_plot_settings()
