"""Persistent schedules, notifications and MQTT outbox. Run by ONE collector."""
import hashlib
import json
import re
import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from frames import frames
from physiology import analyze

# Bangkok has no daylight saving time; fixed offset also works on Windows without tzdata.
LOCAL = timezone(timedelta(hours=7), "Asia/Bangkok")
UTC = timezone.utc
log = logging.getLogger("monitoring")
DAYS = ["Thứ hai", "Thứ ba", "Thứ tư", "Thứ năm", "Thứ sáu", "Thứ bảy", "Chủ nhật"]
DEFAULT_LIMITS = {"bpm": {"enabled": True, "low": 60., "high": 100.},
                  "spo2": {"enabled": True, "low": 95., "high": 100.},
                  "object_temp": {"enabled": False, "low": 30., "high": 40.}}


def local_time(value):
    return value.astimezone(LOCAL).strftime("%d/%m/%Y %H:%M") if value else "—"


def identity(*parts):
    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()


def occurrence_state(now, deadline, sessions):
    """A poor/incomplete measurement is never classified as an absent measurement."""
    if any(s.get("complete") and s.get("good") for s in sessions):
        return "success"
    if any(s.get("complete") for s in sessions):
        return "poor"
    if sessions:
        return "poor" if now >= deadline else "receiving"
    return "missed" if now >= deadline else "due"


def exceeded(result, limits):
    for key, rule in limits.items():
        if not rule.get("enabled"):
            continue
        if key == "object_temp":
            temp = result["temperature"]["object"]
            value = temp["value"] if temp["stable"] else None
        else:
            value = result.get(key) if result.get(key + "_valid") else None
        if value is not None and (value < rule["low"] or value > rule["high"]):
            yield key, value, rule


class Monitor:
    def __init__(self, store):
        self.store, self.db = store, store.db

    def setup(self):
        self.db.schedules.create_index("device_id")
        self.db.occurrences.create_index([("device_id", 1), ("due_at", -1)])
        self.db.notifications.create_index([("created_at", -1)])
        self.db.session_summaries.create_index([("device_id", 1), ("first_received", 1)])

    def save_schedule(self, device, hour, weekdays, grace, enabled=True, schedule_id=None):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,31}", device):
            raise ValueError("Thiết bị chỉ gồm chữ, số, dấu - hoặc _, tối đa 31 ký tự.")
        datetime.strptime(hour, "%H:%M")
        if not weekdays or not set(weekdays) <= set(range(7)) or not 1 <= grace <= 1440:
            raise ValueError("Chọn ngày lặp lại và khoảng chờ từ 1 đến 1440 phút.")
        now = datetime.now(UTC)
        key = schedule_id or uuid4().hex
        self.db.schedules.update_one({"_id": key}, {"$set": {
            "device_id": device, "hour": hour, "weekdays": sorted(weekdays),
            "grace_minutes": grace, "enabled": enabled, "active_from": now,
            "cursor_date": None, "updated_at": now}, "$setOnInsert": {"created_at": now}}, upsert=True)
        # Existing reminders keep history but must not send commands after an edit/disable.
        self.cancel_pending(key)
        return key

    def cancel_pending(self, key):
        ids = [r["_id"] for r in self.db.occurrences.find({"schedule_id": key, "status": {"$in": ["due", "receiving"]}})]
        if ids:
            self.db.occurrences.update_many({"_id": {"$in": ids}}, {"$set": {"status": "cancelled"}})
        self.db.notifications.update_many({"schedule_id": key, "mqtt_status": {"$in": ["pending", "published"]}},
                                          {"$set": {"mqtt_status": "cancelled"}})

    def delete_schedule(self, key):
        self.cancel_pending(key)
        self.db.schedules.delete_one({"_id": key})

    def limits(self):
        doc = self.db.monitor_settings.find_one({"_id": "limits"})
        return doc["values"] if doc else DEFAULT_LIMITS

    def notify(self, key, kind, device, message, now, expires=None, schedule_id=None):
        self.db.notifications.update_one({"_id": key}, {"$setOnInsert": {
            "kind": kind, "device_id": device, "message": message, "created_at": now,
            "read": False, "schedule_id": schedule_id, "expires_at": expires,
            "mqtt_status": "pending" if expires else "not_required", "confirmed_at": None}}, upsert=True)

    def scan_sessions(self, now):
        # Raw inbox is durable and deduplicated, even while time-series projection is delayed.
        groups = self.db.raw_inbox.aggregate([
            {"$group": {"_id": {"device": "$meta.device_id", "session": "$session_id"},
                         "first": {"$min": "$ts"}, "last": {"$max": "$ts"}, "count": {"$sum": 1}}}])
        limits = self.limits()
        for group in groups:
            device, session = group["_id"]["device"], group["_id"]["session"]
            key = identity(device, session)
            old = self.db.session_summaries.find_one({"_id": key})
            if old and old.get("packet_count") == group["count"] and old.get("last_received") == group["last"]:
                continue
            packets = list(self.db.raw_inbox.find({"meta.device_id": device, "session_id": session}))
            samples, temps, info = frames(packets)
            result = analyze(samples, temps, info)
            self.db.session_summaries.replace_one({"_id": key}, {
                "_id": key, "device_id": device, "session_id": session,
                "first_received": group["first"], "last_received": group["last"],
                "packet_count": group["count"], "complete": info["complete"],
                "good": result["bpm_valid"] and result["spo2_valid"], "reasons": result["reasons"]}, upsert=True)
            if info["complete"]:
                for channel, value, rule in exceeded(result, limits):
                    label = {"bpm": "BPM", "spo2": "SpO₂", "object_temp": "Nhiệt độ bề mặt"}[channel]
                    self.notify(identity(device, session, channel), "threshold", device,
                                f"{label}: {value:.1f}; ngoài ngưỡng {rule['low']:g}–{rule['high']:g}. Phiên {session}.", now)

    def schedule_tick(self, now):
        today = now.astimezone(LOCAL).date()
        for schedule in self.db.schedules.find({"enabled": True}):
            start = schedule["active_from"]
            cursor = schedule.get("cursor_date")
            day = datetime.strptime(cursor, "%Y-%m-%d").date() if cursor else start.astimezone(LOCAL).date()
            while day <= today:
                due = datetime.combine(day, datetime.strptime(schedule["hour"], "%H:%M").time(), LOCAL).astimezone(UTC)
                if day.weekday() in schedule["weekdays"] and start <= due <= now:
                    key = identity(schedule["_id"], day.isoformat())
                    self.db.occurrences.update_one({"_id": key}, {"$setOnInsert": {
                        "schedule_id": schedule["_id"], "device_id": schedule["device_id"],
                        "due_at": due, "deadline": due + timedelta(minutes=schedule["grace_minutes"]),
                        "status": "due"}}, upsert=True)
                day += timedelta(days=1)
            self.db.schedules.update_one({"_id": schedule["_id"]}, {"$set": {"cursor_date": today.isoformat()}})
        for occurrence in self.db.occurrences.find({"status": {"$in": ["due", "receiving", "poor", "missed"]}}):
            sessions = list(self.db.session_summaries.find({"device_id": occurrence["device_id"],
                "first_received": {"$gte": occurrence["due_at"], "$lte": occurrence["deadline"]}}))
            state = occurrence_state(now, occurrence["deadline"], sessions)
            self.db.occurrences.update_one({"_id": occurrence["_id"]}, {"$set": {"status": state}})
            if state in ("success", "poor", "receiving"):
                self.db.notifications.update_many({"_id": {"$in": [identity(occurrence["_id"], "due"), identity(occurrence["_id"], "missed")]},
                    "mqtt_status": {"$in": ["pending", "published"]}}, {"$set": {"mqtt_status": "cancelled"}})
            if not sessions:
                missed = state == "missed"
                kind = "measurement_missed" if missed else "measurement_due"
                suffix = "missed" if missed else "due"
                expires = occurrence["deadline"] + timedelta(minutes=30) if missed else occurrence["deadline"]
                text = ("Bỏ lịch đo" if missed else "Đến giờ đo") + " lúc " + local_time(occurrence["due_at"])
                self.notify(identity(occurrence["_id"], suffix), kind, occurrence["device_id"], text,
                            now, expires, occurrence["schedule_id"])

    def dispatch(self, client, now):
        self.db.notifications.update_many({"mqtt_status": {"$in": ["pending", "published"]},
            "expires_at": {"$lte": now}}, {"$set": {"mqtt_status": "expired"}})
        if not client.is_connected():
            return
        for row in self.db.notifications.find({"mqtt_status": {"$in": ["pending", "published"]},
            "expires_at": {"$gt": now}, "$or": [{"last_attempt": {"$exists": False}},
            {"last_attempt": {"$lte": now - timedelta(seconds=30)}}]}):
            payload = {"event_id": row["_id"], "device_id": row["device_id"], "event": row["kind"],
                       "expires_at": int(row["expires_at"].timestamp())}
            claimed = self.db.notifications.update_one({"_id": row["_id"],
                "mqtt_status": {"$in": ["pending", "published"]}, "expires_at": {"$gt": now}},
                {"$set": {"last_attempt": now}})
            if not claimed.matched_count:
                continue
            try:
                sent = client.publish(f"iot/{row['device_id']}/control", json.dumps(payload), qos=1, retain=False)
                sent.wait_for_publish(timeout=3)
                if sent.is_published():
                    self.db.notifications.update_one({"_id": row["_id"], "mqtt_status": {"$in": ["pending", "published"]}},
                        {"$set": {"mqtt_status": "published", "published_at": now}})
            except (RuntimeError, ValueError):
                log.warning("Control publish not confirmed by broker")

    def confirm(self, topic, payload):
        parts = topic.split("/")
        if len(parts) != 3 or parts[0] != "iot" or parts[2] != "control_ack" or len(payload) > 512:
            raise ValueError("Invalid control ACK")
        body = json.loads(payload)
        if not isinstance(body, dict) or body.get("device_id") != parts[1] or body.get("received") is not True or not isinstance(body.get("event_id"), str):
            raise ValueError("Invalid control ACK identity")
        self.db.notifications.update_one({"_id": body["event_id"], "device_id": parts[1],
            "mqtt_status": {"$in": ["pending", "published"]}, "last_attempt": {"$exists": True}},
            {"$set": {"mqtt_status": "confirmed", "confirmed_at": datetime.now(UTC)}})

    def run(self, client, stop):
        while not stop.is_set():
            try:
                now = datetime.now(UTC)
                self.scan_sessions(now)
                self.schedule_tick(now)
                self.dispatch(client, now)
                self.db.monitor_state.update_one({"_id": "worker"}, {"$set": {"heartbeat": now}}, upsert=True)
            except Exception:
                log.exception("Schedule worker failed; retrying in 15 seconds")
            stop.wait(15)
