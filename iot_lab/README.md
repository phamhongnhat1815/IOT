# Signal Lab — Python backend và dashboard

ESP32 → MQTT cloud/TLS → collector → MongoDB Community Server → Streamlit. Không cần Docker, ThingsBoard hay broker local.

## Cấu hình

Dùng `configure_mqtt_cloud.py` theo [MQTT_INTERNET.md](MQTT_INTERNET.md). Mẫu `.env.example` chứa cấu hình tham khảo, không phải tài khoản hoạt động. Script giữ nguyên cấu hình MongoDB đang có, ghi thông tin broker vào `.env` và `../firmware/HealthRawDirect/MqttCloud.h`. Không chia sẻ hai file này hoặc `.env.before-cloud`.

MongoDB mặc định: `mongodb://127.0.0.1:27017`, database `signal_lab`. Đường dẫn CA trong `.env` có thể tương đối với thư mục `iot_lab`. TLS luôn kiểm tra chứng chỉ.

## Cài và chạy

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe check_connection.py --init
.\.venv\Scripts\python.exe configure_mqtt_cloud.py
.\.venv\Scripts\python.exe check_mqtt.py
```

MongoDB Windows Service phải chạy. Sau khi kiểm tra MQTT báo OK:

- Terminal 1: `.\run_collector.bat`, chờ `MQTT subscribed to iot/+/raw`.
- Terminal 2: `.\run.bat`, mở http://127.0.0.1:8501.
- Nạp/bật ESP32. Trên web chọn MongoDB, tải lại trang rồi chọn thiết bị và phiên.

Chỉ chạy một collector. Khởi động lại collector sau khi thay `.env`. `requirements.lock.txt` ghi phiên bản môi trường Windows đã dùng; `requirements.txt` chứa phạm vi phiên bản hỗ trợ.

## Dữ liệu và ACK

| Collection | Mục đích |
|---|---|
| raw_inbox | Gói gốc, unique theo thiết bị/phiên/batch, ghi bền vững trước ACK |
| raw_timeseries | Time-Series dữ liệu gốc |
| processed_timeseries | Kết quả tiền xử lý |
| processed_registry | Nhận diện phiên bản đã xử lý |
| quarantine | Báo cáo thông điệp lỗi, không lưu nguyên payload |

TTL mặc định 7 ngày, xóa bất đồng bộ bởi MongoDB. Inbox là nguồn phục hồi projection. Reader loại trùng theo batch_id nếu Time-Series bị lặp vật lý sau crash.

Topic dữ liệu `iot/<device_id>/raw`, ACK `iot/<device_id>/ack`. Hỗ trợ payload trực tiếp và các định dạng cũ `ppg_raw`/`raw_batch`. Mỗi phiên firmware có 30 gói × 50 cặp IR/RED, kèm tần số và metadata. Thời gian nhận UTC được lưu riêng với millis/micros của thiết bị; không suy tốc độ lấy mẫu từ thời điểm MQTT nhận gói.

Collector chỉ phát ACK sau khi lưu MongoDB bền vững. Thiết bị chỉ xóa phiên flash sau đủ 30 ACK. Gửi lại cùng nội dung được loại trùng; cùng định danh nhưng khác nội dung bị từ chối. Xem [firmware](../firmware/HealthRawDirect/README.md) để biết cách xử lý offline và sleep.

## Dashboard và tiền xử lý

Web có ba thẻ nhịp mạch, SpO₂ ước tính và trung vị nhiệt độ bề mặt, kèm nhận xét và mức đối chiếu tham khảo. Nguồn **Minh họa** không phải dữ liệu thiết bị thật. SpO₂ chưa hiệu chuẩn, nhiệt độ không phải thân nhiệt, không có chẩn đoán. Xem [ANALYSIS.md](ANALYSIS.md) để biết cổng chất lượng, công thức và ngưỡng. Phân tích chạy khi xem, không cần quyền ghi Atlas; raw, CSV và tab tiền xử lý riêng vẫn được giữ.

```powershell
.\.venv\Scripts\python.exe preprocess.py --device esp32-01 --session SESSION_ID
```

Tiền xử lý giữ raw: IQR đánh dấu ngoại lệ; rolling mean, delta và MinMax ở bản phân tích riêng. Không nội suy PPG qua đoạn thiếu; nhiệt độ resample 1s, chỉ lấp một ô thiếu nội bộ.

Kiểm tra pipeline bằng dữ liệu mô phỏng có nhãn riêng:

```powershell
.\.venv\Scripts\python.exe simulate.py --realtime
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

`data/` chứa log, CA và cài đặt ngưỡng cục bộ, không đưa lên Git. MongoDB lưu database ngoài thư mục này.
