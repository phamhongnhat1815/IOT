"""Check broker authentication, TLS and actual subscription permission; no sensor payloads."""
import threading
import uuid
import paho.mqtt.client as mqtt
import config


def main():
    done = threading.Event()
    outcome = {'ok': False}
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                         client_id='signal-check-' + uuid.uuid4().hex[:12])
    if config.MQTT_USER:
        client.username_pw_set(config.MQTT_USER, config.MQTT_PASSWORD)
    if config.MQTT_TLS:
        client.tls_set(ca_certs=config.MQTT_CA_FILE or None)

    def connected(c, u, flags, reason, props):
        if reason.is_failure:
            print('MQTT rejected:', reason)
            done.set()
        else:
            c.subscribe(config.MQTT_TOPIC, qos=1)

    def subscribed(c, u, mid, reasons, props):
        outcome['ok'] = bool(reasons) and all(not code.is_failure for code in reasons)
        print('OK: MQTT connected and subscribed' if outcome['ok'] else 'ERROR: subscription denied')
        done.set()

    client.on_connect = connected
    client.on_subscribe = subscribed
    try:
        print(f'Broker: {config.MQTT_HOST}:{config.MQTT_PORT}; TLS={config.MQTT_TLS}')
        client.connect(config.MQTT_HOST, config.MQTT_PORT, keepalive=30)
        client.loop_start()
        if not done.wait(15):
            print('ERROR: no broker response within 15 seconds')
    except (OSError, ValueError) as exc:
        print('ERROR:', type(exc).__name__, '- check hostname, port, CA and credentials locally')
    finally:
        client.disconnect()
        client.loop_stop()
    return 0 if outcome['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
