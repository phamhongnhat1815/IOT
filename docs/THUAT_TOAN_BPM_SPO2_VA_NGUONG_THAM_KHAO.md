# Khảo sát thuật toán BPM/SpO₂ từ MAX30102 và ngưỡng tham khảo

Ngày khảo sát: 01/11/2026. Đây là tài liệu định hướng nghiên cứu cho dự án, chưa phải thuật toán đã triển khai hay thiết bị y tế được thẩm định. Không đổi firmware, dữ liệu raw hoặc cấu hình đang chạy.

## 1. Kết luận cho bộ dữ liệu hiện tại

Repository đang thu1500 cặp IR/RED, đầu ra danh định100Hz, chia30 gói. Cấu hình MAX là tốc độ ADC400 và averaging4. Backend có thể ghép các gói theo sample index thành chuỗi~15s để thử tính nhịp mạch và SpO₂.

Không tính từ một cặp IR/RED; cần chuỗi theo thời gian. Một gói50 cặp chỉ dài0,5s, thường không đủ nhiều chu kỳ. Tần số dùng trong công thức là100Hz đầu ra, không phải400Hz ADC và không phải tốc độ gói MQTT tới server. Timestamp đọc FIFO là mốc phục vụ đọc, không phải timestamp phần cứng của từng mẫu.

Khuyến nghị triển khai Python offline trước: kiểm tra liên tục → chất lượng tín hiệu → nhịp mạch → R quang học → SpO₂ thử nghiệm → đối chiếu tham chiếu. Chưa bật kết luận sức khỏe tự động dựa vào SpO₂ chưa hiệu chuẩn.

## 2. Thuật toán mở và nghiên cứu

| Nhóm | Phương pháp | Điểm đáng dùng | Giới hạn |
|---|---|---|---|
| BPM | Elgendi/ERMA | Ngưỡng thích nghi bằng hai moving average, dễ giải thích | Phải kiểm tra cực tính PPG, lọc, tham số và dữ liệu module thực |
| BPM | MSPTD | Tìm đỉnh/đáy qua nhiều thang | Chi phí tính toán và hiệu ứng biên; kết quả nghiên cứu không tự chuyển sang module này |
| BPM | qppg | Dò sườn lên/onset thay vì chỉ đỉnh cao nhất | Cần chọn triển khai/license phù hợp |
| BPM | Autocorrelation | Tìm chu kỳ lặp, có thể bổ sung kiểm tra tính tuần hoàn | Có thể nhầm nửa/gấp đôi chu kỳ hoặc bắt chuyển động |
| BPM | FFT/Welch | Một baseline độc lập để so với time-domain | Đỉnh phổ có thể là hài hoặc nhiễu chuyển động; không dùng một mình |
| SpO₂ | MAXREFDES117/Maxim | AC/DC theo nhịp, gom ratio rồi tra bảng | Thiết kế tham chiếu, không phải chứng nhận chính xác cho mọi board MAX30102 |
| BPM/SpO₂ | MAX30102_by_RF | Detrend, autocorrelation, RMS và tương quan hai kênh | Dự án mở; tham số và hiệu chuẩn không mặc nhiên đúng cho hệ đang dùng |

Nguồn nghiên cứu: [Elgendi et al., 2013, DOI10.1371/journal.pone.0076585](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0076585) dùng lọc0,5–8Hz, hai cửa sổ111ms/667ms và offset0,02 lần trung bình tín hiệu bình phương. Đây là cấu hình của bài báo, không phải tham số tối ưu đã đo cho dự án.

[Charlton et al., 2022, DOI10.1088/1361-6579/ac826d](https://pmc.ncbi.nlm.nih.gov/articles/PMC9393905/) đối chiếu15 bộ dò nhịp; MSPTD và qppg tốt trong các đánh giá tổng hợp của nghiên cứu, nhưng chuyển động làm giảm hiệu năng. Tài nguyên: [ppg-beats](https://github.com/peterhcharlton/ppg-beats). Không diễn giải hiệu năng trên tập công bố thành độ chính xác của board đang dùng.

Nguồn mã gốc: [Maxim/SparkFun spo2_algorithm.cpp](https://github.com/sparkfun/SparkFun_MAX3010x_Sensor_Library/blob/master/src/spo2_algorithm.cpp), [RF algorithm](https://github.com/aromring/MAX30102_by_RF/blob/master/algorithm_by_RF.cpp). Chưa sao chép mã vào dự án; nếu dùng lại cần giữ license/copyright và kiểm tra license từng dependency.

### Cảnh báo quan trọng về tần số và buffer

Header [Maxim/SparkFun](https://github.com/sparkfun/SparkFun_MAX3010x_Sensor_Library/blob/master/src/spo2_algorithm.h) đặt `FreqS=25`, buffer4s=100 mẫu. Header [RF](https://github.com/aromring/MAX30102_by_RF/blob/master/algorithm_by_RF.h) cũng mặc định25Hz/4s và giới hạn40–180bpm.

Dự án là100Hz: không truyền mù1500 mẫu vào buffer cố định100 phần tử, không sửa mỗi con sốFs rồi bỏ các hằng dẫn xuất. Nếu giữ mã tham chiếu phải resample có anti-alias đúng25Hz và chia cửa sổ đúng kích thước, hoặc rà soát toàn bộ buffer/hằng phụ thuộcFs. Thuật toán chỉ cho40–180bpm không thể tự xác nhận các vùng nguy cơ nằm ngoài khoảng đó; phải trả trạng thái ngoài phạm vi thay vì coi là bình thường.

## 3. Công thức BPM/nhịp mạch

GọiFs là số mẫu mỗi giây, n_i là chỉ số các nhịp được phát hiện đúng:

$$IBI_i = (n_{i+1}-n_i)/F_s$$

$$PR = 60/\operatorname{median}(IBI_i)$$

IBI tính bằng giây. VớiFs=100 và khoảng cách nhịp75 mẫu, PR=80bpm. Một cách tổng hợp khác là `60*(K-1)/(t_last-t_first)`, tránh sai lệch đếm nguyên số nhịp trong cửa sổ ngắn. Median là lựa chọn tổng hợp robust của pipeline đề xuất, vẫn cần phát hiện và đánh dấu nhịp bị bỏ/đếm đôi.

Nhánh autocorrelation tìm lagk tương ứng chu kỳ, rồi `PR=60*Fs/k`. Nhánh phổ tìm tần số cơ bảnf0 rồi `PR=60*f0`. Đây là các đồng nhất thức thời gian/tần số, không bảo đảm đã chọn đúng nhịp. Cần đối chiếu đỉnh, sườn, tương quan và phổ.

FFT trên15s có độ phân giải lưới cơ bản khoảng1/15Hz, tương ứng4bpm; zero-padding làm dày lưới hiển thị, không thêm thông tin quan sát. Nội suy phổ chỉ là một kỹ thuật ước tính, không bảo đảm sai số dưới4bpm.

Giá trị từ PPG nên đặt tên **pulse_rate_bpm/nhịp mạch ước tính**. Không suy ra chẩn đoán loạn nhịp hoặc kết quả ECG từ một chuỗi PPG15s.

## 4. SpO₂: AC/DC, ratio-of-ratios và hiệu chuẩn

Đặtx_red[n], x_ir[n] là ADC đồng bộ. Trong cùng cửa sổ:

$$DC_c=\operatorname{mean}(x_c[n])$$

$$AC_{c,RMS}=\sqrt{\frac{1}{N}\sum_{n=1}^N a_c[n]^2}$$

Trong đóa_c là thành phần dao động đã bỏ DC/trend theo một phương pháp cố định. Tính ratio:

$$R=\frac{AC_{red}/DC_{red}}{AC_{ir}/DC_{ir}}$$

$$SpO_2\approx aR^2+bR+c$$

**Giữ DC từ tín hiệu raw**; không tính DC trên tín hiệu band-pass có trung bình gần0. Không MinMax/Z-score riêng từng kênh rồi đem AC/DC đã mất tỷ lệ biên độ vào công thức. AC RMS, peak-to-peak và biên độ theo từng beat không phải cùng định nghĩa; mỗi cách cần đường hiệu chuẩn tương ứng.

[Analog Devices, Guidelines for SpO₂ Measurement](https://www.analog.com/en/resources/technical-articles/2022/07/16/12/29/guidelines-for-spo2-measurement--maxim-integrated.html) mô tả ratio và fit đường hiệu chuẩn; hình học quang học/lớp che ảnh hưởng hệ số. [FAQ MAX30102 của hãng](https://ez.analog.com/optical_sensing/a/documents/c/max30102efd-t-faq/DO19495/does-the-max30102-have-an-r-curve-associated-with-it-to-correlate-the-ratio-r-acred-dcred-acir-dcir) không cung cấp một R-curve dùng chung đã thẩm định cho mọi MAX30102.

Ví dụ baseline có thật trong [mã RF](https://github.com/aromring/MAX30102_by_RF/blob/master/algorithm_by_RF.cpp):

$$SpO_{2,refcode}=-45.060R^2+30.354R+94.845$$

Mã dùng RMS sau detrend và chỉ chấp nhận miềnR của nó; đó là logic tham khảo, không phải miền chính xác lâm sàng được chứng minh cho board của mình. Không trộn hệ số này vớiAC định nghĩa khác và tuyên bố độ chính xác thương mại. Công thức `110-25R` thường thấy cũng chỉ là một đường fit đơn giản, không phải định luật phổ quát.

Không ép kết quả về95–100 để trông “ổn”, không biến giá trị ngoài miền hiệu chuẩn thành bình thường. LưuR, AC, DC, phương pháp, hệ số, phiên bản và trạng thái hiệu chuẩn cùng kết quả. SpO₂ có thể chưa hợp lệ trong khi nhịp mạch vẫn tính được.

## 5. Đối chiếu với sản phẩm/giải pháp thương mại

| Nguồn hãng | Điều công khai | Điều không thể suy ra |
|---|---|---|
| [Masimo SET](https://www.masimo.com/technology/pulse-oximetry/masimo-set-pulse-oximetry/) và [manual Rad-5](https://techdocs.masimo.com/globalassets/techdocs/pdf/lab-5724h_master.pdf) | Nhiều bộ xử lý song song, adaptive filtering, đánh giá confidence; manual có sơ đồ năm nhánh | Không công khai toàn bộ mã/hệ số để sao chép thành một công thức MAX30102 |
| [Nonin PureSAT](https://www.nonin.com/resource/puresat-spo2-averaging/) | Hãng mô tả trung bình thích nghi theo từng pulse | Không có mã nguồn đầy đủ trong tài liệu đã tìm; không mặc định một moving average đơn giản là PureSAT |
| [ADI MAX32664](https://www.analog.com/en/products/max32664.html) | Sensor hub thương mại có thuật toán HR/SpO₂; bảnA hỗ trợ MAX30101/MAX30102 đo ở ngón tay | Cần thêm hub/firmware phù hợp; không phải thư viện Python có thể chép trực tiếp vào backend |

Đây là mô tả của nhà sản xuất, không phải thử nghiệm độc lập do dự án thực hiện. Bài học dùng được: kiểm soát chất lượng và chuyển động, confidence, optics/AFE và hiệu chuẩn quan trọng ngang công thức cuối. MAXREFDES117 và SparkFun là thiết kế/thư viện tham chiếu, không đồng nghĩa một máy thương mại được cấp phép.

## 6. “Ổn định” phải tách làm hai trục

**Chất lượng phép đo:** đủ mẫu, không clipping/flatline, tín hiệu có pulse, hai kênh phù hợp, các cách ước tính nhất quán. **Tình trạng chỉ số:** nằm trong/ngoài khoảng tham khảo trong một bối cảnh cụ thể. Số đo thấp và lặp lại ổn định vẫn có thể đáng lo; số đo đẹp nhưng nhiễu không chứng minh an toàn.

[Elgendi, 2016, DOI10.3390/bioengineering3040021](https://pmc.ncbi.nlm.nih.gov/articles/PMC5597264/) so sánh các chỉ số chất lượng như skewness, perfusion, relative power; kết quả theo dataset, không có một ngưỡng IR/DC cố định đảm bảo chất lượng mọi phép đo. IR>50000 hiện tại chỉ là heuristic phát hiện tiếp xúc, không chứng minh đã có waveform tốt.

### Gợi ý kỹ thuật để bắt đầu thử nghiệm — không phải ngưỡng y khoa

Đề xuất cửa sổ8s/800 mẫu tại100Hz, dịch1s; một phiên15s chỉ cho vài cửa sổ chồng lấp. Chúng không phải nhiều lần xác nhận độc lập. Cần kiểm tra hiệu ứng biên và padding khi lọc offline.

| Kiểm tra đề xuất | Xử lý ban đầu |
|---|---|
| Mẫu thiếu/trùng/sai thứ tự | Không ghép giả thành liên tục; tách đoạn hoặc từ chối cửa sổ |
| Bão hòa ADC, chuỗi phẳng, mất tiếp xúc | Đánh dấu lỗi đo; ngưỡng clipping thực tế phải xem histogram/ADC config |
| DC<=0 hoặc AC quá gần nhiễu nền | Không tínhR; ngưỡng biên độ phải học từ dữ liệu module |
| Pearson RED/IR và autocorrelation | Có thể thử mốc0,8 và0,5 từ cấu hình RF làm baseline, không xem là chuẩn lâm sàng |
| Ước tính time-domain và autocorrelation lệch nhau | Thử cờ bất đồng nếu chênh>max(5bpm,10%); đây là tham số đề xuất cần đánh giá |
| IBI biến thiên mạnh | Đánh dấu biến thiên/bất đồng; không kết luận do nhiễu hay bệnh chỉ từ tiêu chí này |
| Không đủ chu kỳ trong cửa sổ | Kéo dài phép thu hoặc trả insufficient_data, không bịa số |

Mốc0,8/0,5 lấy từ [header RF](https://github.com/aromring/MAX30102_by_RF/blob/master/algorithm_by_RF.h), vốn cấu hình25Hz/4s. Không hứa chúng vẫn tối ưu khi đổi100Hz/8s. Pearson cao cũng có thể do chuyển động chung hai kênh. Không dùng một SQI duy nhất để chứng nhận SpO₂.

Tách cờ `signal_quality`, `pulse_rate_valid`, `spo2_estimate_valid`, `calibration_status` và `clinical_interpretation`. Có thể trả `pulse_rate_bpm=null`/`spo2_percent=null` với lý do; null không phải0 và không phải “an toàn”. Kết quả cũ phải ghi tuổi dữ liệu; không giữ màu xanh từ phiên trước khi phiên mới đo lỗi.

## 7. Ngưỡng nhịp mạch tham khảo cho người lớn lúc nghỉ

[American Heart Association](https://www.heart.org/en/health-topics/high-blood-pressure/the-facts-about-high-blood-pressure/all-about-heart-rate-pulse): nhịp tim nghỉ thường60–100bpm. Dưới60 hoặc trên100 cần xem bối cảnh; vận động viên, giấc ngủ, thuốc, sốt/vận động có thể thay đổi nhịp. Không áp nguyên bảng người lớn cho trẻ em.

Nếu cần một bảng tham khảo có nguồn rõ ràng về mức lệch sinh lý, hàng **Pulse** của [RCP NEWS2, 2017](https://www.rcp.ac.uk/media/a4ibkkbf/news2-final-report_0_0.pdf) là:

| Nhịp/phút | Điểm của riêng thông số pulse trong NEWS2 |
|---|---|
| <=40 | 3 |
| 41–50 | 1 |
| 51–90 | 0 |
| 91–110 | 1 |
| 111–130 | 2 |
| >=131 | 3 |

NEWS2 dùng nhiều dấu hiệu sinh tồn trong chăm sóc cấp tính. Điểm3 của một thông số cần xem xét lâm sàng khẩn, không đồng nhất với tổng điểm nguy cơ cao; điểm0 không chứng nhận khỏe mạnh. Khoảng NEWS2 và AHA có mục đích khác nhau.

Giao diện nên ghi “ngoài khoảng nghỉ tham khảo” hoặc “mức lệch pulse theo NEWS2”. Không gọi dữ liệu hai thông số là tổng NEWS2: dự án thiếu nhiều thông số và điều kiện áp dụng.

## 8. Ngưỡng SpO₂ và mức phản hồi

[MedlinePlus/NIH](https://medlineplus.gov/lab-tests/pulse-oximetry/) nêu95–100% thường gặp; <=92% cần liên hệ nhân viên y tế và<=88% cần chăm sóc y tế ngay. Bệnh phổi, độ cao và mục tiêu điều trị có thể khác. Không tự áp mục tiêu oxy cho người COPD/đang thở oxy.

Một phân tầng dễ trình bày, **tham khảo chương trình theo dõi tại nhà cho người lớn nghi/xác định COVID, không phải tiêu chuẩn chung cho mọi bệnh**, là [NHS England, hướng dẫn2022](https://www.england.nhs.uk/coronavirus/wp-content/uploads/sites/52/2020/12/C1634-suspected-Coronavirus-important-information-to-keep-you-safe-at-home-V8_210422.pdf):

| Kết quả được xác nhận bằng thiết bị đáng tin cậy | Cách hiểu tham khảo |
|---|---|
| 95–100% | Khoảng thường gặp; vẫn xem triệu chứng và mức nền |
| 93–94% | Đo kiểm tra lại và xin tư vấn y tế sớm nếu còn thấp |
| <=92% | Cần đánh giá y tế khẩn; nguồn NHS hướng dẫn cấp cứu nếu đo lại vẫn<=92% |

Không trì hoãn hỗ trợ khi có khó thở rõ, đau ngực, tím tái hoặc ngất chỉ vì máy hiện số bình thường. Những ngưỡng trên dành cho số đo đáng tin và bối cảnh y tế, **không xác nhận nguyên mẫu chưa hiệu chuẩn đủ sức phân loại nguy cơ**.

Không trộn bảng này với thangSpO₂ NEWS2 rồi gọi là cùng một chuẩn: thang1 NEWS2 có các mốc/điểm riêng và thang2 chỉ áp dụng theo chỉ định lâm sàng.

## 9. Quy trình triển khai đề xuất cho backend

Đây là thiết kế đề xuất của dự án, chưa thay đổi code đang chạy:

1. Ghép theo `device_id/session_id/sample_start_index`; dùng `sample_rate_hz`, kiểm tra đủ30 gói và phát hiện khoảng trống. Không coi khoảng cách nhận MQTT là khoảng cách lấy mẫu.
2. Giữraw bất biến. Tạo nhánh detrend/lọc với tham số được ghi lại. Dùng phép lọc cùng đáp ứng hai kênh khi tính biên độ; không dùng dữ liệu đã MinMax từ tiền xử lý chung cho SpO₂.
3. Tính SQI; ước tính pulse bằng ERMA hoặc MSPTD, đối chiếu autocorrelation. FFT chỉ giúp kiểm tra hài/phổ.
4. TínhDC/AC/R theo một định nghĩa cố định. Dùng polynomial tham khảo chỉ dưới nhãn **SpO₂ ước tính thử nghiệm/chưa hiệu chuẩn**.
5. Lưu kết quả riêng: thời điểm thu/nhận, cửa sổ,Fs, method/version, tham số lọc, peak indices, SQI, pulse, AC/DC/R, calibration ID, lý do invalid và coverage.
6. Chỉ thêm phân loại sức khỏe sau kiểm chứng thích hợp. Trong bản nghiên cứu hiện tại có thể hiển thị bảng tham khảo riêng; trường kết luận y tế vẫn `not_assessed` khi chưa thẩm định.
7. Không gọi “theo dõi liên tục”: firmware thu~15s, gửi theo phiên rồi sleep. Hệ thống không biết những gì xảy ra giữa hai phiên; không dùng để phát hiện cấp cứu liên tục.

## 10. Kiểm chứng và giới hạn

Đối chiếu nhịp mạch với nguồn tham chiếu phù hợp, đánh dấu cùng khoảng thời gian và độ trễ bộ lọc. Tách dữ liệu chọn tham số và dữ liệu đánh giá theo **người**, không chia ngẫu nhiên các cửa sổ chồng lấp của cùng một phiên sang cả hai tập.

Báo cáo MAE/RMSE/bias, Bland–Altman và tỷ lệ cửa sổ được chấp nhận. Chỉ báo sai số trên số cửa sổ đẹp sẽ che tỷ lệ thất bại. Thử các ngón tay/vị trí, môi trường sáng, nhiệt độ tay, chuyển động, mức sắc tố da và cấu hình LED trong phạm vi an toàn.

[FDA về pulse oximeters](https://www.fda.gov/medical-devices/products-and-medical-procedures/pulse-oximeters) lưu ý ảnh hưởng của tưới máu, sắc tố da, nhiệt độ da và các yếu tố khác. Không coi độ chính xác của linh kiện hoặc thiết bị thương mại khác là độ chính xác của hệ này.

[FDA về thẩm định độ chính xác SpO₂](https://www.fda.gov/regulatory-information/search-fda-guidance-documents/pulse-oximeters-premarket-notification-submissions-510ks-guidance-industry-and-food-and-drug) mô tả đối chiếu với co-oximetry máu động mạch trong điều kiện chuyên môn. So với máy kẹp ngón tham chiếu chỉ là kiểm tra thăm dò, không tương đương chứng nhận. Kiểm tra người khỏe chỉ quanh95–100% không chứng minh đúng ở vùng88–92%.

**Không tự nín thở kéo dài, giảm oxy hít vào hoặc tạo thiếu oxy để hiệu chuẩn.** Nếu cần kiểm chứng vùng thấp phải qua đơn vị chuyên môn và quy trình phù hợp. Dữ liệu công khai giúp benchmark thuật toán nhưng không thay cho kiểm chứng quang học của module thực.

## 11. Việc nên làm trước

Ưu tiên BPM + SQI trước, vì có thể kiểm tra trực tiếp waveform và nhịp tham chiếu. Sau đó hiển thịR và SpO₂ nghiên cứu có nhãn chưa hiệu chuẩn. Khi đã có số liệu đối chiếu mới quyết định ngưỡng chất lượng, đường hiệu chuẩn, phạm vi sử dụng và cơ chế cảnh báo.

Nguồn đã đọc gồm bài nghiên cứu, mã nguồn của tác giả/nhà cung cấp và tài liệu hãng/y tế liên kết tại từng phần. Không dựa vào hệ số từ blog không rõ phép định nghĩaAC hoặc tuyên bố sao chép thuật toán thương mại đóng.
