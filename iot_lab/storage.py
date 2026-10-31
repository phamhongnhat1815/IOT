from datetime import datetime, timedelta, timezone
from pymongo import MongoClient, ASCENDING
from pymongo.errors import DuplicateKeyError, CollectionInvalid
from pymongo.write_concern import WriteConcern
import config


class ConflictError(ValueError): pass


class MongoStore:
    def __init__(self,uri=None,database=None):
        connection=uri or config.MONGO_URI
        if not connection or "YOUR_CLUSTER" in connection or "DB_USER:" in connection:
            raise ValueError("Chưa cấu hình MONGO_URI. Kiểm tra iot_lab/.env.")
        self.client=MongoClient(connection,serverSelectionTimeoutMS=7000,tz_aware=True)
        self.db=self.client[database or config.MONGO_DB]

    def ping(self): self.client.admin.command("ping")

    def setup(self):
        self.ping()
        ttl=config.RETENTION_DAYS*86400
        for name in ("raw_timeseries","processed_timeseries"):
            try:
                self.db.create_collection(name,timeseries={"timeField":"ts","metaField":"meta","granularity":"seconds"},expireAfterSeconds=ttl)
            except CollectionInvalid:
                info=self.db.command("listCollections",filter={"name":name})["cursor"]["firstBatch"][0]
                if "timeseries" not in info["options"]: raise RuntimeError(f"{name} exists but is not time-series")
                if info["options"].get("expireAfterSeconds")!=ttl:
                    self.db.command({"collMod":name,"expireAfterSeconds":ttl})
            self.db[name].create_index([("meta.device_id",ASCENDING),("ts",ASCENDING)])
            self.db[name].create_index("batch_id")
        self.db.raw_inbox.create_index("expires_at",expireAfterSeconds=0)
        self.db.raw_inbox.create_index([("projected",1),("ts",1)])
        self.db.quarantine.create_index("expires_at",expireAfterSeconds=0)
        self.db.processed_registry.create_index("expires_at",expireAfterSeconds=0)

    def save_raw(self,record):
        document={**record,"expires_at":record["ts"]+timedelta(days=config.RETENTION_DAYS),"projected":False}
        collection=self.db.get_collection("raw_inbox",write_concern=WriteConcern(w=1,j=True))
        try:
            collection.insert_one(document)
            fresh=True
        except DuplicateKeyError:
            existing=collection.find_one({"_id":record["_id"]},{"digest":1})
            if not existing or existing["digest"]!=record["digest"]:
                raise ConflictError("same device/session/batch with different contents")
            fresh=False
        return fresh

    def project_pending(self,limit=100):
        # Run ONE collector instance. Raw inbox is durable source of truth.
        # A crash may replay a TS insert: every reader deduplicates by batch_id.
        n=0
        for row in self.db.raw_inbox.find({"projected":False}).sort("ts",1).limit(limit):
            if not self.db.raw_timeseries.find_one({"batch_id":row["_id"]},{"_id":1}):
                doc={k:v for k,v in row.items() if k not in ("_id","projected","expires_at")}
                doc["batch_id"]=row["_id"]
                self.db.raw_timeseries.insert_one(doc)
            self.db.raw_inbox.update_one({"_id":row["_id"]},{"$set":{"projected":True}})
            n+=1
        return n

    def quarantine(self,topic,reason,payload):
        now=datetime.now(timezone.utc)
        # Do not store arbitrary payload secrets; only a bounded structural failure report.
        self.db.quarantine.insert_one({"ts":now,"topic":topic,"reason":str(reason)[:300],
                                       "bytes":len(payload),"expires_at":now+timedelta(days=7)})

    def devices(self):
        return sorted(self.db.raw_timeseries.distinct("meta.device_id"))

    def sessions(self,device,hours=24):
        since=datetime.now(timezone.utc)-timedelta(hours=hours)
        return list(self.db.raw_timeseries.aggregate([
            {"$match":{"meta.device_id":device,"ts":{"$gte":since}}},
            {"$group":{"_id":"$batch_id","r":{"$first":"$$ROOT"}}},
            {"$replaceRoot":{"newRoot":"$r"}},
            {"$group":{"_id":"$session_id","ts":{"$max":"$ts"},"packets":{"$sum":1}}},
            {"$sort":{"ts":-1}},{"$limit":100}]))

    def packets(self,device,session,processed=False):
        name="processed_timeseries" if processed else "raw_timeseries"
        return list(self.db[name].aggregate([
            {"$match":{"meta.device_id":device,"session_id":session}},
            {"$sort":{"ts":-1}},
            {"$group":{"_id":"$batch_id","r":{"$first":"$$ROOT"}}},
            {"$replaceRoot":{"newRoot":"$r"}},
            {"$sort":{"data.sample_start_index":1}},{"$limit":200}]))
