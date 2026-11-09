# Nạp và thử thiết bị đeo cổ

Bản này chạy liên tục. RESET yêu cầu một lượt đo, đo xong quay về giám sát; không deep sleep. Giữ nút SOS hai giây để hủy/tắt **báo động**, không tắt nguồn.

## Chân đã chọn

- SDA cả ba cảm biến: GPIO21; SCL: GPIO22; GND chung.
- GY-521: VCC -> 3V3, AD0 -> GND; XDA/XCL/INT bỏ trống.
- LED đỏ -> GPIO26; xanh lá -> GPIO27; xanh dương -> GPIO32. Mỗi LED: GPIO -> điện trở 330 ohm -> chân dương LED, chân âm -> GND.
- Nút SOS hai chân: GPIO33 và GND, dùng kéo lên nội.
- Còi: I/O -> GPIO25; giữ nguồn module đã kiểm chứng. Code đang kích LOW.

## Nạp

Mở HealthRawDirect.ino ngay trong thư mục này; các header phải ở cùng thư mục. Không phải cài thêm thư viện MPU6050. Giữ WiFiConfig.h và MqttCloud.h hiện có.

Chọn ESP32 Dev Module/WROOM đúng phần cứng, Upload Speed 115200 nếu tốc độ cao lỗi, giữ partition cũ, Erase All Flash Disabled. Bấm Upload. Serial Monitor 9600 baud. Không FORMAT hoặc xóa NVS để sửa lỗi mạng.

## Chạy máy tính

Dừng collector cũ bằng Ctrl+C, chỉ chạy một collector. Terminal 1:

```bash
cd /Users/m1/Desktop/IOT/iot_lab
.venv/bin/python collector.py
```

Terminal 2:

```bash
cd /Users/m1/Desktop/IOT/iot_lab
.venv/bin/python -m streamlit run web.py
```

Web: http://127.0.0.1:8501 -> MongoDB. Bảng cảnh báo hiện cả khi chưa có phiên đo. Tài khoản database trên web phải có quyền ghi nếu muốn yêu cầu tắt báo động.

Nếu broker có ACL chỉ cho raw/ack, bổ sung quyền cho `iot/esp32-01/event`, `iot/esp32-01/event_ack`, `iot/esp32-01/command` theo chiều publish/subscribe ở README.md. Thiết bị khác thay esp32-01 bằng DEVICE_ID thật.

## Thử theo thứ tự

1. Đọc Serial: cần có `WEARABLE`, `READY`, rồi các dòng `IMU g=... dps=...`. Đặt yên, tổng độ lớn gia tốc khoảng 1g; xoay nhẹ thì tốc độ góc thay đổi. `MPU ERROR` là chưa đọc được cảm biến, không phải đã theo dõi tốt. Bản chẩn đoán mới in `I2C SCAN` khi khởi động, bus/WHO_AM_I khi lỗi và `LED OUT` để đối chiếu đấu dây. Đỏ chỉ dành cho chờ hủy/báo động; không dùng đỏ báo lỗi MPU.
2. Chạm nút SOS rồi thả: LED đỏ và còi chớp ngay. Giữ 2 giây: tắt báo động, vẫn giám sát. Web phải nhận SOS và sau đó nhận trạng thái đã tắt.
3. RESET, gửi hết dữ liệu cũ rồi đặt ngón tay đo. Xanh dương sáng lúc chờ/đo, xanh lá nháy 150ms sáng/850ms tắt lúc gửi. Đủ ACK 30/30 thì giữ máy chạy, không sleep.
4. Thử tắt từ web: bấm Yêu cầu tắt báo động. Chưa có xác nhận ESP32 thì chỉ hiển thị đang chờ. Collector phải bật.
5. Thử mất Internet: SOS vẫn báo tại chỗ; RESET phải phục hồi báo động. Có mạng thì gửi lại cùng ID, không tạo lịch sử trùng. Giữ nút 2 giây để tắt; phải gửi hết sự kiện/phiên chờ rồi mới đo lượt mới.

## Mô phỏng ngã qua Serial (không thả rơi thiết bị)

Trong WearableConfig.h, đổi `ENABLE_SERIAL_SIMULATION=false` thành `true` rồi Upload. Chọn line ending Newline. Gửi:

```text
SIM_FALL
```

LED đỏ nháy, còi im trong 6 giây. Giữ nút 2 giây để hủy. Không hủy thì sau 6 giây bật còi/đỏ và gửi sự kiện. `SIM_SOS` thử báo động ngay. Sau khi thử đổi lại false và Upload.

Lệnh SIM chỉ kiểm tra báo động, lưu trữ và mạng, **không kiểm chứng thuật toán nhận dạng chuyển động**. Kiểm thử C++ dùng chuỗi dữ liệu tổng hợp để kiểm tra logic. Kiểm tra người thật phải dựa trên dữ liệu thực tế, không yêu cầu người cao tuổi ngã để thử.

## Ngưỡng thử nghiệm

WearableConfig.h: lowG 0.65g, impact 2.5g, tốc độ quay 150 độ/s, thay đổi hướng 45 độ; sau va chạm cần 800ms tương đối đứng yên trong cửa sổ 3 giây. Cửa sổ từ chuyển động đến va chạm 1 giây. Các số này là điểm khởi đầu kỹ thuật do người dùng đồng ý thử, không phải ngưỡng đã được nghiên cứu xác nhận cho vòng cổ.

Đồng hồ chờ hủy 6 giây bắt đầu sau khi chuỗi nhận dạng hoàn tất. Hộp đung đưa hoặc bị thả có thể báo nhầm; ngã chậm/trượt có thể bị bỏ sót. Cần ghi các hoạt động thường ngày và hiệu chỉnh. Bộ đệm cảnh báo hữu hạn 32 bản ghi trong NVS (định dạng V3 mã hóa rõ từng trường, chỉ ghi các bản ghi đang chờ); không ghi đè dữ liệu chưa ACK, đầy sẽ báo lỗi và chờ gửi bớt. Xem README.md về giới hạn và hướng nghiên cứu.

## Module trả ID 116 và lỗi mạng

116 thập phân = 0x74: code hỗ trợ theo cấu hình MPU6515/họ MPU6500, không bỏ kiểm tra ID tùy ý. Sau khi nạp cần thấy `MPU OK: MPU6515 WHO_AM_I=0x74`, rồi dữ liệu IMU. `NET DIAG: DNS FAIL` là chưa phân giải tên; `TCP8883=FAIL` là chưa mở được kết nối TCP; TCP OK nhưng MQTT lỗi cần xét TLS/CA/giờ và log ESP32. LED BLUE32=0 mà đèn vẫn sáng thì kiểm tra lại đấu LED về GND; đỏ sáng do báo động được lưu thì giữ SOS 2 giây để tắt.

## Lỗi journal CRC/schema và NTP WAIT

Bản mới tự chuyển các journal cũ 16/32 bản ghi có CRC hợp lệ sang khóa `journal_v3`, giữ nguyên khóa `journal` gốc. Cần thấy `JOURNAL MIGRATED V3` hoặc `JOURNAL V3 OK`. Nếu vẫn lỗi, gửi dòng `JOURNAL READ` từ đầu log; không FORMAT/xóa NVS.

Nếu NTP WAIT liên tục, có thể thử đặt giờ thủ công từ máy Mac tin cậy: Terminal chạy `date +%s`, copy số vừa hiện. Serial Monitor chọn Newline, gửi `TIME ` rồi số đó (có một dấu cách), ví dụ dạng `TIME <số vừa lấy>` nhưng không gõ dấu ngoặc. Cần thấy `TIME SET manually`. Sau đó mạch mới có thể thử MQTT/TLS; vẫn phải nhận đủ ACK dữ liệu cũ mới đo tiếp. Nếu còn lỗi, gửi `NET DIAG`/`TLS ERROR`.

## Không có phiên MAX30102/nhiệt độ mới

`IMU g=...` là log Serial của gia tốc/con quay, không phải gói MAX30102 gửi lên MQTT. Bộ nhận chỉ lưu cảnh báo ngã/SOS khi có sự kiện. `MEASUREMENT INIT` kiểm tra MAX/MLX và cấu hình mẫu. `MEASUREMENT BLOCKED` cho biết lỗi lưu trữ/cảm biến; `MEASUREMENT WAIT` cho biết báo động hoặc sự kiện chưa ACK. Chỉ khi có `CAPTURE`, `samples=.../1500`, `CAPTURE DONE`, `FLASH SAVED`, ACK 1/30...30/30 mới xác nhận lượt đo đầy đủ. Log IR có thêm objectC/ambientC. Khi web đang chọn 24 giờ, phiên cũ hơn không hiện; chọn 168 giờ để xem lịch sử trong tuần. Không bỏ qua lỗi journal để ép đo; cần đọc dòng storageReady/schemaValid/encoded/written/freeEntries và JOURNAL READ từ lúc boot.

## MQTT -4 và hàng đợi cảnh báo

`MQTT state=-4` là quá thời gian chờ phản hồi MQTT CONNECT/CONNACK. Bản mới chờ 15 giây thay vì 2, nhường CPU khi chưa có byte và nghỉ 10 giây sau mỗi lần thử thất bại. Bộ nhận MQTT/collector phải online. `TLS STATUS: result=48` là giá trị socket dương của ESP32 core, không phải mã lỗi chứng chỉ; chỉ mã TLS âm được in là lỗi. `EVENT SENT` chưa chứng minh đã lưu; cần `EVENT ACK: ... pending=...` giảm dần tới 0. Khi `alarm=0`, sự kiện và phiên cũ đã ACK hết, mạch mới bắt đầu lượt đo đang chờ. Nếu vẫn `MQTT CONNACK TIMEOUT` ở 15 giây, gửi log để kiểm tra đường mạng/broker; tăng timeout không đảm bảo giải quyết mọi nguyên nhân.

## LED sáng sai màu hoặc sai trạng thái

Báo động/chờ hủy ưu tiên đỏ, tắt xanh lá và xanh dương. Gửi dữ liệu dùng xanh lá nháy; chờ/đo MAX dùng xanh dương khi không báo động và không gửi. Mức bật mặc định 1 (HIGH), tương ứng GPIO -> điện trở -> chân dương LED, chân âm -> GND. Không tự đảo mức nếu chưa xác định dây.

Nạp firmware mới, Serial 9600 Newline. Giữ SOS 2 giây để tắt báo động rồi gửi `LED_TEST`. Trong 5 giây, quan sát: tất cả tắt -> chỉ đỏ GPIO26 -> chỉ xanh lá GPIO27 -> chỉ xanh dương GPIO32 -> tất cả tắt, mỗi bước một giây. SOS/ngã vẫn hoạt động, báo động sẽ hủy bài test và ưu tiên đỏ. Bài test chỉ đổi đèn trong 5 giây, không phải trạng thái đo/gửi bình thường. Nếu ALL_OFF mà LED sáng, kiểm tra đầu còn lại đang về GND hay 3V3. Nếu RED_ONLY sáng màu khác, kiểm tra dây/chân bị đổi. Nếu GPIO đúng nhưng LED không sáng, kiểm tra cực LED, hàng breadboard, điện trở và GND chung. Gửi dòng `LED STATUS` và màu thực tế ở từng bước; chưa đổi LED_*_ON_LEVEL khi chưa xác nhận cách đấu.
