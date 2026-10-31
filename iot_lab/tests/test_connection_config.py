import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import storage


class ConnectionConfigTests(unittest.TestCase):
    def test_empty_explicit_uri_is_rejected(self):
        with patch.object(storage.config,"MONGO_URI",""):
            with self.assertRaises(ValueError):storage.MongoStore()

    def test_template_is_not_used_as_real_connection(self):
        with self.assertRaises(ValueError):
            storage.MongoStore("mongodb://DB_USER:password@YOUR_CLUSTER/")

    def test_local_uri_is_passed_to_driver(self):
        uri="mongodb://127.0.0.1:27017"
        with patch.object(storage,"MongoClient") as client:
            storage.MongoStore(uri,"signal_lab_test")
            self.assertEqual(client.call_args.args[0],uri)
            self.assertNotIn("tlsAllowInvalidCertificates",client.call_args.kwargs)


if __name__=="__main__":unittest.main()
