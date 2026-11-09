# Lịch đo và thông báo

## Phạm vi cập nhật

Firmware dựa trên main tại commit 1fde7f0, bổ sung nhận lời nhắc MQTT và phát còi. Giữ nguyên thuật toán physiology.py, ngưỡng phát hiện ngã, nút, cảm biến, luồng thu mẫu và điều kiện bắt đầu đo của main. Đến giờ chỉ phát còi, KHÔNG tự yêu cầu lượt đo mới. Phải nạp bản firmware này để có nhắc trên thiết bị; main cũ chưa hỗ trợ control/control_ack.

## Web và collector

- Bốn tab Tổng quan, Lịch đo, Thông báo, Dữ liệu; đồ thị và xuất CSV/JSON.
- Thêm, sửa, bật/tắt, xóa lịch theo thiết bị, giờ, ngày lặp, khoảng chờ.
- Một collector kiểm tra lịch mỗi 15 giây, không cần mở trình duyệt.
- Lưu lịch, lần hẹn và thông báo vào MongoDB. Có phiên nhưng tín hiệu kém được ghi Đã đo, cần đo lại, không tính bỏ lịch.
- Cảnh báo chỉ số hợp lệ, chống trùng theo thiết bị/phiên/chỉ số.
- Giữ xử lý sự kiện SOS/ngã và yêu cầu tắt báo động theo main.

## MQTT và quyền broker

Giữ nguyên raw/ack, event/event_ack và command. Bổ sung:

| Topic | Bên gửi | Bên nhận |
|---|---|---|
| iot/<device>/control | Collector | ESP32 của đúng thiết bị |
| iot/<device>/control_ack | ESP32 | Collector |

Collector publish control QoS1, không retain, thử lại mỗi 30 giây khi chưa xác nhận và chưa hết hạn. MQTT ACK của broker chỉ ghi Broker đã nhận. ESP32 publish control_ack (ứng dụng), collector ghi ESP32 đã xác nhận sau khi đúng ID/thiết bị. ACK này không chứng minh người dùng đã nghe còi hoặc đã đo.

Payload control có event_id là 64 ký tự hex thường, device_id, event là measurement_due hoặc measurement_missed, expires_at là Unix seconds. ESP32 từ chối sai thiết bị, sai loại, ID sai, lệnh hết hạn hoặc chưa có giờ hợp lệ. Không dùng command/clear_alarm cho nhắc đo.

## Còi và chống trùng

- Đến giờ: một tiếng 200ms mỗi 2 giây, tối đa 10 giây.
- Bỏ lịch: thêm tiếng 150ms tại mốc 300ms của mỗi chu kỳ 2 giây, tối đa 10 giây.
- Dùng tác vụ còi/nút hiện có, không tạo tác vụ còi cạnh tranh. Báo động và khoảng chờ hủy ngã có ưu tiên; lời nhắc hết 10 giây ngay cả khi bị báo động che.
- Lưu 16 ID cùng hạn lệnh trong namespace NVS riêng slab-reminder, snapshot có phiên bản và checksum. Nhận trùng trả ACK mà không kêu lại, kể cả sau reset. Chỉ tái sử dụng slot đã hết hạn; đủ 16 ID chưa hết hạn thì không ACK lời nhắc mới, collector sẽ thử lại. ID hoặc NVS lỗi không được xóa tự động.
- Ghi NVS thành công trước khi phát còi/ACK. NVS lỗi thì tắt riêng nhận nhắc, giữ nguyên chức năng đo/báo động. Reset giữa lúc lưu và phát còi có thể khiến lời nhắc đã lưu không phát lại; không bảo đảm người dùng nghe được.

## Chạy và thử

Chạy một run_collector.bat và run.bat trong iot_lab. Cấp quyền topic mới trên broker, giữ .env, WiFiConfig.h và MqttCloud.h riêng. Nạp firmware khi board/toolchain đã sẵn sàng, không erase flash/NVS và không FORMAT khi đang giữ dữ liệu.

Trên ESP32 thật: thử đến giờ/bỏ lịch, đúng và sai thiết bị, hết hạn, gửi lại cùng ID, reset rồi gửi lại, mất mạng, SOS/ngã trong lúc nhắc và nhắc trong lúc thu/gửi. Kiểm tra raw/ack và thao tác đo hiện tại vẫn hoạt động. Không suy ra âm thanh hoặc độ chính xác cảm biến từ test máy tính.

Đã có test native C++ chạy chính Reminder.h để kiểm tra snapshot/restart, checksum, bộ nhớ đầy/hết hạn, nhịp còi, millis wrap và ưu tiên báo động. Máy hiện thiếu ESP32 core nên chưa biên dịch toàn sketch hoặc nạp/thử mạch.

## Giới hạn thời gian đo

Khớp lịch bằng giờ máy chủ nhận gói đầu tiên, chưa có giờ đo tuyệt đối; dữ liệu offline phát lại có thể được khớp theo giờ gửi lại. ACK lời nhắc không hoàn tất lịch đo. Không thay đổi ngưỡng chất lượng để ép kết quả.
