# Lịch đo và thông báo Signal Lab

## Chạy hệ thống

1. Giữ cấu hình `.env`, `WiFiConfig.h`, `MqttCloud.h` đang hoạt động. Không cần thêm mật khẩu.
2. Khởi động lại **một** `iot_lab/run_collector.bat` để chạy worker lịch mới; không chạy nhiều collector.
3. Chạy `iot_lab/run.bat`, chọn MongoDB. Chế độ Minh họa không tạo lịch, thông báo hay lệnh MQTT thật.
4. Nạp firmware mới khi đã chuẩn bị toolchain ESP32 và kiểm tra board/partition. Không FORMAT hoặc xóa flash để cập nhật.
5. Cấp nguồn thường xuyên cho ESP32. Sau khởi động thấy `ONLINE IDLE` trong Serial Monitor 9600 baud.

Web có bốn tab: Tổng quan, Lịch đo, Thông báo, Dữ liệu. Cấu hình ngưỡng cảnh báo ở tab Thông báo; đường giới hạn đồ thị ở tab Dữ liệu. Công thức và thông số chất lượng nằm trong mục mở rộng.

## Quy tắc lịch

- Múi giờ Asia/Bangkok, UTC+7; giờ hiển thị `dd/mm/yyyy HH:mm`.
- Lịch gồm thiết bị, giờ, các ngày trong tuần, khoảng chờ và trạng thái bật/tắt. Lịch mới/sửa chỉ áp dụng từ thời điểm lưu, không tạo nhắc cho giờ hẹn đã qua trong ngày.
- Worker chạy mỗi 15 giây trong collector; việc publish nhiều lệnh hoặc database chậm có thể làm chu kỳ dài hơn. Máy chạy collector phải hoạt động và đồng hồ phải đúng.
- Bản ghi lịch hẹn có ID cố định theo lịch/ngày, nên khởi động lại collector không tạo trùng. Khi collector ngừng, lần chạy sau bổ sung lịch hẹn đã qua và ghi bỏ lịch nếu không có phiên tương ứng. Lệnh hết hạn không gửi bù.
- Khoảng đối chiếu là **giờ hẹn ≤ thời điểm nhận gói đầu tiên ≤ hết khoảng chờ**, cùng thiết bị. Một phiên có thể đáp ứng các lịch hẹn trùng khoảng.
- Có phiên hoàn tất với BPM/SpO₂ hợp lệ: Đo thành công. Có phiên hoàn tất tín hiệu kém: Đã đo, cần đo lại. Có gói nhưng chưa hoàn tất: Đang nhận dữ liệu; sau hạn chuyển thành Đã đo, cần đo lại. Không có phiên sau hạn: Bỏ lịch đo.
- Người dùng có thể đo lại trong khoảng chờ; một phiên tốt sẽ thay trạng thái tín hiệu kém. Các gói còn lại của phiên bắt đầu trong khoảng chờ có thể hoàn tất sau hạn.
- **Giới hạn dữ liệu hiện tại:** firmware chỉ gửi uptime, chưa gửi giờ đo tuyệt đối. Phiên đo offline rồi phát lại có thể khớp lịch theo giờ nhận lại. Không thể chứng minh thời điểm đo thật từ payload hiện tại; web ghi rõ giới hạn này.
- Sửa/tắt/xóa lịch hủy các nhắc đang chờ gửi của lịch đó, giữ thông báo và lịch sử đã có. Lịch hẹn cũ đã hủy không kích hoạt lại trong cùng ngày.

## Cảnh báo vượt ngưỡng

Collector dùng nguyên hàm `analyze` hiện có, không sửa thuật toán hoặc raw. Chỉ kiểm tra phiên đủ. BPM/SpO₂ phải có cờ hợp lệ; nhiệt độ bề mặt phải đạt tiêu chí ổn định kỹ thuật.

Ngưỡng cảnh báo mặc định BPM 60–100, SpO₂ 95–100. Nhiệt độ bề mặt mặc định tắt. Đây là cấu hình thông báo, tách biệt với ngưỡng chất lượng và nhãn tham khảo trong thuật toán. Có thể sửa trong mục mở rộng trên web. Thay đổi áp dụng cho các phiên hoàn tất được xử lý tiếp theo, không tính lại các phiên cũ đã xử lý.

ID thông báo vượt ngưỡng theo thiết bị/phiên/chỉ số, tối đa một thông báo cho mỗi chỉ số của một phiên. Worker có thể kiểm tra các phiên lưu sẵn khi chạy lần đầu. Thông báo vượt ngưỡng hiện chỉ lưu/hiện trên web, không phát còi ESP32.

## MQTT và còi

Luồng raw/ACK cũ được giữ. Hai topic mới:

| Topic | Bên phát | Nội dung |
|---|---|---|
| `iot/<device_id>/control` | Collector | `event_id`, `device_id`, `event`, `expires_at` (Unix giây) |
| `iot/<device_id>/control_ack` | ESP32 | `event_id`, `device_id`, `received: true` |

`event` là `measurement_due` hoặc `measurement_missed`. ID là SHA256 dạng hex 64 ký tự. Không dùng retained command. Cấu hình quyền broker phải cho phép collector publish `control`, subscribe `control_ack`, ESP32 subscribe `control`, publish `control_ack` của chính thiết bị; bên cạnh quyền raw/ack cũ.

- Nhắc đến giờ hết hạn khi hết khoảng chờ. Nhắc bỏ lịch hết hạn sau 30 phút tính từ hạn đo.
- Collector publish QoS1, chờ broker xác nhận rồi ghi “Broker đã nhận; chờ ESP32”. Chỉ ACK ứng dụng đúng ID/thiết bị mới ghi “ESP32 đã xác nhận”. Không suy ra đã đo hoặc đã nghe tiếng còi từ ACK này.
- Chưa có ACK: thử lại sau ít nhất 30 giây đến khi hết hạn. Mất MQTT không làm mất thông báo MongoDB. Web hiển thị hết hạn/hủy riêng.
- ESP32 kiểm tra thiết bị, loại sự kiện, ID và hạn lệnh theo NTP. Giữ 16 ID gần nhất trong Preferences/NVS để tránh kêu lại khi gửi trùng/reset, kể cả nhiều lịch gửi xen kẽ. Cặp sự kiện đến giờ/bỏ lịch có ID riêng. Nếu có hơn 16 lệnh còn hiệu lực, lệnh cũ bị đẩy khỏi bộ nhớ chống trùng có thể nhắc lại.
- Đến giờ: một tiếng 200ms mỗi 2 giây, trong 10 giây. Bỏ lịch: hai tiếng ngắn mỗi 2 giây, trong 10 giây. Còi chạy bằng task riêng.

## Thay đổi firmware

Bình thường không deep sleep sau đo nữa. ESP32 chờ online; đặt tay ổn định sẽ bắt đầu thu, gửi, rồi quay về chờ. Cần nhấc tay sau mỗi phiên trước khi đo tiếp. Trong lúc thu vẫn ngắt Wi-Fi và không ghi flash để giữ hợp đồng lấy mẫu; lệnh chưa ACK sẽ được thử lại sau khi thiết bị online.

Nếu còn file chưa gửi, không đo đè; vòng chờ thử gửi lại theo chu kỳ 30 giây. CRC, raw batch và điều kiện xóa phiên sau đủ 30 ACK không thay đổi. Lỗi nghiêm trọng vẫn dùng nhánh báo lỗi và sleep cũ. Chế độ này dùng điện nhiều hơn bản sleep, dành cho thiết bị cắm nguồn.

## MongoDB

Các collection mới: `schedules`, `occurrences`, `notifications`, `monitor_settings`, `session_summaries`, `monitor_state`. Không xóa/sửa dữ liệu raw hiện có. `session_summaries` chỉ giữ trạng thái và lý do, không lưu thay thế raw. Thông báo/lịch sử không tự xóa theo TTL của raw.

Tài khoản web chỉ đọc vẫn xem được dữ liệu; muốn sửa lịch, ngưỡng, trạng thái đọc cần quyền ghi các collection mới. Collector cũng cần các quyền này. Không cần mở quyền xóa raw.

## Kiểm thử

```powershell
cd iot_lab
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
.\.venv\Scripts\python.exe tests/test_ui.py
.\.venv\Scripts\python.exe tests/test_ui_mongo.py
```

Test dùng MongoDB giả lập và MQTT mock, không ghi dữ liệu vào Atlas hoặc gửi lệnh thật. Đã kiểm tra lịch, khung thời gian, khác thiết bị, tín hiệu kém, hồi phục sau gián đoạn, chống trùng, ACK, gửi lại/hết hạn và thao tác form web.

Lần triển khai này chưa biên dịch firmware được trên máy vì thiếu nền tảng `esp32:esp32` trong Arduino CLI, chưa upload hoặc thử còi trên mạch. Cần cài ESP32 core cùng các thư viện trong README firmware, biên dịch đúng board và thử trên phần cứng trước khi coi luồng MQTT/còi đã xác nhận.
