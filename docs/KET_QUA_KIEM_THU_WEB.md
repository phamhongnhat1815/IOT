# Kết quả kiểm thử web Signal Lab

Ngày kiểm thử: **07/11/2026**, múi giờ Asia/Bangkok (UTC+7).

## Kết luận

- **42/42 kiểm thử logic hiện có đạt.**
- **13/13 kiểm thử tích hợp đạt**, dùng broker MQTT TCP thật trên loopback, collector thật, MongoDB giả lập và chương trình ESP32 giả lập.
- Hai bộ kiểm thử giao diện cơ bản và bộ giao diện mở rộng đạt.
- Ba nút xuất file đã được nhấn trực tiếp trong trình duyệt; các file tải về đã được mở và kiểm tra nội dung.
- Phát hiện và sửa một lỗi ở form ngưỡng đồ thị, sau đó kiểm thử hồi quy đạt.

Đây là kết quả kiểm thử phần mềm với môi trường cô lập, **không phải xác nhận phần cứng, firmware hay độ chính xác y tế**.

## Môi trường và mức cô lập

- Python của `iot_lab/.venv`, Streamlit AppTest, mongomock và paho-mqtt.
- Broker kiểm thử: AMQTT 0.12.1, chỉ bind `127.0.0.1` với cổng ngẫu nhiên; không sử dụng hostname, mật khẩu hoặc cổng broker trong `.env`.
- Các thiết bị tích hợp có ID bắt đầu bằng `TEST-`, không có ESP32 thật kết nối tới broker thử.
- Database: MongoDB giả lập trong RAM, mỗi ca tích hợp dùng database riêng. Không ghi vào Atlas hoặc database thật.
- Cấu hình đường ngưỡng dùng thư mục tạm riêng trong bài kiểm thử form; không sửa file ngưỡng thật của người dùng.
- Thời gian lịch được điều khiển trong test để kiểm tra đến giờ/quá hạn nhanh; không chờ thực tế 30 phút. Thuật toán phân tích, validator và bộ xử lý MQTT dùng code sản phẩm.
- Các broker/client thử đã được dừng. Tab trình duyệt dùng kiểm tra tải file đã đóng; không thay đổi nguồn dữ liệu của tab người dùng.

## Luồng tích hợp được kiểm chứng

`Form lịch trên web → MongoDB giả lập → Monitor → broker MQTT TCP thật → ESP32 Python giả lập → control_ack → collector → thông báo trên web`.

Sau đó thiết bị giả lập gửi 30 gói × 50 cặp IR/RED qua MQTT; collector xác thực, lưu inbox, chiếu dữ liệu, phát ACK từng gói. Monitor phân tích và cập nhật lịch; giao diện đọc được “ESP32 đã xác nhận” và “Đo thành công”.

Hàm `configure_callbacks` được tách khỏi `main` của collector để bộ kiểm thử sử dụng đúng các callback chạy trong sản phẩm, thay vì chép lại một collector riêng cho test.

## 13 tình huống tích hợp

| Tình huống | Kết quả |
|---|---|
| Nhắc đến giờ được chuyển qua MQTT, broker xác nhận chưa bị coi là ESP32 xác nhận | Đạt |
| ACK sai thiết bị bị từ chối; ACK đúng cập nhật confirmed | Đạt |
| Gửi lại khi chưa ACK; giả lập chỉ phát một lần cho cùng event ID | Đạt |
| Nhận đủ 30 gói, 1.500 mẫu; hoàn thành lịch, không tạo cảnh báo giả | Đạt |
| Phát lại raw không làm tăng số bản ghi inbox/time-series | Đạt |
| Phiên tín hiệu kém là cần đo lại, không phải bỏ lịch | Đạt |
| Không đo sau hạn tạo nhắc bỏ lịch; sự kiện hết hạn không gửi tiếp | Đạt |
| SpO₂ giả lập thấp tạo một cảnh báo cho cùng phiên/chỉ số | Đạt |
| Raw sai cấu trúc bị quarantine, không có ACK “đã lưu” | Đạt |
| Thiết bị mất kết nối rồi kết nối lại nhận được lệnh gửi lại | Đạt |
| Xóa lịch hủy lệnh đang chờ và giữ lịch sử | Đạt |
| Phiên chưa đủ gói: đang nhận → cần đo lại sau hạn, không bỏ lịch | Đạt |
| Form web đặt lịch, nhận xác nhận, nhận phiên đo rồi hiển thị hoàn thành | Đạt |
| Worker chạy không cần mở phiên web | Đạt |
| Giả lập lỗi ghi database: không ACK đã lưu; khôi phục rồi nhận lại thành công | Đạt |
| Phiên từ thiết bị khác không được dùng để hoàn thành lịch | Đạt |

Một số ca kiểm thử bao gồm nhiều kiểm tra con nên số hàng trong bảng lớn hơn số test case. Bằng chứng máy đọc được: `iot_lab/data/test-results/system-test.json`.

## Kiểm thử giao diện

Dùng Streamlit AppTest với MongoDB giả lập; đây là kiểm thử thực thi code web và trạng thái widget, không thay thế việc kiểm tra phần cứng.

| Nhóm | Nội dung | Kết quả |
|---|---|---|
| Nguồn dữ liệu | Minh họa → MongoDB; không có dữ liệu vẫn hiển thị trạng thái rỗng | Đạt |
| Bộ lọc | Đổi thiết bị, đổi phiên; lọc 1 giờ/24 giờ loại đúng phiên cũ | Đạt |
| Chỉ số | Không có phiên không hiển thị số 0 hoặc kết luận bình thường | Đạt |
| Cập nhật | Điều khiển bật/tắt tự cập nhật không gây exception | Đạt |
| Tiền xử lý | Cả trạng thái chưa có và có bản rolling mean/nhiệt độ được đọc | Đạt |
| Lịch | Thêm, đổi giờ, đổi khoảng chờ, bật/tắt, bật lại, xóa | Đạt |
| Lịch không hợp lệ | Không chọn ngày, mã thiết bị sai bị từ chối và không ghi dữ liệu | Đạt |
| Ngưỡng cảnh báo | Ngưỡng dưới ≥ ngưỡng trên bị từ chối; khoảng hợp lệ lưu được | Đạt |
| Thông báo | Đánh dấu đã đọc và lọc chỉ chưa đọc; trạng thái lưu qua lần chạy lại | Đạt |
| Đường ngưỡng đồ thị | Lưu hợp lệ, sửa lần hai, từ chối giá trị sai mà không ghi đè file | Đạt sau sửa |
| Cập nhật đường ngưỡng | Khi tắt tự cập nhật, lưu form vẫn làm đồ thị vẽ lại ngay | Đạt sau sửa |

## File xuất đã tải qua trình duyệt

Tải trên tab kiểm thử riêng tại web local, nguồn **Minh họa**. Không tải dữ liệu người đo thật.

| File | Kiểm tra sau khi mở | Kết quả |
|---|---|---|
| `ir-red.csv` | 1.500 dòng; cột index/t/ir/red/segment; index 0…1499; IR/RED không thiếu | Đạt |
| `temperature.csv` | 15 dòng; 15 mốc temperature_at_ms riêng; nhiệt độ vật thể/môi trường hợp lệ | Đạt |
| `analysis.json` | JSON đọc được; có BPM/SpO₂, 15 lần đọc nhiệt độ, cờ chất lượng và calibration_status | Đạt |

Dữ liệu minh họa cho BPM khoảng 69,77 và SpO₂ khoảng 88,91. Các giá trị chỉ kiểm tra tính nhất quán giữa web và file, không chứng minh độ chính xác đo người thật. File được trình duyệt lưu vào thư mục Downloads của máy.

## Lỗi tìm thấy và đã sửa

**Form đường ngưỡng không giữ ổn định trạng thái khi sửa sau lần lưu đầu.** Các widget trước đây dùng giá trị mặc định đọc lại từ file nhưng không có key ổn định. Khi file thay đổi, Streamlit có thể dựng lại widget và thay mất giá trị mới người dùng nhập, làm việc kiểm tra ngưỡng lần hai không đúng ý người dùng.

Đã thêm key riêng cho từng checkbox/input. Sau khi ghi file thành công, web chạy lại để các đồ thị đọc cấu hình mới ngay cả khi người dùng tắt tự cập nhật; thông báo lưu thành công được giữ qua lần chạy lại. Test tái hiện đã qua: lưu 40.000–120.000; sửa ngưỡng dưới thành 130.000 phải báo lỗi và giữ nguyên file; sửa lại hợp lệ phải lưu và có lớp rule trong đồ thị.

## Chưa thể kết luận từ đợt kiểm thử này

- Còi, nút SOS, MAX30102, GY-906 và việc lấy mẫu trên mạch thật.
- Firmware thực sự nhận MQTT, lưu ID chống trùng trong NVS, mất nguồn và hoạt động lâu dài. ESP32 giả lập bằng Python không chạy mã Arduino.
- Xác thực/TLS/ACL với broker cloud của nhóm. Broker thử không dùng tài khoản thật.
- Ghi bền vững lên Atlas, time-series/TTL thực, phục hồi database sau khởi động máy. mongomock không kiểm chứng các đặc tính này.
- Chạy liên tục nhiều giờ/ngày hoặc nhiều collector đồng thời. Thiết kế hiện tại yêu cầu một collector.
- Độ chính xác BPM/SpO₂/nhiệt độ trên người thật; thuật toán và ngưỡng chất lượng không thay đổi trong đợt test.

## Chạy lại

Tại `iot_lab`:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-mqtt-test.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
.\.venv\Scripts\python.exe tests/test_ui.py
.\.venv\Scripts\python.exe tests/test_ui_mongo.py
.\.venv\Scripts\python.exe tests/run_ui_extended.py
.\.venv\Scripts\python.exe tests/run_system_test.py
```

Bài `run_system_test.py` sẽ tự tạo và dừng broker loopback; không cần chạy collector thật. Log “Mongo write failed” ở test lỗi database là lỗi được cố ý tạo để xác minh không ACK sai, không phải Atlas bị lỗi.
