"""Règles du jeu. Le stockage sérialise les appels concurrents par salon."""

from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path
import secrets
import unicodedata


DATA = Path(__file__).resolve().parent / "data"
CATEGORIES = ("decouverte", "profondeur", "seduction", "sans_filtre")
LEVELS = ("leger", "audacieux", "intense")
DEFAULTS = {
    "mode": "miroir",
    "categories": ["decouverte"],
    "duration": 30,
    "rounds": 6,
    "challenges": False,
}
REVEAL_SECONDS = 18
CHALLENGE_VOTE_SECONDS = 30
CHALLENGE_PLAY_SECONDS = 60
RANDOM = secrets.SystemRandom()


@lru_cache(maxsize=1)
def _cards():
    with (DATA / "cards.json").open(encoding="utf-8") as source:
        return {card["id"]: card for card in json.load(source)}


@lru_cache(maxsize=1)
def _challenges():
    with (DATA / "challenges.json").open(encoding="utf-8") as source:
        return json.load(source)


def _name(raw):
    if not isinstance(raw, str):
        raise ValueError("Pseudonyme invalide.")
    name = unicodedata.normalize("NFC", raw.strip())
    if not 1 <= len(name) <= 32 or any(unicodedata.category(c) in {"Cc", "Cs", "Cf"} for c in name):
        raise ValueError("Choisis un pseudonyme de 1 à 32 caractères.")
    return name


def _settings(raw):
    if not isinstance(raw, dict) or set(raw) != set(DEFAULTS):
        raise ValueError("Paramètres incomplets.")
    cats = raw["categories"]
    if not isinstance(cats, list) or not 1 <= len(cats) <= 4 or any(c not in CATEGORIES for c in cats) or len(set(cats)) != len(cats):
        raise ValueError("Sélection d’univers invalide.")
    if raw["mode"] not in ("miroir", "dans_ta_tete"):
        raise ValueError("Mode inconnu.")
    if type(raw["duration"]) is not int or not 10 <= raw["duration"] <= 90:
        raise ValueError("La durée doit être comprise entre 10 et 90 secondes.")
    if type(raw["rounds"]) is not int or not 1 <= raw["rounds"] <= 20 or type(raw["challenges"]) is not bool:
        raise ValueError("Réglages des manches invalides.")
    return deepcopy(raw)


def new(name, now):
    return {
        "players": [_name(name)], "phase": "lobby", "turn": 1, "round": 0,
        "settings": deepcopy(DEFAULTS), "adult": [False, False], "deadline": None,
        "deck": [], "history": [], "scores": [0, 0], "locked": [False, False],
        "answers": [None, None], "predictions": [None, None], "replay": [False, False],
        "levelVotes": [None, None], "challengeId": None, "seenChallenges": [],
    }


def join(room, name, now):
    if len(room["players"]) != 1 or room["phase"] != "lobby":
        raise ValueError("Ce salon est complet ou fermé.")
    room["players"].append(_name(name))


def _phase(room, phase, at, seconds=None):
    room["phase"] = phase
    room["turn"] += 1
    room["locked"] = [False, False]
    room["deadline"] = None if seconds is None else at + seconds


def _next_round(room, at):
    if room["round"] == len(room["deck"]):
        _phase(room, "final", at)
        return
    room["round"] += 1
    room["answers"] = [None, None]
    room["predictions"] = [None, None]
    _phase(room, "self" if room["settings"]["mode"] == "miroir" else "predict", at, room["settings"]["duration"])


def _card(room):
    return _cards()[room["deck"][room["round"] - 1]]


def _advance(room, at):
    phase = room["phase"]
    if phase in ("self", "predict"):
        first = "self" if room["settings"]["mode"] == "miroir" else "predict"
        if phase == first:
            _phase(room, "predict" if phase == "self" else "self", at, room["settings"]["duration"])
            return
        guesses, answers = room["predictions"], room["answers"]
        points = [2 if guesses[i] is not None and guesses[i] == answers[1-i] else 0 for i in range(2)]
        room["history"].append({
            "round": room["round"], "cardId": _card(room)["id"],
            "answers": answers[:], "predictions": guesses[:], "points": points,
        })
        room["scores"] = [old + inc for old, inc in zip(room["scores"], points)]
        _phase(room, "reveal", at, REVEAL_SECONDS)
    elif phase == "reveal" and room["settings"]["challenges"]:
        room["levelVotes"] = [None, None]
        room["challengeId"] = None
        _phase(room, "challenge", at, CHALLENGE_VOTE_SECONDS)
    elif phase in ("reveal", "challenge"):
        _next_round(room, at)


def tick(room, now):
    """Rattrape même plusieurs échéances, sans avantager un client lent."""
    while room["deadline"] is not None and room["deadline"] <= now:
        _advance(room, room["deadline"])


def _draw_challenge(room, level, now):
    pool = [c for c in _challenges() if c["level"] == level]
    fresh = [c for c in pool if c["id"] not in room["seenChallenges"]]
    if not fresh:
        ids = {c["id"] for c in pool}
        room["seenChallenges"] = [cid for cid in room["seenChallenges"] if cid not in ids]
        fresh = [c for c in pool if c["id"] != room["challengeId"]] or pool
    chosen = RANDOM.choice(fresh)["id"]
    room["challengeId"] = chosen
    room["seenChallenges"].append(chosen)
    _phase(room, "challenge", now, CHALLENGE_PLAY_SECONDS)


def _ready(room, seat, now):
    room["locked"][seat] = True
    if all(room["locked"]):
        _advance(room, now)


def act(room, seat, body, now):
    if type(seat) is not int or not 0 <= seat < len(room["players"]):
        raise ValueError("Accès refusé.")
    tick(room, now)
    if not isinstance(body, dict) or type(body.get("turn")) is not int or body["turn"] != room["turn"]:
        raise ValueError("La partie a avancé. Actualise ton écran.")
    action = body.get("action")
    allowed = {
        "settings": ("settings",), "adult": ("value",), "start": (), "answer": ("choice",),
        "bonus": ("value",), "next": (), "level": ("value",), "replace": (),
        "decline": (), "replay": (),
    }
    if not isinstance(action, str) or action not in allowed or set(body) != {"action", "turn", *allowed[action]}:
        raise ValueError("Commande invalide.")
    phase = room["phase"]
    if phase == "lobby" and action == "adult" and type(body["value"]) is bool:
        room["adult"][seat] = body["value"]
    elif phase == "lobby" and action == "settings" and seat == 0:
        room["settings"] = _settings(body["settings"])
        room["turn"] += 1
    elif phase == "lobby" and action == "start" and seat == 0:
        if len(room["players"]) != 2:
            raise ValueError("Il faut deux joueurs pour commencer.")
        settings = room["settings"]
        if "sans_filtre" in settings["categories"] and not all(room["adult"]):
            raise ValueError("Chaque joueur doit confirmer son accord pour Sans filtre.")
        pool = [card["id"] for card in _cards().values() if card["category"] in settings["categories"] and (not card["adult"] or all(room["adult"]))]
        if len(pool) < settings["rounds"]:
            raise ValueError("Nombre de cartes insuffisant pour ces réglages.")
        room["deck"] = RANDOM.sample(pool, settings["rounds"])
        _next_round(room, now)
    elif phase in ("self", "predict") and action == "answer":
        choice = body["choice"]
        if choice is not None and (type(choice) is not int or not 0 <= choice < len(_card(room)["choices"])):
            raise ValueError("Choix invalide.")
        field = "answers" if phase == "self" else "predictions"
        if room["locked"][seat] and room[field][seat] != choice:
            raise ValueError("Ce choix est déjà verrouillé.")
        room[field][seat] = choice
        _ready(room, seat, now)
    elif phase == "reveal" and action == "bonus" and seat == 0 and type(body["value"]) is bool:
        room["settings"]["challenges"] = body["value"]
    elif action == "next" and (phase == "reveal" or (phase == "challenge" and room["challengeId"] is not None)):
        _ready(room, seat, now)
    elif phase == "challenge" and action == "decline":
        _advance(room, now)
    elif phase == "challenge" and action == "level" and room["challengeId"] is None and body["value"] in LEVELS:
        room["levelVotes"][seat] = body["value"]
        if room["levelVotes"][0] == room["levelVotes"][1]:
            _draw_challenge(room, body["value"], now)
    elif phase == "challenge" and action == "replace" and room["challengeId"] is not None:
        _draw_challenge(room, room["levelVotes"][0], now)
    elif phase == "final" and action == "replay":
        room["replay"][seat] = True
        if all(room["replay"]):
            players = room["players"]
            upcoming_turn = room["turn"] + 1
            room.update(new(players[0], now))
            room.update(players=players, turn=upcoming_turn)
    else:
        raise ValueError("Cette action est indisponible.")


def view(room, seat, now):
    """Projection exhaustive. Le deck, les choix courants et les secrets restent côté serveur."""
    if type(seat) is not int or not 0 <= seat < len(room["players"]):
        raise ValueError("Accès refusé.")
    tick(room, now)
    visible = {k: deepcopy(room[k]) for k in (
        "players", "phase", "turn", "round", "settings", "adult", "deadline", "locked", "scores", "replay",
    )}
    history = []
    for item in room["history"]:
        entry = {k: deepcopy(item[k]) for k in ("round", "answers", "predictions", "points")}
        entry["card"] = deepcopy(_cards()[item["cardId"]])
        history.append(entry)
    attempts = [sum(item["predictions"][i] is not None and item["answers"][1-i] is not None for item in history) for i in range(2)]
    correct = [score // 2 for score in room["scores"]]
    gap = abs(room["scores"][0] - room["scores"][1])
    recommended = "leger" if max(room["scores"]) < 4 else ("intense" if gap <= 2 else "audacieux")
    text = None
    if room["phase"] == "challenge" and room["challengeId"] is not None:
        text = next(c["text"] for c in _challenges() if c["id"] == room["challengeId"])
    visible.update(
        seat=seat, serverNow=now,
        card=deepcopy(_card(room)) if room["phase"] in ("self", "predict", "reveal") else None,
        history=history,
        stats=[{"correct": correct[i], "attempts": attempts[i], "rate": round(100*correct[i]/attempts[i]) if attempts[i] else None} for i in range(2)],
        challenge={"recommended": recommended, "levelVotes": room["levelVotes"][:], "text": text},
    )
    return visible
