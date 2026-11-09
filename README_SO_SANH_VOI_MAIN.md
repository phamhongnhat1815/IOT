# Những điểm khác main và hướng dẫn review

Ngày cập nhật: 09/11/2026, UTC+7.

Tài liệu so sánh **bản code hiện tại trên máy, gồm cả thay đổi chưa commit**, với `origin/main` tại commit **`1fde7f0` — second**. Không phải so sánh với riêng nhánh `vudo` cũ trên GitHub. Nếu main có commit mới sau mốc này, cần so sánh lại.

Bản này bổ sung giao diện, lịch đo, thông báo và nhận lời nhắc bằng còi. **Có sửa firmware**, nhưng chỉ để nhận lời nhắc, lưu ID chống trùng và phối hợp còi với báo động hiện có. Lời nhắc **không tự bắt đầu đo**.

## 1. Khác biệt về chức năng

| Nội dung | Main tại 1fde7f0 | Bản hiện tại |
|---|---|---|
| Giao diện | Giao diện cũ; các tab phân tích, raw, tiền xử lý | Bốn tab Tổng quan, Lịch đo, Thông báo, Dữ liệu; bố cục mới |
| Chọn dữ liệu | Minh họa/MongoDB, thiết bị, phiên, khoảng giờ | Giữ chức năng; chuyển các lựa chọn vào sidebar |
| Bộ lọc Minh họa | Đổi khoảng giờ nhưng phiên mẫu không đổi | Khóa bộ lọc, ghi rõ không áp dụng cho phiên cố định |
| Mất kết nối MongoDB | Hiện lỗi kết nối | Dừng các truy vấn tiếp theo/tự cập nhật khi phát hiện lỗi ở bước kết nối; có nút thử lại |
| Chỉ số | BPM, SpO₂ ước tính, nhiệt độ bề mặt | Giữ ba chỉ số; cảnh báo theo cấu hình ở cạnh chỉ số hợp lệ; thiếu kết quả có lý do |
| Lịch đo | Chưa có bộ quản lý lịch | Thêm/sửa/bật/tắt/xóa theo thiết bị, giờ, ngày lặp, khoảng chờ |
| Nhắc đo và bỏ lịch | Chưa có worker kiểm tra lịch | Collector kiểm tra mỗi 15 giây, lưu thông báo MongoDB |
| Phiên tín hiệu kém | Chưa đối chiếu với lịch | Có phiên trong khoảng hẹn thì ghi “Đã đo, cần đo lại”, không tính bỏ lịch |
| Cảnh báo vượt ngưỡng | Có mức tham khảo trên web | Thêm cấu hình và thông báo lưu MongoDB, chống trùng theo thiết bị/phiên/chỉ số |
| SOS/ngã và tắt báo động | Đã có trong main | Giữ backend/firmware; đưa giao diện vào tab Thông báo, vẫn xem được khi chưa có phiên raw |
| Đồ thị và xuất file | Có đồ thị, CSV/JSON, tiền xử lý | Giữ chức năng; dữ liệu raw ghi rõ “Dữ liệu thô”; chi tiết thu gọn |
| Công thức/JSON trên màn hình | Có expander kỹ thuật | Không render công thức/JSON dài ở Tổng quan; vẫn tải JSON phân tích được |
| Thời gian web | Một số nơi dùng ISO | Lịch/phiên/thông báo lịch hiển thị dd/mm/yyyy HH:mm, UTC+7; panel SOS/ngã giữ cách hiển thị thời gian của main |
| Còi nhắc đo | Chưa nhận control/control_ack | Thêm nhận lời nhắc đến giờ/bỏ lịch, phát còi và trả ACK |

## 2. Các file cần đọc khi review

| File | Thay đổi cần chú ý |
|---|---|
| `iot_lab/web.py` | Giao diện mới, các form lịch/ngưỡng, thông báo, xử lý lỗi DB, ghép panel SOS/ngã |
| `iot_lab/dashboard_ui.py`, `dashboard.css`, `.streamlit/config.toml` | Thành phần giao diện, CSS và theme |
| `iot_lab/monitoring.py` | Lưu lịch, đối chiếu phiên, cảnh báo, MQTT outbox, ACK, worker nền |
| `iot_lab/overview_state.py` | Tính lịch kế tiếp và trạng thái cần chú ý cho Tổng quan |
| `iot_lab/collector.py` | Chạy thêm worker lịch; giữ xử lý raw và event SOS/ngã, gửi lệnh tắt báo động |
| `firmware/HealthRawDirect/HealthRawDirect.ino` | Khởi tạo NVS lời nhắc, subscribe control, kiểm tra payload và trả control_ack |
| `firmware/HealthRawDirect/Reminder.h` | File mới: cache 16 ID/hạn lệnh, snapshot/checksum, chính sách nhịp còi |
| `firmware/HealthRawDirect/Wearable.h` | Bổ sung nhắc vào tác vụ xuất còi hiện có, giữ ưu tiên báo động |
| `iot_lab/tests/test_reminder_firmware.py`, `tests/cpp/reminder_test.cpp` | Test C++ dùng trực tiếp Reminder.h |
| `iot_lab/tests/test_combined_collector.py` | Kiểm tra collector giữ đồng thời route SOS/ngã và lời nhắc |
| Các test monitoring/UI/system mới | Kiểm tra lịch, thông báo, kết nối, xuất dữ liệu và MQTT với thiết bị giả |
| `docs/LICH_DO_VA_THONG_BAO.md` | Giao thức, cách chạy, giới hạn và bước thử trên mạch |

## 3. Phần giữ nguyên so với main

- `physiology.py` giữ nguyên main: công thức BPM/SpO₂ và ngưỡng chất lượng tự tương quan **0,5**. Lần thử hạ xuống 0,2 trước đây không nằm trong bản này.
- Giữ `FallDetector.h`, `WearableConfig.h`, ngưỡng phát hiện ngã, GPIO và thao tác nút hiện có.
- Giữ hàm thu mẫu `acquireSession`, vòng lặp đo `loop`, tạo payload raw và upload; không đổi điều kiện yêu cầu lượt đo của main.
- Giữ 1.500 cặp/30 gói, xử lý FIFO, lưu LittleFS, raw ACK và cơ chế giữ dữ liệu chưa gửi.
- Giữ xử lý sự kiện SOS/ngã, tắt báo động và các collection/index của main.
- Không đổi thông tin Wi-Fi/MQTT/MongoDB riêng, không xóa dữ liệu, không format NVS/flash.

Main tại mốc so sánh **vẫn chứa code SOS/ngã**. Tài liệu này mô tả code đã kiểm tra, không suy ra phần cứng thực tế đang dùng hoặc quyết định mới của nhóm. Nếu nhóm đã bỏ SOS trong bản chưa push, cần ghép lại với bản đó trước khi nạp.

## 4. Lời nhắc MQTT mới

| Topic | ESP32 | Collector |
|---|---|---|
| `iot/<device_id>/control` | Subscribe | Publish QoS1, không retain |
| `iot/<device_id>/control_ack` | Publish | Subscribe |

Giữ nguyên các topic `raw/ack`, `event/event_ack`, `command`. Phải cấp quyền bổ sung trên broker; không dùng lệnh `clear_alarm` để nhắc đo.

Payload ví dụ minh họa cấu trúc, phải thay ID và hạn lệnh bằng giá trị thực khi thử:

```json
{
  "event_id": "<64 ký tự hex thường, duy nhất cho sự kiện>",
  "device_id": "esp32-01",
  "event": "measurement_due",
  "expires_at": "<Unix seconds dạng số nguyên, còn hiệu lực>"
}
```

- Loại sự kiện: `measurement_due` hoặc `measurement_missed`.
- ESP32 từ chối sai thiết bị, sai loại, ID sai, lệnh hết hạn hoặc chưa có giờ hợp lệ.
- Ghi cache ID vào NVS trước khi phát còi/ACK. Nhận lại cùng ID thì chỉ ACK, không kêu lại, kể cả sau reset.
- Namespace NVS mới `slab-reminder`, 16 ID cùng hạn lệnh, có phiên bản và checksum. Không ghi đè ID còn hạn; nếu đầy thì chờ retry. NVS lỗi sẽ vô hiệu riêng lời nhắc, không ACK giả và không tự xóa trạng thái.
- Đến giờ: 200ms mỗi 2 giây trong 10 giây. Bỏ lịch: thêm tiếng từ mốc 300–450ms mỗi chu kỳ.
- Báo động hoặc khoảng chờ hủy ngã ưu tiên hơn nhắc; không có hai task cùng ghi còi. Lời nhắc có thể bị che và vẫn hết sau 10 giây.
- ACK ESP32 chỉ xác nhận **chấp nhận lời nhắc**, không chứng minh còi đã phát, người dùng đã nghe hoặc đã đo. Reset giữa lúc lưu và phát còi có thể làm lời nhắc đó không phát lại.
- Collector thử lại sau ít nhất 30 giây khi chưa ACK, dừng khi hết hạn. Publish/broker ACK không được coi là ESP32 đã nhận.
- Đến lịch chỉ nhắc bằng còi. Người dùng đo theo cách main hiện tại; không có cơ chế tự khởi động lượt đo mới từ lời nhắc.

## 5. MongoDB và giới hạn cần biết

Các collection bổ sung: `schedules`, `occurrences`, `notifications`, `monitor_settings`, `session_summaries`, `monitor_state`. Người chỉnh lịch/ngưỡng/đánh dấu đã đọc cần quyền ghi; chỉ xem số liệu có thể dùng tài khoản chỉ đọc nhưng không thao tác lưu được.

Khớp lịch theo **giờ máy chủ nhận gói đầu tiên**, trong khoảng giờ hẹn đến hết khoảng chờ. Firmware chưa gửi giờ đo tuyệt đối, nên phiên offline gửi lại có thể khớp theo giờ gửi lại. Chưa xác minh được thời điểm đo thật.

Worker có thể phân tích các phiên đã lưu khi chạy lần đầu và tạo thông báo vượt ngưỡng. Cảnh báo vượt ngưỡng chỉ hiện/lưu trên web, **không gửi còi về ESP32**. Nhắc đến giờ và bỏ lịch mới dùng giao thức control.

Không gọi ACK lời nhắc là hoàn tất lịch. Phải có phiên đo đúng thiết bị trong khoảng hẹn; phiên kém chất lượng được ghi cần đo lại.

## 6. Đã kiểm thử và chưa kiểm chứng

| Nội dung | Kết quả |
|---|---|
| Bộ test logic/UI/protocol | 52 test qua |
| Native C++ chính Reminder.h | Qua: snapshot/restart, checksum, dung lượng/hết hạn, nhịp còi, tràn millis, ưu tiên báo động |
| MQTT cục bộ + MongoDB giả + thiết bị giả | 13 test qua |
| AppTest mất DB, lịch, thông báo | Qua |
| Biên dịch toàn bộ sketch ESP32 | **Chưa thực hiện được: máy thiếu ESP32 core** |
| Nạp board, còi/GPIO/cảm biến/NVS thực tế | **Chưa thử** |
| Broker cloud thực tế, TLS, tài khoản và ACL của nhóm | **Chưa xác minh trong lần sửa này** |

Test MQTT dùng thiết bị giả Python; không chứng minh firmware Arduino đã nhận đúng payload trên mạch. Test C++ kiểm tra phần chính sách Reminder.h, không giả lập toàn bộ Preferences/ArduinoJson/FreeRTOS. Không suy ra độ chính xác y tế từ các test này.

`docs/KET_QUA_KIEM_THU_WEB.md` là báo cáo lần trước, các con số và phạm vi trong đó không thay thế bảng kiểm thử mới ở đây.

## 7. Cách chạy và checklist trước khi merge

Trong `iot_lab`, giữ `.env` hiện có. Dừng collector cũ rồi mở hai terminal:

```powershell
# Terminal 1: chỉ chạy một collector
.\run_collector.bat

# Terminal 2
.\run.bat
```

Mở `http://127.0.0.1:8501`, chọn MongoDB. Muốn thử còi phải cài đúng ESP32 core/thư viện, giữ các header cấu hình riêng và `Reminder.h` cạnh sketch, biên dịch rồi nạp. Không đổi partition hoặc xóa flash/NVS khi đang giữ dữ liệu.

- [ ] Review diff firmware: chỉ phần nhận nhắc/NVS/còi, không thay luồng đo hoặc ngưỡng.
- [ ] Biên dịch với đúng board/core nhóm đang dùng; kiểm tra RAM/flash.
- [ ] Cấp quyền hai topic mới cho ESP32 và collector.
- [ ] Tạo lịch vài phút tới, kiểm tra còi và ACK đúng thiết bị; sau đó đo theo thao tác hiện tại.
- [ ] Không đo đến hết khoảng chờ: có thông báo bỏ lịch và nhịp còi tương ứng.
- [ ] Gửi trùng cùng ID, reset rồi gửi lại: không kêu lại; sai thiết bị/hết hạn: không ACK và không kêu.
- [ ] Thử mất mạng, reconnect và retry; broker nhận mà chưa có ACK thiết bị phải còn trạng thái chờ.
- [ ] Thử báo động hiện có khi đang nhắc, và lời nhắc trong lúc thu/gửi raw; không làm mất báo động/raw ACK.
- [ ] Thử phiên chất lượng kém: cần đo lại, không ghi bỏ lịch và không cảnh báo chỉ số không hợp lệ.
- [ ] Kiểm tra `.env`, WiFiConfig.h, MqttCloud.h không vào commit/ZIP.

ZIP không kèm cấu hình riêng, `.venv`, dữ liệu hoặc thư mục `.git`. Nếu chạy máy mới, cài `requirements.txt` và tạo cấu hình riêng theo hướng dẫn project. Các file test thêm nằm trong requirements-dev/requirements-mqtt-test, không bắt buộc cho chạy web thông thường.

Các chỉnh sửa mới chưa được tự động push lên GitHub. Khi review, dùng nội dung bản nhận được hoặc diff đầy đủ với main; không chỉ xem commit ghép cũ `ce93679` vì commit đó chưa chứa toàn bộ điều chỉnh sau này.
