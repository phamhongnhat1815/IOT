# MQTT Internet — MongoDB vẫn cài trên máy tính

Luồng sau khi cấu hình: ESP32 → broker MQTT cloud có TLS → collector Python trên máy tính → MongoDB local → web Streamlit local. Máy tính và ESP32 có thể dùng hai mạng Internet khác nhau. Máy tính phải bật, MongoDB và collector phải chạy để xác nhận lưu; ESP32 vẫn giữ phiên trong flash nếu chưa đủ ACK. Không cần Docker, Mosquitto local hoặc mở port router.

## 1. Tạo broker riêng

Theo [EMQX Cloud Serverless](https://docs.emqx.com/en/cloud/latest/create/serverless.html), kiểm tra ngày 31/10/2026:

1. Mở https://cloud-intl.emqx.com/ và đăng ký/đăng nhập bằng tài khoản của bạn.
2. Tạo project khi được yêu cầu; chọn New Deployment → Serverless.
3. Đặt **Monthly Spend Limit = 0**, chỉ dùng hạn mức miễn phí; hết hạn mức thì deployment có thể bị dừng. Kiểm tra thông tin giá trên màn hình trước khi tạo. Không cần chọn gói trả phí cho bài thử này.
4. Đặt tên, ví dụ `signal-lab`, và tạo deployment. Đợi trạng thái Running.
5. Trong Overview → Connection Information: sao chép **Address/hostname**, **MQTT TLS port** (thường 8883), và tải **CA Certificate**. Hostname không có `https://`, `mqtts://`, đường dẫn hay `:8883`.
6. Vào **Access Control → Authentication → Add**. Tạo MQTT username/password riêng. Đây là tài khoản kết nối MQTT, không phải tài khoản đăng nhập trang web.
7. Nếu tự cấu hình Authorization/ACL, tài khoản cần publish và subscribe `iot/+/raw`, `iot/+/ack` cho bài lab này. Không dùng broker thử nghiệm công khai để gửi dữ liệu người đo thật.

## 2. Cấu hình một lần cho cả Python và ESP32

Mở PowerShell bình thường:

```powershell
cd <duong-dan-repo>\iot_lab
.\.venv\Scripts\python.exe configure_mqtt_cloud.py
```

Nhập lần lượt hostname, port, MQTT username/password và đường dẫn đầy đủ đến file CA vừa tải. Khi nhập mật khẩu, màn hình không hiện ký tự là bình thường.

Script giữ cấu hình MongoDB và Wi-Fi đang có, tạo:

- `.env`: cấu hình Python, bật TLS và đặt client ID riêng.
- `.env.before-cloud`: bản sao cấu hình trước khi chuyển, chứa thông tin riêng như `.env`.
- `data/certs/mqtt-ca.pem`: bản sao CA công khai.
- `../firmware/HealthRawDirect/MqttCloud.h`: cùng broker, username/password, CA cho ESP32.

Không đưa `.env`, bản sao `.env` hoặc `MqttCloud.h` lên GitHub/chụp gửi. Script không tự tạo tài khoản cloud và không khởi động lại collector đang chạy.

## 3. Kiểm tra và chạy collector

```powershell
.\.venv\Scripts\python.exe check_mqtt.py
```

Cần thấy `TLS=True` và `OK: MQTT connected and subscribed`. Kiểm tra này không gửi dữ liệu cảm biến. Nếu lỗi: kiểm tra hostname/port, CA và MQTT credentials; không tắt kiểm tra chứng chỉ.

Dừng collector cũ rồi chạy lại `run_collector.bat`. Chỉ chạy một collector. Nếu collector cũ đang chạy nền từ lần sửa trước, nhờ dừng đúng tiến trình đó trước khi mở bản mới. Không cần broker Mosquitto local. MongoDB Windows Service vẫn phải chạy.

## 4. Nạp ESP32

1. Mở **firmware/HealthRawDirect/HealthRawDirect.ino** trong repo. Giữ cả `FirmwareTypes.h`, `WiFiConfig.h` và `MqttCloud.h` trong cùng thư mục; không nạp sketch cũ ở Documents\Arduino.
2. Kiểm tra tên/mật khẩu Wi-Fi và mức kích còi trong `WiFiConfig.h` (copy từ `WiFiConfig.example.h` nếu mới clone). Mức kích còi ở đầu sketch. Tên miền MQTT được lấy từ `MqttCloud.h`, không điền IP LAN.
3. Giữ partition đang dùng và **Erase All Flash = Disabled**, không FORMAT để giữ các phiên cũ. Không thay layout `FirmwareTypes.h`.
4. Upload. Serial Monitor 9600. Cần thấy `TRANSPORT: MQTT_CLOUD_TLS_V1`.
5. ESP32 đồng bộ giờ NTP qua Internet trước khi kiểm tra chứng chỉ TLS. Nếu NTP bị mạng chặn thì chưa kết nối broker; file vẫn được giữ để thử lại.
6. Khi collector online, các phiên cũ vẫn gửi cùng device/session/batch và chỉ được xóa sau đủ ACK. Bật lại sau khi chưa gửi xong thì gửi lại an toàn, Python loại trùng.

```text
TRANSPORT: MQTT_CLOUD_TLS_V1
TLS: dang dong bo gio NTP...
MQTT connected=1
ACK esp32-01-... 1/30 (50 cap)
...
ACK esp32-01-... 30/30 (50 cap)
```

Mở `run.bat`, chọn nguồn MongoDB, tải lại trang và chọn `esp32-01`. Thiết bị chỉ xuất hiện sau khi collector lưu ít nhất một gói thật.

## Đổi mạng và truy cập web

- Đổi Wi-Fi ESP32: chỉ đổi SSID/password, giữ broker hostname.
- Máy tính đổi Wi-Fi: không đổi MQTT hostname. Máy cần truy cập Internet và broker TLS port.
- MongoDB vẫn local, không cần mở 27017 ra Internet.
- Web vẫn ở localhost:8501; người khác xem từ xa là bước triển khai web riêng. Chuyển MQTT cloud không tự công khai web.
- Nếu chưa tạo broker và chưa chạy script cấu hình, không nạp bản placeholder; nó báo lỗi cấu hình rồi sleep, không gửi dữ liệu.

Mỗi máy cần tự cấu hình broker riêng. Chạy `check_mqtt.py`, kiểm tra ACK đủ30 gói và MongoDB bằng phần cứng thật; compile hoặc kiểm tra broker riêng lẻ không thay thế kiểm tra end-to-end.

Firmware mới bắt buộc gửi sạch backlog trước khi đo; chưa gửi hết thì sleep, không thu thêm. Còi gửi/chờ ACK một tiếng mỗi giây; còi đợi ngón tay/đo hai tiếng ngắn rồi nghỉ1s, lặp lại.
