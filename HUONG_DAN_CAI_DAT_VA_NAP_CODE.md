# Hướng dẫn cài đặt, nạp ESP32 và chạy web Signal Lab

Cập nhật: 02/11/2026. Hướng dẫn cho Windows 10/11 64-bit, theo mã nguồn hiện tại trong repository.

## 1. Dự án hiện làm gì?

```text
MAX30102 + GY-906 → ESP32 → MQTT cloud/TLS → collector Python → MongoDB Atlas
                                                                  ↑
                                                 Streamlit trên máy người xem
```

- ESP32 thu **IR, RED, nhiệt độ vật thể và nhiệt độ môi trường**. Mỗi phiên có 1.500 cặp IR/RED ở đầu ra danh định 100 Hz (~15 giây), nhiệt độ khoảng mỗi giây.
- IR/RED là giá trị ADC quang học, không phải BPM hoặc SpO₂. Cảm biến đang được cấu hình lấy trung bình FIFO phần cứng; “dữ liệu thô” ở đây là đầu ra cảm biến, chưa qua thuật toán xử lý PPG của backend.
- Collector kiểm tra cấu trúc, phạm vi và thứ tự gói, loại trùng rồi lưu dữ liệu. Kiểm tra hợp lệ không phải tính nhịp tim hoặc chẩn đoán.
- Web hiển thị dữ liệu thô, biểu đồ, ngưỡng do người dùng đặt và xuất CSV. Các ngưỡng không phải ngưỡng chẩn đoán được xác nhận.
- Web hiện tính nhịp mạch, SpO₂ ước tính thử nghiệm và trung vị nhiệt độ bề mặt theo [ANALYSIS.md](iot_lab/ANALYSIS.md). SpO₂ chưa hiệu chuẩn; không có chẩn đoán bệnh. Có script tiền xử lý chạy riêng, giữ nguyên dữ liệu gốc.
- MQTT cloud và Atlas có thể truy cập qua Internet; **web vẫn chạy local** tại `http://127.0.0.1:8501`, chưa phải website công khai.

## 2. Chọn đúng vai trò trước khi cài

| Vai trò | Cần cài/cấu hình | Chương trình cần chạy |
|---|---|---|
| Người quản lý thiết bị và thu dữ liệu | Python, Arduino IDE, driver USB nếu cần, MQTT cloud, Atlas user ghi, thư viện dự án | Một collector và tùy chọn web |
| Người chỉ xem dữ liệu | Python, mã nguồn, Atlas URI chỉ đọc và IP được cho phép | Chỉ web |

Người chỉ xem làm **mục 3, 4 và 10**. Không cần ESP32, Arduino IDE, tài khoản MQTT, MongoDB Server trên máy hay collector.

Máy collector phải có Internet và được bật để nhận dữ liệu mới, ghi Atlas và trả ACK. Khi collector tắt, người xem vẫn đọc được dữ liệu đã lưu, còn ESP32 giữ phiên chưa được xác nhận trong flash.

## 3. Cài phần mềm trên Windows

### 3.1. Python

1. Tải bản Python Windows 64-bit từ [python.org](https://www.python.org/downloads/windows/). Môi trường phát triển đã dùng Python 3.14; không cần nâng cấp nếu `.venv` hiện tại đang chạy tốt.
2. Nếu dùng trình cài truyền thống có tùy chọn **Add Python to PATH**, bật tùy chọn đó.
3. Sau khi cài, mở PowerShell mới, kiểm tra:

```powershell
python --version
```

Nếu lệnh `python` không hoạt động nhưng máy có Python Launcher, thử `py --version` và dùng `py` thay cho `python` khi tạo môi trường ở mục 4. Các lệnh dùng `.venv\Scripts\python.exe` về sau không cần thay.

### 3.2. Git hoặc tải ZIP

Để clone, cài [Git for Windows](https://git-scm.com/downloads/win), mở PowerShell mới và chạy `git --version`.

Nếu không dùng Git, tải ZIP của repository và giải nén. Không chạy trực tiếp từ trong file ZIP. VS Code, MongoDB Compass và MQTTX là công cụ tùy chọn, không bắt buộc.

### 3.3. Arduino IDE — chỉ máy nạp ESP32

Cài [Arduino IDE 2.x](https://www.arduino.cc/en/software/). Không cần cài Arduino App Lab cho dự án này.

Cắm ESP32 bằng cáp USB **có truyền dữ liệu**. Nếu không thấy cổng COM trong Device Manager → Ports (COM & LPT), kiểm tra cáp và driver đúng chip USB trên board:

- CP210x: lấy driver VCP từ [Silicon Labs](https://www.silabs.com/developer-tools/usb-to-uart-bridge-vcp-drivers).
- CH340/CH341: lấy driver từ nhà sản xuất WCH hoặc nhà cung cấp board.
- Board có USB native hoặc chip USB khác: dùng hướng dẫn của đúng board; không cài ngẫu nhiên nhiều driver.

### 3.4. Những phần không cần cài trong phương án hiện tại

Không cần Docker, Mosquitto local, MongoDB Community Server local, Node.js hoặc ThingsBoard. MQTT dùng broker cloud, MongoDB dùng Atlas; mọi máy chạy Python vẫn cần cài các thư viện trong repository.

## 4. Lấy mã nguồn và cài thư viện Python

Ví dụ lưu repository tại `C:\Users\Admin\Desktop\IOT`. Máy khác thay đường dẫn bằng vị trí thực tế của mình.

Nếu clone mới, thay URL bên dưới bằng URL repository thật, không gõ nguyên phần `<...>`:

```powershell
cd C:\Users\Admin\Desktop
git clone <URL_REPOSITORY> IOT
cd IOT\iot_lab
```

Nếu đã có mã nguồn:

```powershell
cd C:\Users\Admin\Desktop\IOT\iot_lab
```

Tạo môi trường **chỉ khi chưa có `.venv`**, rồi cài thư viện:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Không cần chạy Activate.ps1 hoặc đổi Execution Policy: dùng trực tiếp đường dẫn Python trong `.venv`. Đừng copy `.venv` từ máy khác; hãy tạo lại trên máy đang dùng. `requirements.lock.txt` ghi phiên bản môi trường đã dùng, còn `requirements.txt` là danh sách cài đặt chính.

Nếu môi trường đã hoạt động thì bỏ qua bước tạo lại. Các thư viện chính gồm Streamlit, PyMongo, Paho MQTT, Pandas, NumPy, scikit-learn, Altair và python-dotenv.

## 5. MongoDB Atlas — máy quản lý dữ liệu

Nếu Atlas đã kết nối và `check_connection.py --init` đã thành công, không cần tạo cluster hoặc sửa lại URI.

### 5.1. Tạo cluster và tài khoản

1. Vào [MongoDB Atlas](https://www.mongodb.com/cloud/atlas), đăng nhập hoặc tạo tài khoản.
2. Tạo project, ví dụ `SIGNAL_LAB`; tạo cluster gói **Free**, ví dụ `SignalCluster`. Kiểm tra lựa chọn giá trước khi xác nhận.
3. Vào **Security → Database Access / Database Users**, tạo tài khoản database. Tài khoản database khác tài khoản đăng nhập trang Atlas.
4. Tạo `signal_writer` với role **readWrite** trên database **signal_lab** cho collector. Người quản trị dùng tài khoản có quyền quản lý schema khi cần đổi chính sách TTL của collection đã có; không cấp quyền quản trị cho người xem.
5. Tạo tài khoản chỉ đọc theo mục 10 khi cần chia sẻ web.

Xem [quản lý database user của Atlas](https://www.mongodb.com/docs/atlas/security-add-mongodb-users/).

### 5.2. Cho phép IP kết nối

Trong **Network Access → IP Access List**, thêm IP Internet công khai của máy collector bằng **Add Current IP Address**. Sau này thêm IP của từng máy xem.

Đây là IP Internet, không phải địa chỉ `192.168.x.x`. Khi đổi mạng/đổi IP công khai hoặc bật VPN, có thể cần cập nhật danh sách để khớp đường kết nối của Python. Không mặc định mở toàn bộ Internet chỉ để bỏ qua bước này. Xem [Atlas IP Access List](https://www.mongodb.com/docs/atlas/security/ip-access-list/).

### 5.3. Cấu hình `.env` của máy collector

1. Chọn cluster → **Connect → Drivers → Python**.
2. Copy chuỗi `mongodb+srv://...`, thay database username/password bằng giá trị thật.
3. Tại `iot_lab`, nếu chưa có `.env`, copy `.env.example` thành `.env`. **Không ghi đè `.env` đang có**, vì nó chứa cấu hình MQTT đã thiết lập.
4. Mở bằng trình soạn thảo và điền hai mục MongoDB:

```dotenv
MONGO_URI=mongodb+srv://signal_writer:URL_ENCODED_PASSWORD@YOUR_CLUSTER_HOST/?retryWrites=true&w=majority
MONGO_DB=signal_lab
RETENTION_DAYS=7
```

Các giá trị trên chỉ là mẫu. Dán hostname thực từ Atlas, không tự đoán. Nếu password có ký tự đặc biệt như `@`, `:`, `/`, `#`, `%`, hãy URL-encode phần password trong URI. Không thêm dấu `< >` vào giá trị cuối cùng. Xem [hướng dẫn kết nối Atlas](https://www.mongodb.com/docs/atlas/connect-to-database-deployment/).

Giữ nguyên các dòng MQTT khác. Không tải `.env` từ Atlas đè lên `.env` dự án.

Kiểm tra và tạo collection/index lần đầu:

```powershell
.\.venv\Scripts\python.exe check_connection.py --init
```

Kết quả cần thấy:

```text
OK: MongoDB connected. Database: signal_lab
OK: time-series collections and indexes ready
```

Database/collection chưa có sẽ được code tạo khi có đủ quyền. Không cần tạo collection thông thường thay cho các collection Time-Series bằng tay. Đổi URI từ local sang Atlas **không tự chuyển dữ liệu cũ**; hướng dẫn này chỉ cấu hình nơi lưu dữ liệu nhận tiếp theo.

`RETENTION_DAYS` mặc định là **7 ngày**: đây không phải lưu trữ vĩnh viễn. MongoDB thực hiện xóa TTL bất đồng bộ. Nếu cần lưu lâu hơn, người quản lý thay cấu hình và kiểm tra quyền cập nhật schema trước khi dùng.

## 6. MQTT Internet — máy collector và ESP32

Nếu `check_mqtt.py` đã báo OK và `MqttCloud.h` đang đúng, không cần cấu hình lại. Người chỉ xem web bỏ qua toàn bộ mục này.

### 6.1. Tạo broker riêng

1. Đăng nhập [EMQX Cloud Console](https://cloud-intl.emqx.com/).
2. Tạo project → **New Deployment / EMQX Broker + New → Serverless**.
3. Đặt **Monthly Spend Limit = 0** để chỉ dùng hạn mức miễn phí. Khi hết hạn mức broker có thể bị dừng; kiểm tra điều kiện gói trên giao diện trước khi xác nhận.
4. Đợi trạng thái Running. Trong Overview lấy **Address/Hostname**, **MQTT TLS port** (thường 8883) và tải **CA Certificate**.
5. Trong **Access Control → Authentication / Client Authentication**, tạo MQTT username/password. Đây không phải mật khẩu đăng nhập EMQX.
6. Nếu đặt Authorization/ACL riêng, tài khoản dùng cho pipeline cần quyền publish/subscribe các topic dữ liệu và ACK của dự án: `iot/+/raw`, `iot/+/ack`.

Xem [tài liệu tạo EMQX Serverless](https://docs.emqx.com/en/cloud/latest/create/serverless.html). Không dùng broker thử nghiệm công khai cho dữ liệu người đo thật hoặc ACK của thiết bị.

### 6.2. Điền cùng cấu hình cho Python và ESP32

Trong `iot_lab`:

```powershell
.\.venv\Scripts\python.exe configure_mqtt_cloud.py
```

Nhập theo thứ tự:

| Câu hỏi | Giá trị cần nhập |
|---|---|
| Broker hostname | Address lấy từ broker, không có `https://`, `mqtts://`, `:8883` hoặc đường dẫn |
| TLS port | Port TLS của broker, thường 8883 |
| MQTT username/password | Tài khoản MQTT đã tạo |
| Đường dẫn CA | Ví dụ `C:\Users\Admin\Downloads\emqxsl-ca.crt` |

Mật khẩu được nhập ẩn, không hiện dấu sao cũng là bình thường. Script giữ cấu hình MongoDB, cập nhật `.env`, sao chép CA vào `data/certs/` và tạo `firmware/HealthRawDirect/MqttCloud.h`. Nếu có `.env` cũ, script tạo bản sao `.env.before-cloud`.

Kiểm tra:

```powershell
.\.venv\Scripts\python.exe check_mqtt.py
```

Cần thấy `TLS=True` và `OK: MQTT connected and subscribed`. Kiểm tra này xác nhận kết nối và quyền subscribe, chưa chứng minh đủ gói cảm biến đã lưu MongoDB.

Mỗi collector cần client ID riêng; script tự tạo ID. Pipeline của thiết bị chỉ chạy **một collector**. Không phát tài khoản MQTT/ghi database cho mọi người cùng chạy collector, vì collector còn gửi ACK tới ESP32.

## 7. Chuẩn bị phần cứng

Phần cứng: ESP32 Dev Module/WROOM, MAX30102, GY-906/MLX90614, còi chủ động có GND/IO/VCC, cáp USB dữ liệu và dây nối.

Tắt nguồn trước khi đấu dây. Pin I²C của ESP32 dùng logic **3,3 V**. Điện áp cấp và pull-up phụ thuộc module thực tế; kiểm tra ký hiệu/thông số module. Không kéo SDA/SCL lên 5 V. Nếu mạch đang đo tốt, giữ cách cấp nguồn đã kiểm chứng.

| Module | Chân module | ESP32 / cách nối |
|---|---|---|
| MAX30102 | SDA | GPIO21 |
| MAX30102 | SCL | GPIO22 |
| MAX30102 | GND | GND |
| MAX30102 | VIN | 3V3 nếu module hỗ trợ cấp 3,3 V; nếu không, dùng nguồn đúng thông số và bảo đảm I²C 3,3 V |
| MAX30102 | INT | Không nối trong firmware hiện tại |
| GY-906 | SDA | GPIO21, chung bus với MAX30102 |
| GY-906 | SCL | GPIO22, chung bus với MAX30102 |
| GY-906 | GND | GND |
| GY-906 | VCC/VIN | Nguồn theo module, I²C tương thích 3,3 V; không mặc định mọi GY-906 đều cấp cùng điện áp |
| Còi chủ động | IO | GPIO25, yêu cầu module nhận được logic điều khiển 3,3 V |
| Còi chủ động | GND | GND chung |
| Còi chủ động | VCC | Nguồn theo thông số module còi |

Địa chỉ I²C firmware đang dùng: MAX30102 `0x57`, MLX90614 `0x5A`. Nếu MLX đã đổi địa chỉ thì cần sửa cấu hình tương ứng. Không cấp trực tiếp tải còi dòng lớn từ GPIO; dùng đúng module điều khiển phù hợp.

## 8. Arduino IDE và nạp firmware

### 8.1. Cài ESP32 core

Trong Arduino IDE:

1. **File → Preferences → Additional Boards Manager URLs**, thêm URL ổn định:

```text
https://espressif.github.io/arduino-esp32/package_esp32_index.json
```

2. Mở **Boards Manager**, tìm **esp32 by Espressif Systems** và cài. Dự án đã biên dịch với **3.3.12**; dùng phiên bản này khi cần tái lập.
3. Chọn board **ESP32 Dev Module** nếu dùng đúng dòng ESP32/WROOM tương ứng; board khác chọn đúng model. Không áp cấu hình WROOM cho ESP32-C3/S3 một cách mặc định.

Tham khảo [hướng dẫn Espressif](https://docs.espressif.com/projects/arduino-esp32/en/latest/installing.html).

### 8.2. Cài thư viện

Trong **Library Manager**, tìm và cài:

| Thư viện | Ghi chú |
|---|---|
| SparkFun MAX3010x Pulse and Proximity Sensor Library | Firmware dùng `MAX30105.h` để điều khiển MAX30102 |
| Adafruit MLX90614 Library | Đọc GY-906 |
| Adafruit BusIO | Chấp nhận cài dependency khi IDE hỏi |
| PubSubClient | MQTT |
| ArduinoJson | **7.x**, dự án đã dùng 7.4.3 |

WiFi, WiFiClientSecure, Wire, LittleFS và FreeRTOS đi kèm ESP32 core, không cần tìm thư viện ngẫu nhiên cùng tên trên Internet.

### 8.3. Tạo các header cấu hình riêng

Trong `firmware/HealthRawDirect`:

- Copy `WiFiConfig.example.h` thành **WiFiConfig.h**, điền Wi-Fi thật. Nếu đã có file đúng thì giữ lại.
- **MqttCloud.h** được script mục 6 tạo tự động; không cần thay các dòng `MQTT_SERVER = CLOUD_HOST` trong sketch.
- **FirmwareTypes.h** có sẵn trong repository; giữ nguyên để đọc được các phiên flash cũ.

Ví dụ nội dung WiFiConfig.h:

```cpp
#pragma once
const char* WIFI_SSID = "TEN_WIFI_CUA_BAN";
const char* WIFI_PASSWORD = "MAT_KHAU_WIFI_CUA_BAN";
```

ESP32/WROOM thông thường dùng Wi-Fi 2,4 GHz. Máy tính và ESP32 không cần chung Wi-Fi khi cùng truy cập được broker Internet. Đổi mạng chỉ đổi SSID/password của ESP32; hostname broker giữ nguyên.

Sau khi cấu hình, thư mục cần có:

```text
firmware/HealthRawDirect/
  HealthRawDirect.ino
  FirmwareTypes.h
  WiFiConfig.h          # riêng trên máy, Git bỏ qua
  MqttCloud.h           # riêng trên máy, Git bỏ qua
  WiFiConfig.example.h
  MqttCloud.example.h
```

### 8.4. Nạp

1. Mở **HealthRawDirect.ino trong đúng thư mục trên**. Không chỉ chép riêng `.ino` sang sketch khác rồi bỏ các header.
2. Kiểm tra `DEVICE_ID` (mặc định `esp32-01`), GPIO và `BUZZER_ON_LEVEL` ở đầu sketch. Module còi hiện dùng **LOW** để bật; module kích HIGH thì đổi thành HIGH.
3. Trong **Tools → Port**, chọn COM của ESP32. Rút/cắm lại để nhận diện nếu có nhiều COM.
4. Board/Flash Size phải phù hợp phần cứng. Dùng partition có filesystem; ví dụ ESP32 4 MB có thể dùng **Default 4MB with SPIFFS**, LittleFS sử dụng partition nhãn `spiffs`. Nếu đã có dữ liệu offline thì **giữ nguyên partition đang dùng**.
5. **Erase All Flash = Disabled**. Bấm **Verify** để kiểm tra, rồi **Upload** (mũi tên) để thực sự nạp. Verify không nạp firmware.
6. Nếu upload đứng ở Connecting, thử giữ BOOT khi bắt đầu kết nối, thả khi đang ghi; một số board tự vào bootloader nên không cần thao tác này. Đóng chương trình khác đang chiếm COM.
7. Chờ upload thành công, mở Serial Monitor **9600 baud**, bấm RESET/EN.

### 8.5. LittleFS lần đầu

Nếu hiện `LittleFS chua mount duoc` và đây là **lần đầu chưa có dữ liệu cần giữ**, chọn line ending **Newline** hoặc **Both NL & CR**, nhập `FORMAT` rồi Send. Cần thấy `LittleFS OK`.

Nếu từng lưu phiên chờ mà mount lỗi: **không FORMAT**. Format, đổi partition hoặc Erase All Flash có thể xóa dữ liệu. Lỗi mạng không cần format.

## 9. Chạy hệ thống thu dữ liệu

### 9.1. Hai terminal trên máy collector

Terminal 1, tại `iot_lab`:

```powershell
.\run_collector.bat
```

Đợi `MQTT subscribed to iot/+/raw`. Giữ terminal mở, có thể thu nhỏ; đóng hoặc Ctrl+C sẽ dừng chương trình. Không chạy thêm collector thứ hai.

Terminal 2, tại `iot_lab`:

```powershell
.\run.bat
```

Mở `http://127.0.0.1:8501`. Trong thanh bên chọn **MongoDB**, không chọn Minh họa nếu cần dữ liệu thật. Chọn thiết bị `esp32-01` và phiên. Thiết bị chỉ xuất hiện khi đã có ít nhất một gói trong database.

### 9.2. Trình tự ESP32 và còi

| Tình huống | Hành vi |
|---|---|
| Không có phiên chờ | `NO PENDING`, bắt đầu chờ ngón tay/đo |
| Có phiên cũ | `REPLAY FIRST`, gửi hết mới `REPLAY DONE` và chuyển sang đo |
| Chưa gửi hết phiên cũ | `REPLAY PENDING`, giữ flash rồi sleep, không đo thêm dù còn chỗ |
| Đang chờ ngón tay/đo | Hai tiếng100ms, cách nhau100ms, rồi nghỉ1000ms; lặp lại |
| Đang gửi/chờ ACK | Một tiếng150ms mỗi1000ms |
| Gửi hết phiên mới | Kêu dài2s, tắt còi và sleep |
| Offline/còn dữ liệu sau lượt gửi | Hai tiếng ngắn rồi sleep |
| Lỗi | Ba tiếng ngắn rồi sleep |

Giữ ngón tay ổn định trên MAX30102, bố trí GY-906 đo đúng đối tượng cần ghi nhiệt độ. Nếu nhấc tay hoặc có lỗi lấy mẫu, phiên RAM sẽ thu lại. `F=1` là IR trên ngưỡng, `T=1` là nhiệt độ hợp lệ theo kiểm tra code, không phải xác nhận sức khỏe hay chất lượng tín hiệu lâm sàng.

Log thành công điển hình:

```text
TRANSPORT: MQTT_CLOUD_TLS_V1
CAPTURE DONE: 1500 cap, ... lan nhiet do. Dang luu flash...
FLASH SAVED. Co the gui lai sau RESET/mat nguon.
MQTT connected=1
ACK esp32-01-... 1/30 (50 cap)
...
ACK esp32-01-... 30/30 (50 cap)
Da xac nhan du 1500 cap; xoa file da gui.
SUCCESS: tat ca phien da du ACK.
SLEEP. Bam RESET hoac tat/bat nguon de chay lai.
```

Một ACK nghĩa là collector đã xác nhận ghi bền vững gói đó vào MongoDB. Chỉ đủ30 ACK mới xóa file phiên. Publish thành công hoặc MQTT connected chưa đủ chứng minh lưu toàn bộ phiên.

Mỗi lượt replay/upload có ngân sách300s; một gói không có ACK sau khoảng30s thì dừng sớm. Giữ tối đa8 phiên; không ghi đè phiên chưa ACK. Phiên đã ghi hoàn tất vào LittleFS giữ qua mất nguồn; đang thu trong RAM thì có thể mất nếu tắt nguồn. Reset/bật lại sẽ gửi lại an toàn nhờ loại trùng phía Python. Không có timer tự đánh thức sau sleep.

TLS cần giờ NTP hợp lệ; nếu mạng chặn NTP hoặc port broker, thiết bị giữ dữ liệu thay vì bỏ kiểm tra chứng chỉ. GY-906 có thể vẫn được cấp điện khi ESP32 sleep; MAX được shutdown, không phải cắt nguồn toàn bộ mạch.

Trong Atlas có thể kiểm tra `signal_lab.raw_inbox` và `signal_lab.raw_timeseries`. Nếu web không có thiết bị mới, tải lại cả trang để cập nhật danh sách thiết bị/phiên. Tự cập nhật biểu đồ không nhất thiết tạo lại các lựa chọn ngoài biểu đồ.

## 10. Người khác clone và chỉ xem web

### 10.1. Người quản lý chuẩn bị

1. Trong Atlas tạo user riêng, ví dụ `signal_reader`, role **read trên signal_lab**. Có thể cấp user riêng cho từng người để dễ thu hồi.
2. Thêm IP Internet của máy người xem vào IP Access List.
3. Gửi riêng URI chỉ đọc; không commit URI có mật khẩu lên Git. Không gửi tài khoản writer, Atlas Admin hoặc MQTT cho người chỉ xem.

### 10.2. Trên máy người xem

Làm mục3 và4 để cài Python, clone và cài `requirements.txt`. Trong `iot_lab`, tạo file `.env` chỉ cần:

```dotenv
MONGO_URI=mongodb+srv://signal_reader:URL_ENCODED_PASSWORD@YOUR_CLUSTER_HOST/?retryWrites=true&w=majority
MONGO_DB=signal_lab
```

Không dùng `.env` chứa tài khoản writer của người quản lý. Kiểm tra kết nối bằng lệnh **không có --init**:

```powershell
.\.venv\Scripts\python.exe check_connection.py
.\run.bat
```

Chọn nguồn **MongoDB**, thiết bị và phiên. Mọi người đọc cùng dữ liệu Atlas đã được cấp quyền. Không cần cài MongoDB Server, Arduino IDE hoặc cấu hình MQTT; không chạy `configure_mqtt_cloud.py`, collector, preprocess hoặc `check_connection.py --init` với user chỉ đọc.

Nếu máy người quản lý tắt, dữ liệu đã lưu vẫn xem được khi Atlas hoạt động và chưa bị xóa theo TTL. Muốn có dữ liệu mới, collector của người quản lý phải chạy. Cách này không cho người chưa được cấp quyền/IP tự xem chỉ bằng URL localhost của máy khác.

## 11. Tiền xử lý tùy chọn và kiểm thử

Chỉ chạy tiền xử lý bằng tài khoản được phép ghi:

```powershell
.\.venv\Scripts\python.exe preprocess.py --device esp32-01 --session MA_PHIEN_THAT
```

Thay `MA_PHIEN_THAT` bằng session ID từ web. Script tạo rolling mean, delta, MinMax và cờ ngoại lệ IQR ở dữ liệu xử lý riêng; không sửa raw, không nội suy PPG qua đoạn mất mẫu, không đưa ra chẩn đoán. Web có tab **Tiền xử lý** để xem kết quả đã tạo.

Kiểm thử phần mềm:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

Nếu cần thử pipeline không dùng mạch, máy collector có thể chạy `simulate.py --realtime` khi collector đang bật. Nó ghi dữ liệu giả dưới thiết bị **simulator**, không phải số đo người thật. Không dùng kết quả mô phỏng để xác nhận cảm biến hoạt động.

## 12. Lỗi thường gặp

| Lỗi/hiện tượng | Kiểm tra |
|---|---|
| Python không nhận lệnh | Mở terminal mới, kiểm tra PATH hoặc thử `py`; sau đó dùng Python trong `.venv` |
| Không có `.venv\Scripts\python.exe` | Đang ở đúng `iot_lab` chưa; tạo `.venv` và cài requirements |
| ModuleNotFoundError | Cài requirements bằng chính Python trong `.venv`, không dùng pip của môi trường khác |
| Không thấy COM | Cáp dữ liệu, cổng USB, Device Manager, driver đúng chip |
| Thiếu FirmwareTypes.h/WiFiConfig.h/MqttCloud.h | Mở đúng sketch, giữ header cùng thư mục; file cấu hình riêng không đi theo Git, phải tạo |
| ArduinoJson lỗi API | Dùng ArduinoJson7.x theo firmware hiện tại |
| LittleFS mount failed | Chỉ FORMAT ở lần đầu không có dữ liệu cần giữ; kiểm tra partition, không format để sửa mạng |
| MQTT Bad user name or password | Kiểm tra MQTT user trên đúng deployment, chạy lại script cấu hình rồi check_mqtt; không dùng mật khẩu web EMQX |
| MQTT state=-2 | Kiểm tra hostname/port, Internet, DNS, CA, giờ NTP và mạng có chặn8883 không; không dùng IP LAN cũ |
| Đèn MAX chưa sáng lúc bật | Có thể đang gửi backlog trước khi khởi tạo cảm biến; xem REPLAY FIRST/PENDING/DONE |
| F=0 khi đặt tay | Xem IR thực tế, nguồn/dây/vị trí ngón tay; ngưỡng mặc định50000 không phù hợp mọi module |
| Có FLASH SAVED nhưng chưa ACK | Kiểm tra một collector đang chạy, đúng broker, có quyền đọc/ghi Atlas, database kết nối được |
| Có ACK nhưng web không thấy | Web và collector phải cùng Atlas host và MONGO_DB; chọn MongoDB, tải lại trang, chọn đúng thiết bị/phiên/khoảng thời gian |
| Atlas authentication failed | Database user/password, URL-encoding trong URI, không dùng mật khẩu đăng nhập Atlas |
| Atlas timeout/DNS | IP Access List, VPN/đường mạng, cluster trạng thái hoạt động, DNS cho SRV và kết nối Internet |
| User reader chạy --init bị từ chối | Reader chỉ chạy check_connection không --init và web; khởi tạo bằng writer/người quản lý |
| Web dừng sau đóng terminal | Giữ terminal Streamlit mở; localhost chỉ tồn tại khi chương trình đang chạy |
| Cổng8501 đang dùng | Dừng bản web cũ bằng Ctrl+C hoặc chạy `.\.venv\Scripts\python.exe -m streamlit run web.py --server.port 8502` tại iot_lab |
| Đổi sang Atlas nhưng mất lịch sử cũ | Dữ liệu local không tự di chuyển; vẫn nằm ở MongoDB local cũ, cần kế hoạch chuyển riêng |

Các thông báo gợi ý “kiểm tra MongoDB Windows Service” trong công cụ cũ áp dụng cho phương án local; khi dùng Atlas hãy kiểm tra URI, IP Access List, tài khoản và trạng thái cluster trước.

## 13. File được chia sẻ qua Git

Đưa mã nguồn, README/tài liệu, tests, requirements và **file mẫu** lên Git. Git đã bỏ qua:

- `.env`, `.env.before-cloud` và các cấu hình `.env.*` riêng.
- `firmware/HealthRawDirect/WiFiConfig.h` và `MqttCloud.h`.
- `.venv/`, `__pycache__/`, dữ liệu/log trong `iot_lab/data/` và file biên dịch.

Người clone dùng `WiFiConfig.example.h`, `MqttCloud.example.h` và `.env.example` làm mẫu, rồi tự lấy quyền truy cập phù hợp. Đổi mật khẩu nếu đã vô tình công khai; xóa khỏi file mới không loại được mật khẩu trong lịch sử Git cũ.

Có thể kiểm tra trước khi commit:

```powershell
git status --short
git check-ignore iot_lab/.env firmware/HealthRawDirect/WiFiConfig.h firmware/HealthRawDirect/MqttCloud.h
```

## 14. Trình tự dùng lại mỗi ngày

**Máy quản lý:** mở collector → mở web nếu cần → bật/RESET ESP32 → chờ gửi backlog → đo → chờ đủ ACK và sleep. Không cần tạo lại broker, cluster, `.venv`, CA hay FORMAT mỗi lần sử dụng.

**Máy chỉ xem:** có Internet/IP được phép → chạy `run.bat` → chọn MongoDB và phiên.

**Sau khi đổi `.env`:** khởi động lại collector/web tương ứng. **Sau khi đổi firmware/header:** Upload lại, không xóa flash. Nhớ kiểm tra firmware thực tế trên board; kiểm thử phần mềm và compile không chứng minh độ chính xác đo trên phần cứng.
