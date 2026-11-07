# Firmware ESP32 — HealthRawDirect

ESP32 Dev Module/WROOM, MAX30102, GY-906/MLX90614 và còi chủ động. Gửi MQTT Internet qua TLS, xác nhận lưu MongoDB rồi chờ online để nhận nhắc đo.

Bản mới thêm `control`/`control_ack`, còi nhắc đến giờ/bỏ lịch và đo lại sau khi nhấc/đặt tay. Xem [hướng dẫn đầy đủ](../../docs/LICH_DO_VA_THONG_BAO.md). Bản firmware mới chưa được biên dịch/kiểm chứng trên mạch trong lần chỉnh sửa này do CLI thiếu ESP32 core; số liệu build cuối tài liệu là của bản cũ.

## Đấu dây và thư viện

Hai cảm biến dùng chung SDA GPIO21, SCL GPIO22 và GND. Kiểm tra đúng điện áp cấp và mức logic của module thực tế. Còi: IO GPIO25, GND chung; cấp VCC theo thông số module. Mức kích hiện tại LOW, đổi `BUZZER_ON_LEVEL` nếu module khác.

Arduino IDE: ESP32 core 3.3.12 đã được dùng để biên dịch; thư viện SparkFun MAX3010x, Adafruit MLX90614 + BusIO, PubSubClient, ArduinoJson 7.x. WiFiClientSecure, LittleFS và FreeRTOS có sẵn trong ESP32 core.

## Cấu hình và nạp

1. Copy `WiFiConfig.example.h` thành `WiFiConfig.h`, điền SSID/password. Giữ file sẵn có nếu máy đã cấu hình.
2. Chạy `iot_lab/configure_mqtt_cloud.py` theo [hướng dẫn MQTT Internet](../../iot_lab/MQTT_INTERNET.md). Script tạo `MqttCloud.h` với hostname, TLS port, MQTT credentials và CA. `MqttCloud.example.h` chỉ là mẫu.
3. Mở `HealthRawDirect.ino`, giữ **FirmwareTypes.h, WiFiConfig.h, MqttCloud.h** cùng thư mục.
4. Chọn board phù hợp và partition có filesystem. Khi đang giữ dữ liệu offline, không đổi partition và giữ **Erase All Flash = Disabled**.
5. Upload; Serial Monitor **9600 baud**. Broker hostname không cần đổi khi đổi Wi-Fi; SSID/password đổi trong `WiFiConfig.h`.

Hai header chứa cấu hình riêng bị Git bỏ qua. Không đưa mật khẩu vào sketch hoặc file mẫu. Giữ DEVICE_ID `esp32-01` nếu tiếp tục dùng cùng thiết bị; ngưỡng IR cần phù hợp tín hiệu thực tế.

### Khởi tạo LittleFS lần đầu

Code không tự format khi mount thất bại. Chỉ khi đây là lần đầu và chưa có dữ liệu cần giữ: chọn line ending Newline hoặc Both NL & CR, nhập `FORMAT` rồi Send. Nếu đã có phiên chờ thì không FORMAT; kiểm tra flash/partition trước. Đổi partition hoặc Erase All Flash có thể xóa dữ liệu.

## Luồng chạy

1. Kiểm tra CRC/schema các file flash. File lỗi được giữ, báo lỗi và không đo mới.
2. Không có phiên cũ: vào chờ online. Có phiên cũ: `REPLAY FIRST`, thử gửi trước. Chưa gửi hết thì giữ file và chờ online, thử lại mỗi 30s; không đo mới khi còn backlog.
3. Đợi IR trên ngưỡng ổn định1s và đọc được nhiệt độ. Thu1500 cặp IR/RED ở đầu ra danh định100Hz (~15s), nhiệt độ khoảng1Hz, ít nhất5 lần hợp lệ. Không cần BPM hợp lệ.
4. Nhấc tay, lỗi I2C/FIFO hoặc service gap>100ms: bỏ phiên RAM đang thu và bắt đầu lại. Không chạy Wi-Fi hoặc ghi flash trong lúc thu.
5. Dừng MAX, ghi cả phiên vào file .tmp, flush/close và kiểm tra CRC/schema trước khi rename .ready.
6. Mỗi phiên gửi30 gói ×50 cặp. Mỗi gói chờ đúng ACK topic/session/batch/sample_count/saved; chưa ACK thì gửi lại cùng nội dung sau2s. Ghi MongoDB bền vững mới ACK, publish() thành công chưa đủ.
7. Chỉ xóa file sau30 ACK. Reset trước khi xóa có thể gửi lại; collector loại trùng theo device/session/batch.
8. Gửi hết phiên mới: kêu dài2s rồi quay về chờ online. Nhấc tay rồi đặt lại để đo tiếp, không cần RESET. Trong lúc thu ngắt Wi-Fi; khi chờ kết nối MQTT để nhận nhắc. Lỗi nghiêm trọng vẫn báo còi và deep sleep.

Mỗi lượt replay/upload tối đa300s; một gói chờ ACK tối đa30s rồi dừng sớm nếu không có tiến triển. Giữ tối đa8 phiên (~100KB dữ liệu phiên). Không ghi đè phiên chưa ACK. TLS kiểm tra CA/hostname; đồng bộ giờ NTP qua Internet trước khi kết nối, không dùng setInsecure.

## Còi

| Trạng thái | Nhịp |
|---|---|
| Gửi dữ liệu/chờ ACK | Kêu150ms mỗi1000ms |
| Chờ ngón tay/thu mẫu | Kêu100ms → nghỉ100ms → kêu100ms → nghỉ1000ms, lặp lại |
| Hoàn tất toàn bộ | Kêu dài2s rồi chờ online |
| Offline/còn phiên chưa gửi | Hai tiếng ngắn, giữ file và thử gửi lại |
| Đến giờ đo | Một tiếng 200ms mỗi2s, trong10s |
| Bỏ lịch đo | Hai tiếng ngắn mỗi2s, trong10s |
| Lỗi | Ba tiếng ngắn rồi tắt và sleep |

Task còi độc lập, không thêm delay chặn luồng thu mẫu.

## Offline và kiểm tra trên mạch

Chỉ phiên đã ghi hoàn tất vào flash mới giữ qua mất nguồn. Tắt nguồn lúc đang thu có thể mất phiên RAM hiện tại. File .tmp hoàn chỉnh có CRC hợp lệ được khôi phục; file dở dang được giữ để kiểm tra. Deep sleep không cắt nguồn vật lý module: MAX shutdown, GY-906 có thể vẫn được cấp điện.

Bật MongoDB và collector Python trước khi gửi. Cần thấy `TRANSPORT: MQTT_CLOUD_TLS_V1`, `MQTT connected=1`, ACK1/30…30/30, rồi `Da xac nhan du 1500 cap; xoa file da gui.` Web chọn MongoDB → esp32-01.

Kiểm tra các tình huống: có backlog + collector tắt phải giữ file và không đo đè; có backlog + đủ ACK phải gửi xong trước CAPTURE; không backlog phải ONLINE IDLE, nhận nhắc MQTT, đặt tay để đo; nhấc tay giữa thu phải DO LAI. Không FORMAT để thử lỗi mạng.

Bản xử lý backlog/còi đã biên dịch: chương trình1106714 byte (84%), RAM tĩnh62492 byte (19%), Arduino-ESP32 3.3.12. Sau khi tách Wi-Fi ra header riêng, giá trị cấu hình và thuật toán giữ nguyên. Nhịp còi và các nhánh mới cần kiểm chứng trên mạch thật.
