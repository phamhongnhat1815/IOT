import sys
import unittest
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from physiology import analyze, estimate_ppg, temperature_summary, pulse_reference, oxygen_reference


def waveform(bpm=80, ratio=.5, fs=100, seconds=15, invert=False):
    t = np.arange(int(seconds*fs))/fs
    wave = np.sin(2*np.pi*bpm/60*t) + .15*np.sin(4*np.pi*bpm/60*t)
    if invert:
        wave = -wave
    samples = pd.DataFrame({'index': np.arange(len(t)), 't': t,
                            'ir': 80000+1200*wave, 'red': 70000+1200*ratio*70000/80000*wave,
                            'segment': 0})
    return samples, {'complete': True, 'rate': fs}


class PhysiologyTests(unittest.TestCase):
    def test_known_rate_across_sample_rates_and_polarities(self):
        for fs, bpm, inverse in ((100, 80, False), (50, 120, True), (100, 45, False), (100, 150, False)):
            with self.subTest(fs=fs, bpm=bpm):
                raw, info = waveform(bpm=bpm, fs=fs, invert=inverse)
                before = raw.copy(deep=True)
                result = estimate_ppg(raw, info)
                self.assertTrue(result['bpm_valid'], result['reasons'])
                self.assertAlmostEqual(result['bpm'], bpm, delta=2)
                self.assertTrue(raw.equals(before))

    def test_ratio_and_spo2_are_estimates_not_clinical_validation(self):
        raw, info = waveform(ratio=.5)
        result = estimate_ppg(raw, info)
        self.assertTrue(result['spo2_valid'])
        self.assertAlmostEqual(result['quality']['ratio'], .5, places=5)
        self.assertAlmostEqual(result['spo2'], 98.757, places=2)
        self.assertEqual(result['calibration_status'], 'unvalidated')
        self.assertIsNone(result['clinical_level'])

    def test_incomplete_gaps_clipping_and_flatline_never_report_normal(self):
        original, info = waveform()
        cases = [(original, {**info, 'complete': False})]
        gap = original.drop(index=500)
        cases.append((gap, info))
        flat = original.copy(); flat['ir'] = 80000
        cases.append((flat, info))
        clipped = original.copy(); clipped.loc[100:120, 'ir'] = 262143
        cases.append((clipped, info))
        for raw, meta in cases:
            result = estimate_ppg(raw, meta)
            self.assertIsNone(result['bpm'])
            self.assertIsNone(result['spo2'])
            self.assertIsNone(result['reference_level'])

    def test_random_noise_is_not_a_pulse(self):
        raw, info = waveform()
        rng = np.random.default_rng(100)
        raw['ir'] = 80000+rng.normal(0, 1000, len(raw))
        raw['red'] = 70000+rng.normal(0, 1000, len(raw))
        result = estimate_ppg(raw, info)
        self.assertFalse(result['bpm_valid'])

    def test_bad_red_quality_does_not_invent_spo2(self):
        raw, info = waveform()
        raw['red'] = 70000 + 800*np.sin(2*np.pi*1.9*raw['t'])
        result = estimate_ppg(raw, info)
        self.assertTrue(result['bpm_valid'])
        self.assertIsNone(result['spo2'])
        self.assertIsNone(result['reference_level'])

    def test_temperature_median_keeps_outlier_visible_and_deduplicates(self):
        temps = pd.DataFrame({'temperature_at_ms': list(range(15))+[0],
                              'object_temp': [34.2]*14+[80, 34.2], 'ambient_temp': [28]*16})
        result = temperature_summary(temps)
        self.assertEqual(result['object']['count'], 15)
        self.assertEqual(result['object']['value'], 34.2)
        self.assertEqual(result['object']['max'], 80)
        self.assertFalse(result['object']['stable'])
        self.assertFalse(result['body_temperature'])

    def test_invalid_temperature_is_not_zero_or_fever(self):
        temps = pd.DataFrame({'object_temp': [np.nan, float('inf'), 400], 'ambient_temp': [28]*3})
        result = temperature_summary(temps)
        self.assertIsNone(result['object']['value'])
        self.assertEqual(result['object']['invalid_count'], 3)

    def test_reference_boundaries_do_not_leave_fractional_gaps(self):
        for value, level in ((92, 'Nguy hiểm'), (92.1, 'Cảnh báo'), (94.9, 'Cảnh báo'), (95, 'Bình thường')):
            self.assertEqual(oxygen_reference(value), level)
        self.assertEqual(pulse_reference(40), 'Nguy hiểm')
        self.assertEqual(pulse_reference(60), 'Bình thường')
        self.assertEqual(pulse_reference(100), 'Bình thường')
        self.assertEqual(pulse_reference(131), 'Nguy hiểm')

    def test_missing_temperature_cannot_make_combined_result_normal(self):
        raw, info = waveform()
        temps = pd.DataFrame({'object_temp': [34.2]*3, 'ambient_temp': [28]*3})
        result = analyze(raw, temps, info)
        self.assertTrue(result['bpm_valid'])
        self.assertTrue(result['spo2_valid'])
        self.assertIsNone(result['reference_level'])
        self.assertIsNone(result['clinical_level'])


if __name__ == '__main__':
    unittest.main()
