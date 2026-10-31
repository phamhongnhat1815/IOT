"""Configure the same private TLS broker in Python and ESP32, without echoing passwords."""
import getpass
import json
from pathlib import Path
import re
import shutil
import ssl
import uuid

ROOT = Path(__file__).resolve().parent


def cloud_header(host, port, username, password, ca):
    quote = lambda value: json.dumps(value, ensure_ascii=True)
    return ('#pragma once\n// Generated locally; do not share credentials.\n'
            f'constexpr char CLOUD_HOST[] = {quote(host)};\n'
            f'constexpr unsigned short CLOUD_PORT = {port};\n'
            f'constexpr char CLOUD_USER[] = {quote(username)};\n'
            f'constexpr char CLOUD_PASSWORD[] = {quote(password)};\n'
            f'constexpr char CLOUD_CA[] = {quote(ca)};\n')


def update_env(text, settings):
    for key, value in settings.items():
        # Quoted dotenv values safely preserve spaces, quotes and backslashes.
        encoded = "'" + str(value).replace('\\', '\\\\').replace("'", "\\'") + "'"
        pattern = rf'(?m)^{re.escape(key)}\s*=.*$'
        line = f'{key}={encoded}'
        if re.search(pattern, text):
            text = re.sub(pattern, lambda _: line, text)
        else:
            text = text.rstrip('\r\n') + '\n' + line + '\n'
    return text


def atomic_write(path, text):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(text, encoding='utf-8')
    temporary.replace(path)


def main():
    print('MQTT CLOUD TLS - giu nguyen MongoDB va Wi-Fi. Khong FORMAT ESP32.')
    host = input('Broker hostname (khong https://, khong :port): ').strip()
    if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?', host) or '.' not in host:
        raise ValueError('Hostname khong hop le')
    port = int(input('TLS port [8883]: ').strip() or '8883')
    if not 1 <= port <= 65535:
        raise ValueError('Port khong hop le')
    username = input('MQTT username: ').strip()
    password = getpass.getpass('MQTT password (khong hien ky tu): ')
    if not username or not password or any(c in username + password for c in '\r\n\x00'):
        raise ValueError('Username/password trong hoac co ky tu khong hop le')
    ca_path = Path(input('Duong dan CA certificate .pem/.crt tai tu broker: ').strip().strip('"')).expanduser()
    ca = ca_path.read_text(encoding='utf-8-sig')
    ssl.create_default_context(cadata=ca)  # Reject malformed CA before writing settings.
    cert_dir = ROOT / 'data' / 'certs'
    cert_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(cert_dir / 'mqtt-ca.pem', ca)
    env_path = ROOT / '.env'
    original = env_path.read_text(encoding='utf-8-sig') if env_path.exists() else (ROOT / '.env.example').read_text(encoding='utf-8')
    if env_path.exists():
        shutil.copy2(env_path, ROOT / '.env.before-cloud')
    atomic_write(ROOT.parent / 'firmware' / 'HealthRawDirect' / 'MqttCloud.h',
                 cloud_header(host, port, username, password, ca))
    settings = {'MQTT_HOST': host, 'MQTT_PORT': port, 'MQTT_USER': username,
                'MQTT_PASSWORD': password, 'MQTT_TLS': 'true',
                'MQTT_CA_FILE': 'data/certs/mqtt-ca.pem', 'MQTT_TOPIC': 'iot/+/raw',
                'MQTT_CLIENT_ID': 'signal-lab-' + uuid.uuid4().hex[:12]}
    atomic_write(env_path, update_env(original, settings))
    print('OK: .env va firmware/HealthRawDirect/MqttCloud.h da cung broker TLS.')
    print('Chay check_mqtt.py; restart collector; mo HealthRawDirect.ino va Upload.')
    print('Giu Erase All Flash=Disabled. Khong FORMAT. Khong chia se .env/MqttCloud.h.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, ssl.SSLError) as exc:
        raise SystemExit(f'Cau hinh chua hoan tat: {exc}')
