"""Autorisations, purge en cascade et limites du serveur avec une base jetable."""
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import server


class Transport(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for key, value in (("DB", Path(tmp.name) / "test.db"), ("PG", False), ("RATE", {})):
            change = patch.object(server, key, value)
            change.start()
            self.addCleanup(change.stop)
        server.initialize()
        self.lobby, token = self.call("create", {"name": "Camille"})
        self.headers = {"cookie": server.COOKIE + "=" + token}

    def call(self, path, body=None, headers=None):
        return server.api(path, body or {}, headers or {}, "127.0.0.1")

    def test_code_cannot_read_state(self):
        with self.assertRaises(server.Problem) as ctx:
            self.call("state", headers={"cookie":server.COOKIE+"="+self.lobby["code"]})
        self.assertEqual(ctx.exception.status, 401)

    def test_atomic_second_seat(self):
        def join(name):
            try:
                view, _ = self.call("join", {"name":name, "code":self.lobby["code"]})
                return view["seat"]
            except server.Problem as err:
                return err.status
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(pool.map(join, ["Lou", "Noa"]), [1, 409])

    def test_rate_limit(self):
        for _ in range(15):
            with self.assertRaises(server.Problem) as failure:
                self.call("join", {"name":"Lou", "code":"AAAAAAA"})
            self.assertEqual(failure.exception.status, 404)
        with self.assertRaises(server.Problem) as failure:
            self.call("join", {"name":"Lou", "code":self.lobby["code"]})
        self.assertEqual(failure.exception.status, 429)

    def test_expiry_and_physical_purge(self):
        for field, limit in (("created",server.MAX_AGE), ("touched",server.TTL)):
            with self.subTest(field=field):
                with closing(server.db()) as conn, conn:
                    conn.execute(f"UPDATE rooms SET {field}={field}-?", (limit+1,))
                with self.assertRaises(server.Problem) as failure:
                    self.call("state", headers=self.headers)
                self.assertEqual(failure.exception.status,401)
                with closing(server.db()) as conn, conn:
                    server.expire(conn,server.time.time())
                    self.assertEqual(conn.execute("SELECT COUNT(*) FROM seats").fetchone()[0],0)
                    self.assertEqual(conn.execute("SELECT COUNT(*) FROM rooms").fetchone()[0],0)
                _, token=self.call("create", {"name":"Lou"})
                self.headers={"cookie": server.COOKIE+"="+token}

    def test_forged_scores_never_persist(self):
        with self.assertRaises(ValueError):
            self.call("act", {"action":"adult","turn":1,"value":True,"scores":[999,999]}, self.headers)
        self.assertEqual(self.call("state",headers=self.headers)[0]["scores"], [0,0])
