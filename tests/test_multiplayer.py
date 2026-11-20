"""Parcours HTTP réel avec deux sessions privées et des requêtes concurrentes."""
import http.cookiejar
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor


class Client:
    def __init__(self, origin):
        self.origin = origin
        self.jar = http.cookiejar.CookieJar()
        self.http = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def request(self, endpoint, body=None):
        request = urllib.request.Request(self.origin + "/api/" + endpoint,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Origin": self.origin, "Content-Type": "application/json"})
        with self.http.open(request, timeout=5) as response:
            return json.load(response)

    def state(self):
        return self.request("state")

    def act(self, action, turn, **fields):
        return self.request("act", {"action": action, "turn": turn, **fields})


class TwoClients(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        cls.origin = f"http://127.0.0.1:{port}"
        env = {**os.environ, "HOST": "127.0.0.1", "PORT": str(port),
               "DB_PATH": str(Path(cls.tmp.name) / "test.sqlite"),
               "PUBLIC_ORIGIN": cls.origin}
        cls.proc = subprocess.Popen([sys.executable, "server.py"], env=env,
                                    cwd=Path(__file__).resolve().parents[1])
        cls.addClassCleanup(cls.stop_server)
        for _ in range(100):
            if cls.proc.poll() is not None:
                raise RuntimeError("Le serveur de test s’est arrêté.")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=.15):
                    return
            except OSError:
                time.sleep(.05)
        raise RuntimeError("Le serveur de test ne répond pas.")

    @classmethod
    def stop_server(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=5)

    def setUp(self):
        self.a, self.b = Client(self.origin), Client(self.origin)
        self.code = self.a.request("create", {"name": "Lou"})["code"]
        self.b.request("join", {"name": "Noa", "code": self.code})

    def concurrent(self, fn):
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(fn, [self.a, self.b], [0, 1]))

    def test_http_simultaneous_opposites_and_reconnect(self):
        a, b = self.a, self.b
        start = a.act("start", a.state()["turn"])
        self.assertEqual(start["card"], b.state()["card"])
        self.concurrent(lambda client, seat: client.act("answer", start["turn"], choice=seat))
        pending = b.state()
        self.assertEqual(pending["phase"], "predict")
        self.assertEqual(pending["deadline"], a.state()["deadline"])
        self.assertEqual(pending["history"], [])
        self.concurrent(lambda client, seat: client.act("answer", pending["turn"], choice=1-seat))
        self.assertEqual(a.state()["scores"], [2, 2])
        # Relance d’un client à partir du cookie de la session originale.
        resumed = Client(self.origin)
        for cookie in b.jar:
            resumed.jar.set_cookie(cookie)
        self.assertEqual(resumed.state()["history"], a.state()["history"])
        self.assertEqual(resumed.state()["seat"], 1)
        with self.assertRaises(urllib.error.HTTPError):
            resumed.act("answer", start["turn"], choice=0)
        self.assertEqual(resumed.state()["scores"], [2, 2])

    def test_reconnect_after_elapsed_deadline(self):
        a, b = self.a, self.b
        lobby = a.state()
        settings = {**lobby["settings"], "duration": 10, "rounds": 1}
        a.act("settings", lobby["turn"], settings=settings)
        start = a.act("start", a.state()["turn"])
        a.act("answer", start["turn"], choice=2)
        # Les deux clients ferment la connexion pendant plus d’une phase entière.
        time.sleep(10.1)
        state = b.state()
        self.assertEqual(state["phase"], "predict")
        self.assertEqual(state["deadline"], start["deadline"] + 10)
        self.assertFalse(state["history"])
        self.concurrent(lambda c, i: c.act("answer", state["turn"], choice=2))
        reveal = a.state()
        self.assertEqual(reveal["history"][0]["answers"], [2, None])
        self.assertEqual(reveal["scores"], [0, 2])

    def test_http_second_mode_and_refused_challenge(self):
        a, b = self.a, self.b
        lobby = a.state()
        settings = {**lobby["settings"], "mode": "dans_ta_tete", "rounds": 1, "challenges": True}
        a.act("settings", lobby["turn"], settings=settings)
        start = a.act("start", a.state()["turn"])
        self.assertEqual(start["phase"], "predict")
        self.concurrent(lambda c, i: c.act("answer", start["turn"], choice=1-i))
        second = a.state()
        self.assertEqual(second["phase"], "self")
        self.concurrent(lambda c, i: c.act("answer", second["turn"], choice=None if i else 0))
        reveal = a.state()
        self.assertEqual(reveal["scores"], [0, 2])
        self.concurrent(lambda c, i: c.act("next", reveal["turn"]))
        challenge = b.state()
        self.assertEqual(challenge["phase"], "challenge")
        final = b.act("decline", challenge["turn"])
        self.assertEqual(final["phase"], "final")
        self.assertEqual(final["scores"], [0, 2])
        self.concurrent(lambda c, i: c.act("replay", final["turn"]))
        self.assertEqual(a.state()["phase"], "lobby")
        self.assertEqual(b.state()["scores"], [0, 0])
