# Phân tích phiên IR/RED và nhiệt độ trên web

Phiên bản `ppg-research-v1`, ngày02/11/2026. Thuật toán trong `physiology.py` chạy khi xem web, dùng raw từ MongoDB; không yêu cầu quyền ghi Atlas và không sửa firmware. Không ghi đè raw hoặc tự lưu các ước tính vào database. Có thể tải JSON phân tích trên tab Dữ liệu thô.

## 1. Nhiệt độ: dùng trung vị, không dùng mẫu cuối hoặc lấy cực đại

Với15 lần đọc, dùng **trung vị các mẫu vật thể hợp lệ**, đếm theo `temperature_at_ms` để một phép đọc được gửi lại trong nhiều gói không bị tính nhiều lần. Chấp nhận số lần đọc thực tế của phiên, không giả thêm để đủ15.

Hiển thị thêm số mẫu, min/max, IQR và trung bình trong chi tiết. Không âm thầm bỏ các mẫu lệch bằng IQR. Trung vị giảm ảnh hưởng của vài mẫu lệch; min/max làm chúng vẫn nhìn thấy. Ví dụ14 mẫu34,2°C và một mẫu80°C: trung vị34,2°C, còn trung bình~37,25°C. Cần kiểm tra mẫu80, không kết luận nó là giá trị sinh lý thật hoặc giả chỉ từ thống kê.

Tiêu chí “dao động nhỏ” khởi đầu: ít nhất5 lần đọc hợp lệ, IQR≤0,3°C và max−min≤1°C. Đây là tiêu chí kỹ thuật do dự án đề xuất, chưa phải chuẩn y tế; cần điều chỉnh dựa trên dữ liệu kiểm chứng.

Nhiệt độ GY-906 là **nhiệt độ vật thể/bề mặt**. Median không biến nó thành thân nhiệt. Nhiệt độ môi trường được thống kê riêng, không trộn vào nhiệt độ vật thể. Chưa có hiệu chuẩn thân nhiệt nên không áp37,5/38°C hoặc ngưỡng hạ thân nhiệt lên số đo này; không cộng một offset tùy ý.

## 2. Nhịp mạch và SpO₂

Chỉ phân tích phiên đủ và liên tục, ít nhất8s; dùngFs từ metadata. Từ chối mẫu thiếu/chồng/không hữu hạn, ADC chạm biên hoặc đoạn phẳng≥0,2s. Các cổng chất lượng là engineering baseline, có thể từ chối cả một số phép đo sinh lý thật, cần kiểm chứng tỷ lệ từ chối.

Nhánh xử lý: detrend → Butterworth band-pass0,5–5Hz zero-phase → bỏ0,75s ở hai biên khi ước tính → dò đỉnh hai cực tính và đối chiếu autocorrelation. Khoảng mô hình30–240bpm; ngoài khoảng không đồng nghĩa bình thường. Đây là baseline peaks+autocorrelation của dự án, **không tuyên bố đã triển khai nguyên thuật toán Elgendi/MSPTD**.

- Nhịp mạch: `60/median(IBI_seconds)`. Cần ít nhất5 đỉnh để kiểm tra.
- Kiểm tra khởi đầu: autocorrelation≥0,5; sai khác giữa peak/auto không quámax(5bpm,10%); CV của IBI≤0,25. Biến thiên mạnh có thể do tín hiệu hoặc nhịp thực; code không chẩn đoán nguyên nhân.
- DC là trung bình raw. AC dùng RMS sau detrend/lọc; yêu cầu mức dao động tối thiểu để tránh chia gần0.
- `R=(AC_red/DC_red)/(AC_ir/DC_ir)`; SpO₂ baseline=`−45.060R²+30.354R+94.845`.
- Chỉ báo số SpO₂ khi nhịp đạt điều kiện, tương quan RED/IR≥0,8, R trong miền tham khảo của công thức và kết quả trong(0,100]. Không clip số về95–100.

Hệ số trên lấy cảm hứng từ mã tham khảo RF/Maxim, **chưa hiệu chuẩn lại với module và định nghĩa AC có band-pass hiện tại**. `spo2_valid` trong JSON chỉ là đạt cổng kỹ thuật, không phải xác nhận đúng lâm sàng. `calibration_status=unvalidated`, `clinical_level=null` luôn được giữ trong phiên bản này. Dữ liệu tổng hợp có thể không đủ điều kiện dù từng gói nhận MQTT hợp lệ.

Không dùng bản MinMax/rolling của `preprocess.py` để tính AC/DC. Bộ lọc zero-phase thích hợp phân tích offline một phiên; chưa phải thuật toán stream từng mẫu hoặc giám sát cấp cứu liên tục.

## 3. Ba mức màu là quy tắc tham khảo, không phải chẩn đoán

| Chỉ số ước tính đạt cổng kỹ thuật | Bình thường | Cảnh báo | Nguy hiểm |
|---|---|---|---|
| Nhịp mạch, người lớn lúc nghỉ | 60–100 | Ngoài60–100, trừ vùng Nguy hiểm | ≤40 hoặc≥131 |
| SpO₂ thử nghiệm | ≥95 | >92 và<95 | ≤92 |

Các từ trong bảng là **nhãn đối chiếu của giao diện nghiên cứu**, không phải khả năng dự báo bệnh đã được xác nhận. Nhịp lấy khoảng nghỉ của AHA và mốc lệch lớn của pulse NEWS2 để minh họa; không phải tổng NEWS2. SpO₂ tham khảo NHS COVID tại nhà; không áp dụng đồng loạt cho trẻ em, mọi bệnh phổi, người đang thở oxy hoặc mọi độ cao. Các khoảng dùng số chưa làm tròn, nên92,5 và94,5 thuộc Cảnh báo, không có khoảng hở do làm tròn.

Không có mức màu y khoa cho nhiệt độ bề mặt. Nhận xét tổng hợp nêu cả ba, giữ dòng “Chưa có kết luận y khoa”, lấy mức đối chiếu cao hơn của pulse/SpO₂ khi có đủ thông tin. Thiếu một chỉ số không được suy ra mức Bình thường; giá trị null khác0. Nhiệt độ vật thể thiếu5 mẫu cũng không được tổng hợp thành mức Bình thường. Không coi nhịp bình thường là lý do bỏ qua SpO₂ thấp; cũng không suy sốt, COVID hay bệnh tim từ ba thẻ số.

Nguồn và giới hạn đã tổng hợp tại [khảo sát thuật toán](../docs/THUAT_TOAN_BPM_SPO2_VA_NGUONG_THAM_KHAO.md). Nguồn chính: [AHA](https://www.heart.org/en/health-topics/high-blood-pressure/the-facts-about-high-blood-pressure/all-about-heart-rate-pulse), [RCP NEWS2](https://www.rcp.ac.uk/media/a4ibkkbf/news2-final-report_0_0.pdf), [NHS](https://www.england.nhs.uk/coronavirus/wp-content/uploads/sites/52/2020/12/C1634-suspected-Coronavirus-important-information-to-keep-you-safe-at-home-V8_210422.pdf), [RF](https://github.com/aromring/MAX30102_by_RF), [ADI về hiệu chuẩn](https://www.analog.com/en/resources/technical-articles/2022/07/16/12/29/guidelines-for-spo2-measurement--maxim-integrated.html).

Nếu có triệu chứng nghiêm trọng thì cần hỗ trợ y tế, không chờ số liệu nguyên mẫu hoặc bỏ qua triệu chứng vì màu xanh. Cần đối chiếu thiết bị tham chiếu, đánh giá sai số và tỷ lệ từ chối trước khi dùng để cảnh báo thực tế.

## 4. Chạy bản mới và kiểm tra

Tại `iot_lab`:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\run.bat
```

SciPy là dependency trực tiếp mới (môi trường hiện có đã có SciPy). Chọn MongoDB để xem phép đo thật; nguồn Minh họa có banner riêng và chỉ dùng kiểm tra giao diện. Web có ba thẻ, nhận xét, sóng đã lọc, raw và dữ liệu xử lý riêng; CSV raw và JSON phân tích tải được bằng tài khoản chỉ đọc.

Kiểm tra:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -B tests/test_ui.py
```

Tests dùng waveform tổng hợp có nhịp biết trước, hai cực tính/tần số mẫu khác nhau; kiểm tra ratio, khoảng ngưỡng, gap, clipping, flatline, nhiễu, hai kênh bất đồng và median nhiệt độ có mẫu lệch. Đây không phải kiểm chứng độ chính xác trên người hoặc so với SaO₂.
