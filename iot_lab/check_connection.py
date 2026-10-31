"""Check MongoDB without printing credentials."""
import argparse
import sys
from pymongo.errors import ConfigurationError, OperationFailure, ServerSelectionTimeoutError, PyMongoError
from storage import MongoStore


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--init",action="store_true",help="Create collections and indexes after successful ping")
    args=parser.parse_args()
    try:
        store=MongoStore();store.ping()
        print("OK: MongoDB connected. Database:",store.db.name)
        if args.init:
            store.setup();print("OK: time-series collections and indexes ready")
        return 0
    except ValueError:
        print("Missing/placeholder MONGO_URI. Edit iot_lab/.env locally.")
    except ConfigurationError:
        print("Invalid MONGO_URI. For local MongoDB use mongodb://127.0.0.1:27017.")
    except OperationFailure:
        print("Database authentication/permission error. Check DATABASE USER and access to signal_lab.")
    except ServerSelectionTimeoutError:
        print("Cannot reach MongoDB. Check that the MongoDB Windows service is running and MONGO_URI is correct.")
    except PyMongoError:
        print("MongoDB error. Check the MongoDB service and database user settings.")
    return 1


if __name__=="__main__":sys.exit(main())
