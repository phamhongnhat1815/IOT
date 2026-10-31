# Signal Lab

Thu thập dữ liệu thô từ ESP32 + MAX30102 + GY-906, lưu MongoDB và hiển thị biểu đồ bằng Streamlit.

```text
ESP32 → MQTT Internet/TLS → Python collector → MongoDB Atlas → Streamlit local
```

## Thành phần

**Bắt đầu tại [hướng dẫn đầy đủ từ cài đặt đến nạp code và xem web](HUONG_DAN_CAI_DAT_VA_NAP_CODE.md).** Có hướng dẫn riêng cho máy collector và người clone chỉ để xem dữ liệu.

- `firmware/HealthRawDirect/`: firmware Arduino IDE, lưu offline vào LittleFS, nhận ACK rồi sleep.
- `iot_lab/`: collector, dashboard, tiền xử lý, công cụ cấu hình và kiểm thử.
- `docs/`: tài liệu nghiên cứu cảm biến và tín hiệu.

Mỗi phiên thu 1.500 cặp IR/RED ở đầu ra danh định 100 Hz và nhiệt độ khoảng mỗi giây. Chưa có thuật toán tính BPM/SpO2 hoặc chẩn đoán bệnh.

## Cài và chạy trên Windows

Cài Python, cấu hình MongoDB Atlas và broker MQTT riêng. Người chỉ xem web dùng tài khoản Atlas chỉ đọc, không chạy collector. Không cần Docker, MongoDB Server local hay Mosquitto local với phương án Atlas; MongoDB local vẫn là lựa chọn phát triển nếu tự cấu hình URI tương ứng.

Tại thư mục dự án:

```powershell
cd iot_lab
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Tạo `.env` từ `.env.example` nếu chưa có, điền `MONGO_URI` của Atlas và `MONGO_DB=signal_lab` theo hướng dẫn đầy đủ. Giữ `.env` đang hoạt động nếu máy đã cấu hình. Với máy quản lý dữ liệu:

```powershell
.\.venv\Scripts\python.exe check_connection.py --init
.\.venv\Scripts\python.exe configure_mqtt_cloud.py
.\.venv\Scripts\python.exe check_mqtt.py
```

Script cấu hình yêu cầu hostname, port TLS, MQTT username/password và CA của broker riêng. Xem [hướng dẫn MQTT Internet](iot_lab/MQTT_INTERNET.md).

Mở hai terminal tại `iot_lab`: chạy `run_collector.bat` và `run.bat`. Chỉ chạy một collector. Web local: http://127.0.0.1:8501, chọn nguồn **MongoDB** và thiết bị **esp32-01** khi đã có dữ liệu. Muốn người khác truy cập qua Internet cần triển khai web riêng.

## Nạp ESP32

1. Copy `firmware/HealthRawDirect/WiFiConfig.example.h` thành `WiFiConfig.h`, điền Wi-Fi. Máy đang cấu hình sẵn thì giữ file hiện có.
2. Script `configure_mqtt_cloud.py` tạo `MqttCloud.h` cho ESP32 và `.env` cho Python dùng cùng broker.
3. Mở `HealthRawDirect.ino`, giữ các header cùng thư mục. Cài thư viện theo [hướng dẫn firmware](firmware/HealthRawDirect/README.md), chọn board rồi Upload.
4. Serial Monitor **9600 baud**. Giữ **Erase All Flash = Disabled**, không FORMAT khi còn dữ liệu chưa gửi.

Có phiên cũ thì gửi hết trước khi đo. Chưa gửi hết thì sleep và giữ dữ liệu. Còi đo hai tiếng ngắn rồi nghỉ; còi gửi một tiếng ngắn mỗi giây; hoàn thành kêu dài 2 giây rồi sleep.

## Kiểm tra và cấu hình riêng

```powershell
cd iot_lab
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

Git bỏ qua `.env`, bản sao `.env`, `WiFiConfig.h`, `MqttCloud.h`, `.venv`, dữ liệu/log và file biên dịch. Chỉ đưa file cấu hình **mẫu** lên Git. Không commit mật khẩu hoặc dữ liệu người đo.

Chi tiết chương trình: [iot_lab/README.md](iot_lab/README.md).
