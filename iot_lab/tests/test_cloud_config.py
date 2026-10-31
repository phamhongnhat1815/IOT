import sys
import unittest
from pathlib import Path
from io import StringIO
from dotenv import dotenv_values

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from configure_mqtt_cloud import update_env, cloud_header


class CloudConfigTests(unittest.TestCase):
    def test_cloud_settings_preserve_mongo_and_roundtrip_password(self):
        original = 'MONGO_URI=mongodb://127.0.0.1:27017\nMONGO_DB=signal_lab\nMQTT_HOST=old\n'
        password = "space ' quote \\ dollar ${NOT_AN_ENV_VAR} and #"
        result = update_env(original, {'MQTT_HOST': 'private.example.com',
                                       'MQTT_PASSWORD': password, 'MQTT_TLS': 'true'})
        values = dotenv_values(stream=StringIO(result), interpolate=False)
        self.assertEqual(values['MONGO_URI'], 'mongodb://127.0.0.1:27017')
        self.assertEqual(values['MONGO_DB'], 'signal_lab')
        self.assertEqual(values['MQTT_HOST'], 'private.example.com')
        self.assertEqual(values['MQTT_PASSWORD'], password)

    def test_header_escapes_quotes_and_newlines_for_cpp(self):
        text = cloud_header('private.example.com', 8883, 'device', 'a"b\\c',
                            '-----BEGIN CERTIFICATE-----\nCA\n-----END CERTIFICATE-----\n')
        self.assertIn('"a\\"b\\\\c"', text)
        self.assertIn('CERTIFICATE-----\\nCA\\n', text)
        self.assertNotIn('setInsecure', text)


if __name__ == '__main__':
    unittest.main()
