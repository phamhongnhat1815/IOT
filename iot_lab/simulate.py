"""Explicit synthetic publisher for testing the real MQTT->Mongo pipeline."""
import argparse
import json
import time
import paho.mqtt.client as mqtt
import config
import demo


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--realtime",action="store_true")
    args=parser.parse_args()
    client=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id="signal-lab-simulator")
    if config.MQTT_USER:client.username_pw_set(config.MQTT_USER,config.MQTT_PASSWORD)
    if config.MQTT_TLS:client.tls_set(ca_certs=config.MQTT_CA_FILE or None)
    client.connect(config.MQTT_HOST,config.MQTT_PORT);client.loop_start()
    session="sim-"+str(time.time_ns())
    try:
        for record in demo.packets():
            payload={**record["data"],"device_id":"simulator","session_id":session,
                     "sent_at_ms":int(time.time()*1000),"clock_synced":True}
            info=client.publish("iot/simulator/raw",json.dumps(payload),qos=1)
            info.wait_for_publish(timeout=10)
            if not info.is_published():raise RuntimeError("Broker did not acknowledge publish")
            if args.realtime:time.sleep(.5)
    finally:client.disconnect();client.loop_stop()
    print("Published synthetic session:",session)


if __name__=="__main__":main()
