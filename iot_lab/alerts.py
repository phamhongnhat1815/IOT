"""Wearable event contract and durable remote alarm commands (MQTT application ACKs)."""
import hashlib
import json
import re
import time
import uuid
from datetime import datetime, timedelta, timezone

import paho.mqtt.client as mqtt
from pymongo.errors import DuplicateKeyError
from pymongo.write_concern import WriteConcern

ID = re.compile(r"[A-Za-z0-9_-]{1,39}\Z")
DEVICE = re.compile(r"[A-Za-z0-9_-]{1,31}\Z")


def validate_event(payload, topic):
    if len(payload) > 1024:
        raise ValueError("event too large")
    d = json.loads(payload)
    if not isinstance(d, dict):
        raise ValueError("event must be an object")
    device, event = d.get("device_id"), d.get("event_id")
    if not isinstance(device, str) or not DEVICE.fullmatch(device):
        raise ValueError("invalid event device")
    if topic != f"iot/{device}/event" or not isinstance(event, str) or not ID.fullmatch(event):
        raise ValueError("event topic/identity mismatch")
    if type(d.get("schema_version")) is not int or d["schema_version"] != 1:
        raise ValueError("invalid event schema")
    if d.get("kind") not in ("fall", "sos") or d.get("state") not in ("active", "cleared"):
        raise ValueError("invalid event kind/state")
    revision = d.get("revision")
    if type(revision) is not int or revision != (1 if d["state"] == "active" else 2):
        raise ValueError("invalid event revision")
    for key, maximum in (("uptime_ms", 0xffffffff), ("occurred_at", 4102444800)):
        if type(d.get(key)) is not int or not 0 <= d[key] <= maximum:
            raise ValueError("invalid event clock")
    command = d.get("command_id", "")
    if not isinstance(command, str) or (command and not ID.fullmatch(command)) or (command and revision != 2):
        raise ValueError("invalid command acknowledgement")
    if d.get("detector") != "pendant_sequence_trial_v1":
        raise ValueError("unknown detector version")
    return {key: d.get(key, "") for key in (
        "schema_version", "device_id", "event_id", "revision", "kind", "state",
        "uptime_ms", "occurred_at", "command_id", "detector")}


def save_event(db, data):
    """Return an ACK only after immutable event + latest state are durably written."""
    event_key = f'{data["device_id"]}:{data["event_id"]}'
    key = f'{event_key}:{data["revision"]}'
    digest = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    now = datetime.now(timezone.utc)
    events = db.get_collection("alert_events", write_concern=WriteConcern(w=1, j=True))
    try:
        events.insert_one({"_id": key, "data": data, "digest": digest, "received_at": now})
    except DuplicateKeyError:
        if events.find_one({"_id": key}, {"digest": 1}).get("digest") != digest:
            raise ValueError("conflicting event replay")
    states = db.get_collection("alert_states", write_concern=WriteConcern(w=1, j=True))
    # Newer state cannot be rolled back by delayed/replayed active messages.
    try:
        states.update_one({"_id": event_key, "revision": {"$lt": data["revision"]}},
                          {"$set": {**data, "received_at": now}}, upsert=True)
    except DuplicateKeyError:
        pass  # Existing revision is equal/newer.
    if data["command_id"]:
        db.get_collection("alert_commands", write_concern=WriteConcern(w=1, j=True)).update_one(
            {"_id": data["command_id"], "device_id": data["device_id"], "event_id": data["event_id"]},
            {"$set": {"status": "confirmed", "confirmed_at": now}})
    return {"device_id": data["device_id"], "event_id": data["event_id"],
            "revision": data["revision"], "saved": True}


def queue_clear(db, device, event):
    if not DEVICE.fullmatch(device) or not ID.fullmatch(event):
        raise ValueError("invalid alarm identity")
    if not db.alert_states.find_one({"device_id": device, "event_id": event, "state": "active"}):
        raise ValueError("alarm is no longer active")
    now = datetime.now(timezone.utc)
    command = {"_id": uuid.uuid4().hex, "device_id": device, "event_id": event,
               "action": "clear_alarm", "created_at": now,
               "expires_at": int(time.time()) + 60, "status": "queued"}
    db.get_collection("alert_commands", write_concern=WriteConcern(w=1, j=True)).insert_one(command)
    return command["_id"]


def dispatch_commands(db, client, now=None):
    now = int(time.time()) if now is None else now
    db.alert_commands.update_many({"status": {"$in": ["queued", "sent"]}, "expires_at": {"$lt": now}},
                                 {"$set": {"status": "unconfirmed"}})
    for row in db.alert_commands.find({"status": {"$in": ["queued", "sent"]},
                                      "expires_at": {"$gte": now}}).limit(32):
        payload = {"device_id": row["device_id"], "event_id": row["event_id"],
                   "command_id": row["_id"], "action": "clear_alarm", "expires_at": row["expires_at"]}
        result = client.publish(f'iot/{row["device_id"]}/command', json.dumps(payload), qos=1, retain=False)
        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            db.alert_commands.update_one({"_id": row["_id"], "status": {"$in": ["queued", "sent"]}},
                                         {"$set": {"status": "sent"}})


def render_alert_panel(st, store, auto=True):
    """Render before measurement selectors so alarm-only devices can be controlled."""
    @st.fragment(run_every="2s" if auto else None)
    def panel():
        from pymongo.errors import PyMongoError
        st.subheader("Cảnh báo SOS / nghi ngã")
        st.caption("Phát hiện ngã thử nghiệm từ MPU6050. Thời gian bên dưới là lúc máy chủ nhận sự kiện.")
        try:
            rows = list(store.db.alert_states.find().sort("received_at", -1).limit(30))
            if not rows:
                st.info("Chưa nhận sự kiện SOS/ngã. Không có sự kiện không chứng minh thiết bị đang online.")
            for row in rows:
                with st.container(border=True):
                    label = "NGHI NGÃ" if row["kind"] == "fall" else "SOS"
                    st.write(f'{row["device_id"]} · {label} · {row["received_at"].isoformat(timespec="seconds")}')
                    if row["state"] == "active":
                        st.error("Đã nhận báo động; chưa có xác nhận tắt từ thiết bị.")
                        if st.button("Yêu cầu tắt báo động", key="clear-" + row["_id"]):
                            queue_clear(store.db, row["device_id"], row["event_id"])
                            st.info("Đã tạo yêu cầu. Chờ collector gửi và ESP32 xác nhận, chưa coi là đã tắt.")
                    else:
                        st.success("ESP32 đã xác nhận tắt báo động.")
                    commands = list(store.db.alert_commands.find({"device_id": row["device_id"],
                        "event_id": row["event_id"]}).sort("created_at", -1).limit(1))
                    if commands:
                        c = commands[0]
                        status = c["status"]
                        if status in ("queued", "sent") and c["expires_at"] < time.time():
                            status = "unconfirmed"
                        st.caption({"queued": "Chờ collector gửi lệnh", "sent": "Đã gửi lệnh, chờ ESP32 xác nhận",
                                    "confirmed": "ESP32 đã xác nhận lệnh", "unconfirmed": "Hết hạn chờ; chưa xác nhận tắt. Có thể gửi lại."}[status])
            if st.button("Làm mới cảnh báo", key="refresh-alerts"):
                st.rerun(scope="fragment")
        except (PyMongoError, ValueError):
            st.error("Chưa đọc/gửi được cảnh báo. Kiểm tra MongoDB và quyền tài khoản.")
    panel()
