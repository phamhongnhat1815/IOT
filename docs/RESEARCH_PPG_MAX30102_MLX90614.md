# Tổng hợp tài liệu cho đồ án MAX30102 + MLX90614 + ESP32

Ngày tổng hợp: 30/10/2026. Đây là khảo sát tài liệu có chọn lọc, không phải tổng quan hệ thống theo PRISMA. Phân biệt thông tin từ hãng, mã nguồn nghiên cứu, thử nghiệm thiết bị và bằng chứng lâm sàng. Không suy ra độ chính xác của nguyên mẫu từ độ chính xác của linh kiện hoặc sản phẩm khác.

## 1. Kết luận định hướng

Phạm vi phù hợp: thiết bị đo theo phiên, truyền dữ liệu PPG hai kênh RED/IR và nhiệt độ lên ThingsBoard; backend phân tích chất lượng, tính nhịp mạch và thử nghiệm SpO2; web lưu lịch sử, giải thích kết quả và yêu cầu đo lại khi cần.

Đóng góp nên tập trung vào ba câu hỏi có thể kiểm chứng:

1. Dữ liệu truyền lên có đầy đủ và giữ đúng trục thời gian không?
2. Thuật toán có cho kết quả gần thiết bị tham chiếu và biết từ chối tín hiệu kém không?
3. Giao diện có giúp hiểu kết quả, mức chất lượng và giới hạn phép đo không?

Không đặt mục tiêu chẩn đoán COVID, viêm phổi, bệnh tim hoặc ngưng thở khi ngủ bằng một phiên ngắn. Không biến số đo nhiệt độ bề mặt thành thân nhiệt bằng một hằng số tùy ý.

## 2. Danh mục nguồn và ghi chú đọc

### A. Thiết kế tham chiếu và mã nguồn

**[1] Analog Devices — MAX30102 datasheet/product.**
https://www.analog.com/en/products/max30102.html

Nguồn gốc cấu hình LED, ADC, FIFO, tốc độ lấy mẫu và chế độ tiết kiệm điện. Cần ghi lại cấu hình thực tế trong mỗi phiên. Tốc độ đặt trong thanh ghi và tốc độ mẫu sau averaging cần phân biệt.

**[2] Analog Devices — MAXREFDES117.**
https://www.analog.com/en/resources/reference-designs/maxrefdes117.html

Thiết kế tham chiếu có driver và thuật toán HR/SpO2 cơ bản. Dùng làm baseline, không xem là chứng nhận y khoa cho module tự lắp.

**[3] Analog Devices — MAXREFDES1043.**
https://www.analog.com/en/resources/reference-designs/maxrefdes1043.html

Có luồng chờ/phát hiện ngón tay/đo và cấu hình cảm biến. Hữu ích để tổ chức state machine; cấu hình nguồn của thiết kế này không được sao chép nguyên xi sang board ESP32.

**[4] SparkFun — Example8_SPO2, đọc trực tiếp mã.**
https://raw.githubusercontent.com/sparkfun/SparkFun_MAX3010x_Sensor_Library/master/examples/Example8_SPO2/Example8_SPO2.ino

Cấu hình ví dụ: 100 samples/s với averaging 4, đầu ra 25 samples/s. Bộ đệm 100 mẫu là 4 giây; mỗi lần thay 25 mẫu rồi tính lại. Có cờ valid riêng. Khi chuyển thuật toán sang backend phải kiểm tra các hằng số tốc độ, chiều dài cửa sổ và tiền xử lý.

**[5] MAX30102_by_RF — README và thuật toán.**
https://github.com/aromring/MAX30102_by_RF
https://github.com/aromring/MAX30102_by_RF/blob/master/algorithm_by_RF.cpp

Thuật toán thay thế và cơ chế lọc chất lượng dựa vào tự tương quan, tương quan hai kênh. Có dữ liệu mẫu để vẽ kiểm tra. Hữu ích làm thuật toán so sánh; không có cơ sở coi kết quả là chính xác lâm sàng chỉ vì số hiển thị ổn định.

**[6] Analog Devices — Guidelines for SpO2 Measurement (2019).**
https://www.analog.com/en/resources/technical-articles/guidelines-for-spo2-measurement--maxim-integrated.html

Giải thích AC/DC, ratio-of-ratios, ảnh hưởng cấu trúc quang học, đường hiệu chuẩn và kiểm chứng theo người bằng leave-one-out. Cùng cảm biến nhưng khác kính/vỏ vẫn có thể cần hệ số khác. Bảng hệ số cho cảm biến khác không phải hệ số mặc định cho MAX30102. Các đoạn về quy định phản ánh thời điểm tài liệu, không dùng làm kết luận pháp lý hiện hành.

### B. Phát hiện nhịp và chất lượng tín hiệu

**[7] Charlton et al., 2022 — Detecting beats in the photoplethysmogram: benchmarking open-source algorithms.**
https://api.repository.cam.ac.uk/server/api/core/bitstreams/3022e8a8-e2bd-4a21-bbea-0d70946cbb0c/content

Đọc phương pháp, kết quả, thảo luận. So sánh 15 bộ phát hiện nhịp; MSPTD và qppg hoạt động tốt trong khảo sát. Thử nghiệm dùng cửa sổ 20 giây, chồng 5 giây; hiệu năng giảm khi chuyển động. Đây không phải yêu cầu mọi thiết bị phải đo 20 giây, cũng không bảo đảm thuật toán tốt nhất trên MAX30102 của đồ án.

**[8] PPG-beats — phần mềm của nhóm nghiên cứu.**
https://ppg-beats.readthedocs.io/en/stable/

Thư viện MATLAB, tập thuật toán và khung đánh giá có ECG tham chiếu. Nên học cách đánh giá phát hiện nhịp bằng sensitivity/PPV/F1, ngoài sai số BPM.

**[9] NeuroKit2 — tài liệu PPG.**
https://neuropsychology.github.io/NeuroKit/functions/ppg.html

Có pipeline làm sạch, tìm nhịp, quality và vẽ dữ liệu trong Python. Template matching chấm độ giống dạng sóng với mẫu trung bình. Điểm quality không phải xác suất kết quả đúng về y khoa. Dùng cho nhánh PPG/nhịp mạch; không mặc định có thuật toán SpO2 hai bước sóng đã hiệu chuẩn.

**[10] BIDMC PPG and Respiration Dataset.**
https://physionet.org/content/bidmc/1.0.0/

53 bản ghi, mỗi bản 8 phút, có PPG/ECG/hô hấp 125 Hz và chỉ số số học 1 Hz. Phù hợp thử pipeline tìm nhịp và nhánh hô hấp. Không phải tập RED/IR thô hai kênh MAX30102 để tự hiệu chuẩn SpO2; có giá trị SpO2 đích không có nghĩa đủ đầu vào cho bài toán đó.

### C. Các nghiên cứu gần phần cứng của đồ án

**[11] Renhoran & Nur’aidha, 2025 — Performance Evaluation of Commercial MLX90614 and MAX30102 Sensors for Portable Vital Sign Monitoring Device.**
https://ajmedtech.com/index.php/journal/article/download/79/108/685

Đọc phương pháp và kết quả; nguyên mẫu ESP32, 26 người khỏe mạnh 17–22 tuổi. Có MAE/RMSE/Bland–Altman, khảo sát khoảng cách đo nhiệt, loại đoạn đầu và lọc tín hiệu. Nên học thiết kế đánh giá. Giới hạn: mẫu trẻ/khỏe, máy so sánh có sai số, không chứng minh phát hiện bệnh hay độ chính xác khi thiếu oxy. Không dùng ngôn ngữ kết luận mạnh của bài thay cho đánh giá bằng chứng.

**[12] Rojas et al. — Monitoreo remoto de signos vitales: pulso, temperatura y saturación de oxígeno empleando cloud computing.**
https://revistas.udea.edu.co/index.php/ingenieria/article/view/354048
DOI: 10.17533/udea.redin.20240941

Trang tạp chí/tóm tắt mô tả MAX30102, MLX90614, Arduino Mega, Raspberry Pi Zero W và ThingSpeak. Có kiểm tra thống kê và thời gian thu từ xa khoảng 117 giây. Chỉ dùng chi tiết đã đọc ở trang tạp chí, không coi đã thẩm định toàn bộ PDF. Không có khác biệt thống kê không đồng nghĩa chứng minh hai thiết bị tương đương.

**[13] Chowdhary et al., 2022 — IoT based Wearable Health Monitoring System for COVID-19 Patients.**
https://ceur-ws.org/Vol-3142/PAPER_01.pdf

Đọc kiến trúc và kết quả nguyên mẫu: NodeMCU, MAX30102, cảm biến nhiệt, còi/OLED, ThingSpeak/Blynk. Có ích cho sơ đồ IoT và cảnh báo. Tên có COVID-19 nhưng hệ thống theo dõi chỉ số không phải xét nghiệm xác định COVID. Không lấy ảnh màn hình hoạt động làm bằng chứng chính xác lâm sàng.

### D. Sản phẩm thương mại và cách tổ chức dịch vụ

**[14] Masimo MightySat Rx.**
https://www.masimo.com/products/wearables/mightysatrx/

Trang hãng mô tả SpO2, PR, Pi, PVi và RRp; có kết nối ứng dụng, xu hướng và waveform ở phiên bản phù hợp. Nên học cách trình bày tín hiệu cùng kết quả. Thuật toán SET độc quyền; không có cơ sở cho rằng dùng MAX30102 hoặc có thể tái tạo chỉ bằng bộ lọc đơn giản.

**[15] Masimo SafetyNet — cloud telehealth.**
https://www.masimo.com/products/telehealth/masimo-safetynet/

Portal tập trung, lịch sử, triệu chứng tự báo, care pathway và phân quyền. Bài học cho đồ án: lưu phiên, bối cảnh và lý do cảnh báo. Đây là trang hãng; các tuyên bố hiệu quả cần đọc nghiên cứu gốc, không suy rộng thành bằng chứng cho nguyên mẫu.

**[16] Masimo Patient SafetyNet — giám sát và thông báo.**
https://www.masimo.com/products/remote-monitoring/safetynet/

Theo dõi tập trung và chuyển cảnh báo đến nhân viên, có cơ chế escalation. Nên học phân biệt technical alert với physiological alert. Đồ án đo một phiên rồi ngủ không có chức năng giám sát liên tục tương đương.

**[17] Nonin Onyx Vantage 9590.**
https://www.nonin.com/support/9590/

Thông số hãng công bố độ chính xác theo điều kiện và dải đo. A_rms không phải giới hạn sai số tuyệt đối cho mọi lần đọc. Dùng tham khảo cách báo cáo điều kiện thử nghiệm, không gán thông số sản phẩm này cho MAX30102.

**[18] Nonin WristOx2 / nVISION.**
https://www.nonin.com/support/nvision/
https://www.nonin.com/products/wristox2-model-3150-with-ble/

Giải pháp ghi dữ liệu và phần mềm quản lý. Học báo cáo theo thời gian, sự kiện và dữ liệu bị loại. Ứng dụng qua đêm cần phép đo dài; không tương đương đo 5 giây.

### E. Vai trò hỗ trợ quyết định lâm sàng

**[19] Apple Heart Study, NEJM 2019.**
https://www.nejm.org/doi/full/10.1056/NEJMoa1901183

Thiết bị PPG phát hiện xung không đều; bước tiếp theo có tư vấn và ECG patch. Nghiên cứu nêu rõ giới hạn về độ nhạy và việc không thông báo không loại trừ loạn nhịp. Bài học: cảnh báo dẫn đến kiểm tra xác nhận, không coi PPG ngắn là ECG.

**[20] Lee et al., NEJM 2022 — Pulse Oximetry for Monitoring Patients with Covid-19 at Home — A Pragmatic, Randomized Trial.**
https://www.nejm.org/doi/full/10.1056/NEJMc2201541

Thử nghiệm bổ sung máy đo SpO2 vào chương trình COVID Watch. Không cải thiện đáng kể tiêu chí ngày còn sống và ngoài viện sau 30 ngày so với chương trình sẵn có. Không diễn giải thành SpO2 vô ích trong mọi hoàn cảnh. Đo đúng, phát hiện bất thường và cải thiện kết cục là ba loại bằng chứng khác nhau.

**[21] NHS England — COVID Oximetry @home guidance.**
https://www.england.nhs.uk/coronavirus/wp-content/uploads/sites/52/2020/11/C1671_COVID-Oximetry-%40home-Novel-coronavirus-COVID-19-guidance-note.pdf

Ví dụ quy trình theo dõi tại nhà, hướng dẫn đo và phân luồng. Là tài liệu theo bối cảnh COVID; không áp toàn bộ ngưỡng hoặc quy trình sang mọi người dùng đồ án.

**[22] AASM 2017 — Diagnostic Testing for Adult Obstructive Sleep Apnea.**
https://www.aasm.org/resources/clinicalguidelines/diagnostic-testing-osa.pdf

Đọc khuyến cáo và yêu cầu phép đo: đánh giá giấc ngủ, PSG hoặc HSAT đủ kỹ thuật, không chỉ bộ dự đoán. Cấu hình đo ngắn của đồ án không đủ cho chẩn đoán ngưng thở khi ngủ. Đây là hướng dẫn 2017, dùng để hiểu giới hạn phương pháp, không khẳng định là bản mới nhất.

**[23] Sjoding et al., NEJM 2020 — Racial Bias in Pulse Oximetry Measurement.**
https://doi.org/10.1056/NEJMc2029240

Phân tích cặp SpO2 và độ bão hòa oxy từ máu cho thấy sai khác hiệu năng giữa nhóm bệnh nhân. Bài có correction; không dùng các tỷ lệ làm thông số cho thiết bị của đồ án. Bài học: không coi một con số SpO2 là chắc chắn; cần xem bối cảnh và đa dạng đối tượng thử.

**[24] FDA — Pulse Oximeter Basics.**
https://www.fda.gov/consumers/consumer-updates/pulse-oximeter-basics

Giới hạn phép đo, cách đo và phân biệt sản phẩm wellness với thiết bị y tế. Kết quả phải được xem cùng triệu chứng. Dùng để viết hướng dẫn và giới hạn của web, không tạo hệ chẩn đoán bằng vài điều kiện if.

### F. Nhiệt độ và hạ tầng dữ liệu

**[25] Melexis — MLX90614 datasheet.**
https://www.melexis.com/-/media/files/documents/datasheets/mlx90614-datasheet-melexis.pdf

Đọc mô tả, accuracy, medical variants và FOV. Nhiệt độ là kết quả vùng nhìn; độ chính xác phụ thuộc cân bằng nhiệt. Cần biết mã linh kiện, tách khỏi nguồn nhiệt của ESP32 và cố định cách đo. Không lấy độ phân giải thay cho độ chính xác.

**[26] Melexis — evaluation board manual.**
https://www.melexis.com/-/media/files/documents/user-manuals/evb90614-user-manual-melexis.pdf?sc_lang=en

Chế độ minh họa nhiệt độ lõi có giới hạn sử dụng rõ ràng. Không sao chép một phép biến đổi demo thành thuật toán chẩn đoán sốt.

**[27] FDA — Non-contact Infrared Thermometers.**
https://www.fda.gov/medical-devices/general-hospital-devices-and-supplies/non-contact-infrared-thermometers

Tư thế, môi trường, vùng đo và hướng dẫn hãng ảnh hưởng kết quả. Đồ án cần quy trình đo lặp lại được, thay vì chỉ thêm trung bình số học.

**[28] ThingsBoard — Time-Series Data.**
https://thingsboard.io/docs/user-guide/digital-twins/time-series-data/

Hỗ trợ dữ liệu theo thời gian, JSON, lịch sử và chuyển tiếp qua Rule Engine. Backend phải đọc toàn bộ phiên, không chỉ latest values. Timestamp nhận tại server không thay thế timestamp lấy mẫu.

**[29] ThingsBoard — Telemetry HTTP payload formats.**
https://thingsboard.io/docs/reference/http-api/telemetry/

Ví dụ timestamp phía thiết bị và batch nhiều điểm. Đây là trang HTTP; triển khai MQTT cần kiểm tra tài liệu transport MQTT tương ứng. Với dữ liệu PPG có thể chọn lưu mỗi batch dưới một JSON key và metadata, sau khi thử tương thích trên tenant thực tế.

## 3. Thiết kế xử lý được đề xuất (cần thử nghiệm)

1. Kiểm tra session_id, batch_index, batch_total, sample_count, sample_index và thời gian.
2. Xác thực tốc độ mẫu thực tế; phát hiện khoảng trống/FIFO overflow. Không ghép qua khoảng mất dữ liệu như liên tục.
3. Lưu raw bất biến; tách nhánh xử lý nhịp mạch và SpO2.
4. Nhánh nhịp mạch: tiền xử lý phù hợp, tìm nhịp, kiểm tra chu kỳ và chất lượng. So sánh baseline với một thuật toán nghiên cứu.
5. Nhánh SpO2: ước lượng AC/DC từ dữ liệu phù hợp; tính R; dùng đường hiệu chuẩn có nguồn; kiểm tra riêng chất lượng hai kênh. Không dùng tín hiệu đã bỏ DC để tính DC.
6. Nhiệt độ: kiểm tra lỗi đọc và độ ổn định; giữ object/ambient riêng; chỉ đánh giá theo phương pháp đã xác nhận.
7. Tạo kết quả theo chỉ số: valid/invalid, giá trị, đơn vị, nguyên nhân từ chối và phiên bản thuật toán.
8. Rule engine nhận xét chỉ chạy khi chất lượng đủ. Ngưỡng phải ghi nguồn, đối tượng và bối cảnh; không coi trong khoảng tham chiếu là không mắc bệnh.

Không loại mọi nhịp quá nhanh/chậm ở bước chất lượng chỉ vì vượt khoảng bình thường: điều đó có thể xóa chính tín hiệu cần phát hiện. Bất thường sinh lý và lỗi kỹ thuật phải tách nhau. Tương quan RED/IR cao cũng chưa đủ chứng minh tín hiệu đúng vì hai kênh có thể cùng bị nhiễu.

## 4. Ràng buộc 5 đợt và thời lượng

5 đợt x 50 mẫu = 250 cặp. Tại 50 Hz, thu 5 giây; tại 25 Hz, thu 10 giây. Không thể vừa giữ 250 mẫu, vừa 50 Hz, vừa khẳng định có 20 giây tín hiệu liên tục.

Giữ yêu cầu hiện tại làm chế độ thử nghiệm ngắn: 5 đợt, 50 mẫu/đợt, 50 Hz, khoảng một đợt/giây. Backend có thể từ chối phiên. Chế độ 10–20 giây là phương án cần người dùng lựa chọn nếu kết quả thí nghiệm cho thấy phiên ngắn thiếu ổn định, không tự đổi yêu cầu.

Phải kiểm tra tốc độ sau averaging: ví dụ đặt 200 samples/s và average 4 có đầu ra danh định 50 samples/s. Xác nhận bằng số mẫu và thời gian thực tế, không chỉ bằng comment trong code.

Thuật toán cần ghép cả phiên; mỗi gói một giây là đơn vị truyền, không nhất thiết là cửa sổ phân tích. Thời gian ổn định trước khi bắt đầu phiên cần được khảo sát riêng.

## 5. Luồng firmware và xác nhận

BOOT -> WAIT_CONTACT -> CAPTURE_AND_BUFFER -> WAIT_BACKEND_ACK -> SENSOR_SHUTDOWN -> DEEP_SLEEP.

Còi theo nhịp trong lúc chờ/thu/gửi; tắt khi backend xác nhận đã nhận và lưu đủ dữ liệu phiên. ACK này không có nghĩa dữ liệu đủ chất lượng hoặc người đo khỏe. Sau khi ngủ, web có thể trả kết quả cần đo lại; dùng RESET để bắt đầu phiên mới.

Nếu chưa có ACK: retry có kiểm soát, timeout và trạng thái lỗi; không treo vô hạn không giải thích. Mất điện trong lúc đợi cần được quyết định rõ có lưu flash hay chấp nhận mất phiên. Deep sleep không tự cắt nguồn toàn bộ module.

## 6. Web tối thiểu có giá trị

- Tiến trình nhận gói, thời điểm đo, trạng thái phiên.
- Kết quả PR/BPM, nhiệt độ bề mặt và SpO2 thử nghiệm nếu đủ điều kiện.
- Trạng thái chất lượng riêng từng chỉ số; lý do cần đo lại.
- Biểu đồ RED/IR với đỉnh đã phát hiện; đoạn bị loại được đánh dấu.
- Lịch sử và xu hướng; phân biệt thay đổi sinh lý với đổi phiên bản thuật toán.
- Xuất CSV/JSON để tái chạy thuật toán; giữ cấu hình cảm biến và firmware.
- Bối cảnh tự nhập tùy chọn: nghỉ/vừa vận động, triệu chứng, ghi chú. Không tự chuyển thành chẩn đoán.
- Phân quyền nếu nhiều người; không để credential ThingsBoard trong frontend.

## 7. Kế hoạch thực nghiệm đề xuất

Các số lượng/cấu hình dưới đây là kế hoạch kỹ thuật cần điều chỉnh, không phải tiêu chuẩn chứng nhận.

1. Thu một bộ pilot dài để cắt cửa sổ 5/10/20 giây và đánh giá ảnh hưởng thời lượng; không nội suy thêm mẫu để giả tăng dữ liệu.
2. Thử tĩnh, đổi vị trí ngón tay, áp lực và ánh sáng thông thường; ghi nhận đoạn dịch chuyển. Có cơ cấu giữ ngón tay vừa phải, không siết cản tuần hoàn.
3. Đồng bộ thời gian đối chiếu. Nhịp mạch có thể so với máy đo có nguồn gốc rõ; ECG tham chiếu tốt hơn cho đánh giá từng nhịp khi có điều kiện. PPG có độ trễ so với ECG cần căn chỉnh.
4. Nhiệt độ: thử khoảng cách/vị trí và điều kiện phòng; chọn chuẩn và vị trí đối chiếu có ý nghĩa. Không gộp nhiệt độ da và nhiệt độ miệng thành cùng một đại lượng.
5. Báo cáo MAE/RMSE, bias và limits of agreement; độ thành công, tỷ lệ bị từ chối, thời gian ra kết quả, mất/trùng gói. Sai số trung bình thấp chưa chứng minh mọi phép đo đều tốt.
6. Nếu điều chỉnh ngưỡng/hệ số bằng dữ liệu người: tách theo người giữa tập điều chỉnh và đánh giá. Không để các cửa sổ của cùng người rơi cả hai phía rồi tuyên bố tổng quát tốt.
7. Dữ liệu mô phỏng dùng kiểm tra pipeline, timestamp và lỗi truyền. Nó không chứng minh độ chính xác cảm biến hoặc phát hiện bệnh.
8. Không tự gây giảm oxy, nhịn thở hay dùng khí để hiệu chuẩn. Thử nghiệm kiểu đó trong tài liệu thuộc môi trường chuyên môn có giám sát. Người khỏe SpO2 cao chỉ cho phép đánh giá trong vùng đã quan sát.

## 8. Đóng góp nghiên cứu khả thi

Đề xuất câu hỏi chính: "Cơ chế đánh giá chất lượng và lựa chọn cửa sổ phân tích có cải thiện độ tin cậy của phép đo theo phiên từ MAX30102 khi truyền qua IoT không?"

So sánh: baseline luôn xuất số với pipeline có quality gate; thuật toán A/B; cửa sổ 5/10/20 giây. Báo cáo cả sai số lẫn tỷ lệ có kết quả để tránh làm đẹp sai số bằng cách loại gần hết dữ liệu.

Phạm vi xác nhận: trong nhóm người và điều kiện thực nghiệm đã khảo sát. SpO2 chưa có dữ liệu thấp được ghi là ước tính thử nghiệm; cảnh báo là demo quy tắc, chưa chứng minh hiệu quả lâm sàng.

## 9. Nguồn chưa đọc đủ để dùng làm căn cứ chính

- https://www.mdpi.com/2072-666X/16/7/791 — có kết quả tìm kiếm nhưng toàn văn bị giới hạn truy cập (429) ở lần khảo sát; chưa thẩm định phương pháp đầy đủ.
- https://www.nature.com/articles/s41746-022-00665-y — kết quả tìm kiếm mô tả nghiên cứu smartphone hypoxemia, mở toàn văn gặp lỗi; không lấy chi tiết phương pháp làm nền cho thiết kế này.
- Một số trang Nonin bị 403 khi mở trực tiếp; tính năng/thông số lấy từ nội dung trang hãng được công cụ tìm kiếm trả về. Cần kiểm tra đúng manual và model nếu mua hoặc dùng làm máy tham chiếu.

Không coi các nguồn không truy cập đủ là đã đọc toàn văn; không dùng con số quảng cáo hoặc tiêu đề có chữ "diagnosis" làm bằng chứng xác nhận.
