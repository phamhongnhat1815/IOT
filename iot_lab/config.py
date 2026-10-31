import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env", interpolate=False)
MONGO_URI = os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017").strip()
MONGO_DB = os.getenv("MONGO_DB", "signal_lab")
RETENTION_DAYS = int(os.getenv("RETENTION_DAYS", "7"))
if not 1 <= RETENTION_DAYS <= 3650:
    raise ValueError("RETENTION_DAYS must be 1..3650")
MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "iot/+/raw")
MQTT_USER = os.getenv("MQTT_USER", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
MQTT_TLS = os.getenv("MQTT_TLS", "false").lower() == "true"
MQTT_CA_FILE = os.getenv("MQTT_CA_FILE", "").strip()
if MQTT_CA_FILE and not Path(MQTT_CA_FILE).is_absolute():
    MQTT_CA_FILE = str(ROOT / MQTT_CA_FILE)
MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", "signal-lab-collector")
