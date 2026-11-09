"""Run actual firmware reminder policy on the host, without Arduino/hardware."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class ReminderFirmwareTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("c++"), "native C++ compiler required")
    def test_persistent_reminder_and_output_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = str(Path(tmp) / "reminder_test.exe")
            subprocess.run(["c++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                            "-I", str(ROOT / "firmware/HealthRawDirect"),
                            str(ROOT / "iot_lab/tests/cpp/reminder_test.cpp"), "-o", binary],
                           check=True, capture_output=True)
            subprocess.run([binary], check=True, capture_output=True)


if __name__ == "__main__":
    unittest.main()
