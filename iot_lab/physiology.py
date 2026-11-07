"""Research estimates from raw PPG. No diagnosis, clinical validation or raw mutation.

See docs/THUAT_TOAN_BPM_SPO2_VA_NGUONG_THAM_KHAO.md and ANALYSIS.md.
All quality thresholds below are engineering starting points, not medical cutoffs.
"""
import math
import numpy as np
import pandas as pd
from scipy import signal

VERSION = "ppg-research-v1"
LEVELS = ("Bình thường", "Cảnh báo", "Nguy hiểm")


def temperature_summary(temps):
    """Use each distinct physical reading once, with no ambient/body correction."""
    frame = temps.copy()
    if "temperature_at_ms" in frame:
        frame = frame.drop_duplicates("temperature_at_ms")
    def describe(key, low, high):
        values = pd.to_numeric(frame.get(key, pd.Series(dtype=float)), errors="coerce").to_numpy(dtype=float)
        valid = values[np.isfinite(values) & (values >= low) & (values <= high)]
        if not len(valid):
            return {"value": None, "count": 0, "invalid_count": len(values), "stable": False,
                    "min": None, "max": None, "iqr": None, "mean": None}
        q1, q3 = np.percentile(valid, [25, 75])
        return {"value": float(np.median(valid)), "mean": float(np.mean(valid)),
                "count": len(valid), "invalid_count": len(values) - len(valid),
                "min": float(valid.min()), "max": float(valid.max()), "iqr": float(q3 - q1),
                "stable": bool(len(valid) >= 5 and q3 - q1 <= .3 and np.ptp(valid) <= 1.0)}
    return {"object": describe("object_temp", -70, 380),
            "ambient": describe("ambient_temp", -40, 125), "method": "median", "body_temperature": False}


def pulse_reference(bpm):
    if bpm is None or not math.isfinite(bpm):
        return None
    if bpm <= 40 or bpm >= 131:
        return LEVELS[2]
    if bpm < 60 or bpm > 100:
        return LEVELS[1]
    return LEVELS[0]


def oxygen_reference(spo2):
    if spo2 is None or not math.isfinite(spo2) or not 0 <= spo2 <= 100:
        return None
    # Continuous boundaries avoid leaving fractional estimates (94.5, 92.5) unclassified.
    if spo2 <= 92:
        return LEVELS[2]
    if spo2 < 95:
        return LEVELS[1]
    return LEVELS[0]


def _invalid(reason):
    return {"version": VERSION, "bpm": None, "spo2": None, "bpm_valid": False,
            "spo2_valid": False, "reasons": [reason], "calibration_status": "unvalidated",
            "clinical_level": None, "reference_level": None, "quality": {},
            "curve": [], "peaks": [], "method": "peaks+autocorrelation / RMS ratio"}


def estimate_ppg(samples, info):
    """Analyze one complete contiguous session; never bridge missing samples."""
    if not info.get("complete"):
        return _invalid("Chưa đủ phiên liên tục; chờ đủ gói, không nội suy mẫu thiếu.")
    fs = float(info.get("rate", 0))
    if not math.isfinite(fs) or not 20 <= fs <= 3200:
        return _invalid("Tần số mẫu ngoài phạm vi bộ xử lý.")
    if len(samples) < math.ceil(8 * fs):
        return _invalid("Cần ít nhất 8 giây dữ liệu liên tục.")
    index = samples["index"].to_numpy(dtype=float)
    if not np.all(np.diff(index) == 1) or samples["segment"].nunique() != 1:
        return _invalid("Dữ liệu có gián đoạn hoặc chồng mẫu.")
    ir = samples["ir"].to_numpy(dtype=float, copy=True)
    red = samples["red"].to_numpy(dtype=float, copy=True)
    if not np.isfinite(ir).all() or not np.isfinite(red).all():
        return _invalid("Có mẫu quang học không hợp lệ.")
    if np.any(ir <= 0) or np.any(ir >= 262143) or np.any(red <= 0) or np.any(red >= 262143):
        return _invalid("ADC chạm biên; cần kiểm tra tiếp xúc/LED và đo lại.")
    if np.std(ir) < 1 or np.std(red) < 1:
        return _invalid("Tín hiệu phẳng hoặc biên độ quá nhỏ.")
    # A sustained exact plateau is inconsistent with a usable unclipped PPG waveform.
    for values in (ir, red):
        changes = np.r_[0, np.flatnonzero(np.diff(values) != 0) + 1, len(values)]
        if np.max(np.diff(changes)) >= math.ceil(.2 * fs):
            return _invalid("Có đoạn phẳng kéo dài ít nhất 0,2 giây.")
    dc_ir, dc_red = float(np.mean(ir)), float(np.mean(red))
    sos = signal.butter(3, [.5, 5], btype="bandpass", fs=fs, output="sos")
    ac_ir = signal.sosfiltfilt(sos, signal.detrend(ir))
    ac_red = signal.sosfiltfilt(sos, signal.detrend(red))
    # Exclude edges from estimation, while showing the full filtered signal for inspection.
    trim = int(round(.75 * fs))
    x, y = ac_ir[trim:-trim], ac_red[trim:-trim]
    rms_ir, rms_red = float(np.sqrt(np.mean(x*x))), float(np.sqrt(np.mean(y*y)))
    if min(rms_ir, rms_red) < 1 or rms_ir / dc_ir < .0001:
        return _invalid("Phần dao động nhịp quá yếu so với nền.")
    low, high = math.ceil(fs * 60 / 240), math.floor(fs * 60 / 30)
    lags = np.arange(low, high + 1)
    acf = np.array([np.dot(x[k:], x[:-k]) / max(np.linalg.norm(x[k:])*np.linalg.norm(x[:-k]), 1e-12)
                    for k in lags])
    maxima, _ = signal.find_peaks(np.r_[-np.inf, acf, -np.inf])
    maxima = maxima - 1
    maxima = maxima[(maxima >= 0) & (maxima < len(acf))]
    if not len(maxima):
        return _invalid("Không tìm được chu kỳ mạch rõ trong khoảng 30–240 bpm.")
    best = float(np.max(acf[maxima]))
    candidates = maxima[acf[maxima] >= max(.2, .9 * best)]
    if not len(candidates):
        return _invalid("Tính tuần hoàn yếu; chưa đủ chất lượng tính nhịp.")
    chosen = int(candidates[0])
    bpm_auto = float(60 * fs / lags[chosen])
    periodicity = float(acf[chosen])
    # Check both polarities. No assumption that every sensor's systolic pulse points up.
    choices = []
    for polarity in (1, -1):
        peaks, _ = signal.find_peaks(polarity*x, distance=max(1, int(.25*fs)), prominence=.5*np.std(x))
        if len(peaks) < 5:
            continue
        ibi = np.diff(peaks) / fs
        bpm = float(60 / np.median(ibi))
        cv = float(np.std(ibi) / np.mean(ibi))
        choices.append((abs(bpm-bpm_auto), cv, bpm, peaks, polarity))
    if not choices:
        return _invalid("Không đủ nhịp rõ để kiểm tra khoảng cách nhịp.")
    difference, cv, bpm, peaks, polarity = min(choices, key=lambda c: (c[0], c[1]))
    correlation = float(np.corrcoef(x, y)[0, 1])
    ratio = (rms_red / dc_red) / (rms_ir / dc_ir)
    result = _invalid("")
    result["reasons"] = []
    result["quality"] = {"autocorrelation": periodicity, "red_ir_correlation": correlation,
                         "ibi_cv": cv, "bpm_autocorrelation": bpm_auto, "bpm_difference": difference,
                         "dc_ir": dc_ir, "dc_red": dc_red, "ac_ir_rms": rms_ir, "ac_red_rms": rms_red,
                         "ratio": float(ratio), "polarity": polarity}
    if not 30 <= bpm <= 240 or difference > max(5, .1*bpm) or cv > .25:
        result["reasons"].append("Các cách tính nhịp bất đồng hoặc khoảng nhịp biến thiên; cần kiểm tra waveform/đo lại.")
    else:
        result.update(bpm=bpm, bpm_valid=True)
    # Baseline only. Coefficients have NOT been calibrated to this module/filter/optics.
    spo2 = float(-45.060*ratio*ratio + 30.354*ratio + 94.845)
    if result["bpm_valid"] and correlation >= .8 and .02 < ratio < 1.84 and 0 < spo2 <= 100:
        result.update(spo2=spo2, spo2_valid=True)
    else:
        result["reasons"].append("SpO₂ chưa đủ điều kiện kỹ thuật; không ép kết quả vào 95–100%.")
    result["curve"] = [{"t": float(t), "ir_ac": float(a), "red_ac": float(b)}
                       for t, a, b in zip(samples["t"], ac_ir, ac_red)]
    result["peaks"] = [float(samples["t"].iloc[int(i)+trim]) for i in peaks]
    levels = [pulse_reference(result["bpm"]), oxygen_reference(result["spo2"])]
    present = [level for level in levels if level is not None]
    # Missing a channel must never turn a session into a green "normal" result.
    if present and (len(present) == 2 or any(level != LEVELS[0] for level in present)):
        result["reference_level"] = max(present, key=LEVELS.index)
    return result


def analyze(samples, temps, info):
    result = estimate_ppg(samples, info)
    result["temperature"] = temperature_summary(temps)
    if result["temperature"]["object"]["count"] < 5 and result["reference_level"] == LEVELS[0]:
        result["reference_level"] = None
        result["reasons"].append("Chưa đủ 5 lần nhiệt độ vật thể hợp lệ; không tổng hợp thành mức bình thường.")
    parts = []
    if result["bpm_valid"]:
        parts.append(f'Nhịp mạch ước tính {result["bpm"]:.1f} bpm: {pulse_reference(result["bpm"]).lower()} theo quy tắc tham khảo người lớn lúc nghỉ.')
    else:
        parts.append("Chưa có ước tính nhịp mạch đủ chất lượng.")
    if result["spo2_valid"]:
        parts.append(f'SpO₂ ước tính {result["spo2"]:.1f}% chưa hiệu chuẩn; mức tham khảo phải được kiểm chứng bằng máy đo đáng tin cậy.')
    else:
        parts.append("SpO₂ chưa đủ điều kiện để báo số.")
    temp = result["temperature"]["object"]
    if temp["value"] is not None:
        parts.append(f'Nhiệt độ bề mặt trung vị {temp["value"]:.2f} °C từ {temp["count"]} lần đọc; không phải thân nhiệt để kết luận sốt.')
    else:
        parts.append("Chưa có nhiệt độ vật thể hợp lệ.")
    result["summary"] = parts
    return result
