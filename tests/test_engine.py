"""Vérifications du contrat public du moteur, horloge injectée en secondes."""
import json
import unittest
from pathlib import Path

import engine


class GameTests(unittest.TestCase):
    def setUp(self):
        self.now = 100_000
        self.room = engine.new("Lou", self.now)
        engine.join(self.room, "Noa", self.now)

    def state(self, seat=0):
        return engine.view(self.room, seat, self.now)

    def act(self, action, seat=0, **fields):
        body = {"action": action, "turn": self.state(seat)["turn"], **fields}
        engine.act(self.room, seat, body, self.now)

    def configure(self, **options):
        self.act("settings", settings={**self.state()["settings"], "rounds": 1, **options})

    def start(self, **options):
        self.configure(**options)
        self.act("start")

    def pair(self, left, right):
        self.act("answer", choice=left)
        self.act("answer", 1, choice=right)

    def finish_reveal(self):
        self.act("next")
        self.act("next", 1)

    def test_mirror_private_until_both_predictions(self):
        self.start()
        card = self.state()["card"]
        self.assertEqual(card, self.state(1)["card"])
        self.assertEqual(self.state()["phase"], "self")
        self.pair(0, 1)
        self.assertEqual(self.state()["phase"], "predict")
        self.act("answer", choice=1)
        for seat in (0, 1):
            view = self.state(seat)
            self.assertEqual(view["history"], [])
            self.assertEqual(view["scores"], [0, 0])
            self.assertTrue({"answers", "predictions"}.isdisjoint(view))
        self.act("answer", 1, choice=0)
        result = self.state()
        self.assertEqual(result["phase"], "reveal")
        self.assertEqual(result["history"][-1]["points"], [2, 2])
        self.assertEqual(result["scores"], [2, 2])
        self.assertEqual(result["stats"][0]["rate"], 100)
        self.assertEqual(result["history"], self.state(1)["history"])

    def test_secret_choice_changes_do_not_change_partner_view(self):
        # Une comparaison structurelle complète détecte les fuites même imbriquées.
        self.start()
        other = json.loads(json.dumps(self.room))
        for room, choice in [(self.room, 0), (other, 2)]:
            engine.act(room, 0, {"action": "answer", "turn": self.state()["turn"], "choice": choice}, self.now)
        self.assertEqual(self.state(1), engine.view(other, 1, self.now))

    def test_reverse_unequal_scores(self):
        self.start(mode="dans_ta_tete")
        self.assertEqual(self.state()["phase"], "predict")
        self.pair(1, 2)
        self.assertEqual(self.state()["phase"], "self")
        self.pair(0, 1)
        view = self.state()
        self.assertEqual(view["scores"], [2, 0])
        self.assertEqual(view["history"][0]["answers"], [0, 1])
        self.assertEqual(view["history"][0]["predictions"], [1, 2])

    def test_skip_does_not_count_as_missed_prediction(self):
        self.start()
        self.pair(None, 2)
        self.pair(2, 0)
        self.assertEqual(self.state()["scores"], [2, 0])
        self.assertEqual(self.state()["stats"][1]["attempts"], 0)
        self.assertIsNone(self.state()["history"][0]["answers"][0])

    def test_expiration_is_server_authoritative(self):
        self.start(duration=10)
        self.act("answer", choice=2)
        self.now = self.state()["deadline"] + .05
        engine.tick(self.room, self.now)
        self.assertEqual(self.state()["phase"], "predict")
        self.now = self.state()["deadline"] + .05
        engine.tick(self.room, self.now)
        self.assertEqual(self.state()["scores"], [0, 0])
        self.assertEqual(self.state()["history"][0]["answers"], [2, None])
        self.assertEqual(self.state()["history"][0]["predictions"], [None, None])
        self.assertEqual(self.state()["phase"], "reveal")

    def test_duplicate_and_delayed_move_cannot_change_outcome(self):
        self.start()
        stale = {"action": "answer", "turn": self.state()["turn"], "choice": 1}
        self.act("answer", choice=0)
        try:
            self.act("answer", choice=2)
        except ValueError:
            pass
        self.act("answer", 1, choice=1)
        try:
            engine.act(self.room, 0, stale, self.now)
        except ValueError:
            pass
        self.assertFalse(self.state()["locked"][0])
        self.pair(1, 0)
        self.assertEqual(self.state()["scores"], [2, 2])
        self.assertEqual(self.state()["history"][0]["answers"], [0, 1])

    def test_adult_requires_both_players(self):
        self.act("adult", value=True)
        try:
            self.configure(categories=["sans_filtre"])
            self.act("start")
        except ValueError:
            pass
        self.assertEqual(self.state()["phase"], "lobby")
        self.act("adult", 1, value=True)
        self.start(categories=["sans_filtre"])
        self.assertTrue(self.state()["card"]["adult"])

    def test_challenge_requires_agreement_and_can_be_declined(self):
        self.start(challenges=True, rounds=2)
        self.pair(0, 1)
        self.pair(1, 0)
        self.finish_reveal()
        self.assertEqual(self.state()["phase"], "challenge")
        self.act("level", value="leger")
        self.act("level", 1, value="intense")
        self.assertFalse(self.state()["challenge"]["text"])
        self.act("level", 1, value="leger")
        self.assertTrue(self.state()["challenge"]["text"])
        self.act("decline", 1)
        self.assertEqual(self.state()["scores"], [2, 2])
        self.assertEqual(self.state()["round"], 2)

    def test_replace_draws_another_challenge_without_score_change(self):
        self.start(challenges=True)
        self.pair(0, 1)
        self.pair(1, 0)
        self.finish_reveal()
        self.act("level", value="audacieux")
        self.act("level", 1, value="audacieux")
        old_text = self.state()["challenge"]["text"]
        self.act("replace", 1)
        self.assertNotEqual(self.state()["challenge"]["text"], old_text)
        self.assertEqual(self.state()["scores"], [2, 2])

    def test_invalid_input_and_guest_settings(self):
        baseline = self.state()["settings"]
        for invalid in (9, 91, True, "45"):
            with self.assertRaises(ValueError):
                self.configure(duration=invalid)
        with self.assertRaises(ValueError):
            self.act("settings", 1, settings={**baseline, "rounds": 20})
        self.assertEqual(self.state()["settings"], baseline)

    def test_no_restart_of_timers_after_long_disconnect(self):
        self.start(duration=10, rounds=3)
        self.now += 1000
        engine.tick(self.room, self.now)
        final = self.state()
        self.assertEqual(final["phase"], "final")
        self.assertEqual(final["scores"], [0, 0])
        self.assertEqual([x["round"] for x in final["history"]], [1, 2, 3])

    def test_interround_bonus_activation(self):
        self.start()
        self.pair(0, 1)
        self.pair(1, 0)
        self.act("bonus", value=True)
        self.finish_reveal()
        self.assertEqual(self.state()["phase"], "challenge")
        self.act("decline")
        self.assertEqual(self.state()["phase"], "final")

    def test_replay_requires_two_and_clears_scores(self):
        self.start()
        self.pair(0, 1)
        self.pair(1, 0)
        self.finish_reveal()
        self.assertEqual(self.state()["phase"], "final")
        self.act("replay", 1)
        self.assertEqual(self.state()["phase"], "final")
        self.act("replay")
        self.assertEqual(self.state()["phase"], "lobby")
        self.assertEqual(self.state()["history"], [])
        self.assertEqual(self.state()["scores"], [0, 0])


class ContentTests(unittest.TestCase):
    def test_catalog(self):
        from collections import Counter
        data = Path(__file__).resolve().parents[1] / "data"
        cards = json.loads((data / "cards.json").read_text())
        challenges = json.loads((data / "challenges.json").read_text())
        self.assertEqual(Counter(c["category"] for c in cards), dict.fromkeys(
            ["decouverte", "profondeur", "seduction", "sans_filtre"], 60))
        self.assertEqual(Counter(c["level"] for c in challenges),
                         dict.fromkeys(["leger", "audacieux", "intense"], 30))
        for items, key in [(cards, "id"), (cards, "question"), (challenges, "id"), (challenges, "text")]:
            self.assertEqual(len(items), len({i[key].strip().casefold() for i in items}))
        for c in cards:
            self.assertIn(c["intensity"], (1, 2, 3))
            self.assertTrue(c["allowSkip"])
            self.assertEqual(c["adult"], c["category"] == "sans_filtre")
            self.assertTrue(3 <= len(c["choices"]) <= 5)
            self.assertEqual(len(c["choices"]), len(set(c["choices"])))
            self.assertEqual(set(c["compatibility"]["modes"]), {"miroir", "dans_ta_tete"})

if __name__ == "__main__":
    unittest.main()
