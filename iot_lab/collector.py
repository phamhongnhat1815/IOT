"""MQTT -> validate -> MongoDB durable inbox -> time-series projection -> ACK."""
import logging
import signal
import threading
import time
import json
import paho.mqtt.client as mqtt
from pymongo.errors import PyMongoError
import config
from alerts import validate_event, save_event, dispatch_commands
from model import validate
from storage import MongoStore, ConflictError
from monitoring import Monitor

log=logging.getLogger("collector")


def acknowledgement(record):
    """Called only after save_raw succeeds (including an identical durable retry)."""
    data=record["data"]
    return {"device_id":data["device_id"],"session_id":data["session_id"],
            "batch_index":data["batch_index"],"sample_count":data["sample_count"],"saved":True}


def configure_callbacks(client, store, monitor, raw_topic=None):
    """Shared by the running collector and isolated real-broker integration tests."""
    topic = raw_topic or config.MQTT_TOPIC
    def connected(c,u,flags,reason,props):
        if reason.is_failure: log.warning("MQTT connection refused: %s",reason);return
        c.subscribe(topic,qos=1)
        c.subscribe("iot/+/control_ack",qos=1)
        c.subscribe("iot/+/event",qos=1)
        log.info("MQTT subscriptions requested for %s and control_ack",topic)

    def received(c,u,msg):
        start=time.perf_counter()
        if msg.topic.endswith("/control_ack"):
            try:
                monitor.confirm(msg.topic,msg.payload)
                if msg.qos:c.ack(msg.mid,msg.qos)
            except (ValueError,TypeError,UnicodeDecodeError):
                log.warning("Rejected control ACK")
                if msg.qos:c.ack(msg.mid,msg.qos)
            except PyMongoError:
                log.warning("Control ACK could not be saved; retry on next command")
            return
        try:
            if msg.topic.endswith("/event"):
                data=validate_event(msg.payload,msg.topic)
                ack=save_event(store.db,data)
                c.publish(f'iot/{data["device_id"]}/event_ack',json.dumps(ack),qos=1,retain=False)
                if msg.qos:c.ack(msg.mid,msg.qos)
                log.info("ALERT device=%s kind=%s state=%s event=%s revision=%s",data["device_id"],data["kind"],data["state"],data["event_id"],data["revision"])
                return
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
    monitor=Monitor(store)
    monitor.setup()
    client=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id=config.MQTT_CLIENT_ID,clean_session=False,manual_ack=True)
    if config.MQTT_USER: client.username_pw_set(config.MQTT_USER,config.MQTT_PASSWORD)
    if config.MQTT_TLS: client.tls_set(ca_certs=config.MQTT_CA_FILE or None)
    client.reconnect_delay_set(1,30)
    stop=threading.Event()

    configure_callbacks(client,store,monitor)
    def command_worker():
        while not stop.wait(2):
            if client.is_connected():
                try: dispatch_commands(store.db,client)
                except (PyMongoError, OSError): log.warning("Command delivery unavailable; waiting for retry")
    threading.Thread(target=command_worker,name="alarm-commands",daemon=True).start()
    def finish(*_):stop.set();client.disconnect()
    signal.signal(signal.SIGINT,finish);signal.signal(signal.SIGTERM,finish)
    worker=threading.Thread(target=monitor.run,args=(client,stop),daemon=True,name="schedule-worker")
    worker.start()
    # Explicit outer reconnect also handles deliberate disconnect on failed DB writes.
    while not stop.is_set():
        try:
            client.connect(config.MQTT_HOST,config.MQTT_PORT,keepalive=30)
            client.loop_forever(retry_first_connection=True)
        except OSError as exc:
            log.warning("MQTT unavailable at %s:%s (%s, code=%s). Check MQTT_HOST, MQTT_PORT and broker service; retry in 3s.",
                        config.MQTT_HOST,config.MQTT_PORT,type(exc).__name__,
                        getattr(exc,"winerror",None) or getattr(exc,"errno",None))
        except PyMongoError as exc:
            log.warning("MongoDB unavailable (%s); retry in 3s.",type(exc).__name__)
        if not stop.is_set():stop.wait(3)


if __name__=="__main__": main()
