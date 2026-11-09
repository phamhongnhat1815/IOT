"""MQTT -> validate -> MongoDB durable inbox -> time-series projection -> ACK."""
import logging
import signal
import threading
import time
import json
import paho.mqtt.client as mqtt
from pymongo.errors import PyMongoError
import config
from model import validate
from storage import MongoStore, ConflictError

log=logging.getLogger("collector")


def acknowledgement(record):
    """Called only after save_raw succeeds (including an identical durable retry)."""
    data=record["data"]
    return {"device_id":data["device_id"],"session_id":data["session_id"],
            "batch_index":data["batch_index"],"sample_count":data["sample_count"],"saved":True}


def main():
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    try:store=MongoStore()
    except (ValueError,PyMongoError):
        log.error("Cau hinh MONGO_URI trong .env; chay check_connection.bat de kiem tra.")
        return
    while True:
        try: store.setup();break
        except PyMongoError:
            log.warning("MongoDB unavailable; retry in 5s");time.sleep(5)
    store.project_pending()
    client=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id=config.MQTT_CLIENT_ID,clean_session=False,manual_ack=True)
    if config.MQTT_USER: client.username_pw_set(config.MQTT_USER,config.MQTT_PASSWORD)
    if config.MQTT_TLS: client.tls_set(ca_certs=config.MQTT_CA_FILE or None)
    client.reconnect_delay_set(1,30)
    stop=threading.Event()

    def connected(c,u,flags,reason,props):
        if reason.is_failure: log.warning("MQTT connection refused: %s",reason);return
        c.subscribe(config.MQTT_TOPIC,qos=1)
        log.info("MQTT subscribed to %s",config.MQTT_TOPIC)

    def received(c,u,msg):
        start=time.perf_counter()
        try:
            record=validate(msg.payload,msg.topic)
            db_start=time.perf_counter()
            fresh=store.save_raw(record)
            raw_write_ms=(time.perf_counter()-db_start)*1000
        except (ValueError,TypeError,KeyError,ZeroDivisionError,UnicodeDecodeError) as exc:
            try: store.quarantine(msg.topic,exc,msg.payload)
            except PyMongoError: log.warning("Could not store rejected-message report")
            log.warning("Rejected packet: %s",exc)
            if msg.qos:c.ack(msg.mid,msg.qos)
            return
        except PyMongoError:
            log.error("Mongo write failed: no application ACK; publisher must retry")
            # Reconnect a persistent MQTT session for QoS1 redelivery.
            c.disconnect()
            return
        # Only ACK after the raw packet is durable, never on mere receipt.
        data=record["data"]
        ack=acknowledgement(record)
        c.publish(f'iot/{data["device_id"]}/ack',json.dumps(ack),qos=1,retain=False)
        if msg.qos:c.ack(msg.mid,msg.qos)
        try: store.project_pending(20)
        except PyMongoError: log.warning("Time-series projection pending; raw packet is durable")
        log.info("%s batch=%d/%d new=%s db_ms=%.1f collector_ms=%.1f publish_to_python_ms=%s",
                 data["device_id"],data["batch_index"],data["batch_total"],fresh,
                 raw_write_ms,(time.perf_counter()-start)*1000,record["e2e_ms"])

    client.on_connect=connected;client.on_message=received
    def finish(*_):stop.set();client.disconnect()
    signal.signal(signal.SIGINT,finish);signal.signal(signal.SIGTERM,finish)
    # Explicit outer reconnect also handles deliberate disconnect on failed DB writes.
    while not stop.is_set():
        try:
            client.connect(config.MQTT_HOST,config.MQTT_PORT,keepalive=30)
            client.loop_forever(retry_first_connection=True)
        except (OSError,PyMongoError):log.warning("Connection unavailable; retry")
        if not stop.is_set():stop.wait(3)


if __name__=="__main__": main()
