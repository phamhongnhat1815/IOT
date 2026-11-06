"""Read-only presentation helpers; scheduling and measurement algorithms stay separate."""
from datetime import datetime, timedelta, timezone
from monitoring import LOCAL


def next_appointment(schedules, now):
    candidates = []
    today = now.astimezone(LOCAL).date()
    for schedule in schedules:
        if not schedule.get("enabled"):
            continue
        hour = datetime.strptime(schedule["hour"], "%H:%M").time()
        for offset in range(8):
            day = today + timedelta(days=offset)
            due = datetime.combine(day, hour, LOCAL).astimezone(timezone.utc)
            if (day.weekday() in schedule["weekdays"] and due > now
                    and due >= schedule["active_from"]):
                candidates.append({"due_at": due, "device_id": schedule["device_id"]})
                break
    return min(candidates, key=lambda item: item["due_at"]) if candidates else None


def main_action(result, info, context):
    if context.get("error"):
        return "neutral", "Chưa tải được lịch và thông báo", "Kết quả phiên đo vẫn hiển thị bên dưới. Kiểm tra kết nối rồi thử lại."
    current = context.get("current")
    if current and current["status"] == "receiving":
        return "neutral", "Đang nhận phiên đo theo lịch", "Giữ ngón tay ổn định và chờ thiết bị gửi đủ dữ liệu."
    if result is not None and not info["complete"]:
        return "neutral", "Đang nhận dữ liệu", "Giữ ngón tay ổn định và chờ phiên đo hoàn tất."
    if current and current["status"] == "due":
        return "attention", "Đã đến giờ đo", "Đặt ngón tay lên cảm biến để thực hiện lịch đo đang chờ."
    if current and current["status"] == "poor":
        return "attention", "Lần đo theo lịch cần thực hiện lại", "Phiên trước chưa đạt chất lượng. Giữ ngón tay ổn định khi đo lại."
    if result is None:
        return "neutral", "Chưa có kết quả đo", "Chọn một phiên đã lưu hoặc đặt ngón tay lên cảm biến để đo."
    if not result["bpm_valid"] or not result["spo2_valid"]:
        return "attention", "Phiên đang xem cần đo lại", "Chưa xác nhận được đủ nhịp mạch và SpO₂. Giữ ngón tay ổn định và thực hiện một phiên mới."
    if not result["temperature"]["object"]["stable"]:
        return "attention", "Cần kiểm tra lại phép đo nhiệt độ", "Nhiệt độ bề mặt chưa ổn định hoặc chưa có đủ mẫu hợp lệ."
    if context.get("unread_count"):
        return "neutral", "Có thông báo cần xem", "Kiểm tra các thông báo bên dưới; mở tab Thông báo để xem đầy đủ."
    return "neutral", "Đã có kết quả của phiên đang xem", "Bạn có thể xem chỉ số bên dưới và theo dõi lịch đo tiếp theo."
