from collections import defaultdict
import pandas as pd

INITIAL_RATING = 1000
K = 32


def skip_id(character: str, act: str) -> str:
    char = character.upper().replace(" ", "_")
    act_num = act.split()[-1]
    return f"{char}_SKIP_ACT{act_num}"


def _elo_key(card: str, character: str, act: str) -> tuple:
    return (card, character, act)


def _expected(rating_a: float, rating_b: float) -> float:
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400))


def _update(rating_a: float, rating_b: float, a_won: bool):
    score_a = 1.0 if a_won else 0.0
    exp_a = _expected(rating_a, rating_b)
    new_a = rating_a + K * (score_a - exp_a)
    new_b = rating_b + K * ((1 - score_a) - (1 - exp_a))
    return new_a, new_b


def compute_ratings(events: list[dict]) -> dict[tuple, float]:
    """
    Process all choice events and return a dict of
    (card_id, character, act) -> elo_rating.

    Rules:
    - chosen card beats each other offered card (pairwise)
    - if all skipped, SKIP beats each offered card
    """
    ratings: dict[tuple, float] = defaultdict(lambda: INITIAL_RATING)

    for event in events:
        character = event["character"]
        act = event["act"]
        offered = event["offered"]
        chosen = event["chosen"]

        if chosen is not None:
            # Chosen beats every other card in the offer
            winner_key = _elo_key(chosen, character, act)
            for card in offered:
                if card == chosen:
                    continue
                loser_key = _elo_key(card, character, act)
                new_w, new_l = _update(ratings[winner_key], ratings[loser_key], a_won=True)
                ratings[winner_key] = new_w
                ratings[loser_key] = new_l
        else:
            # All skipped — SKIP beats every offered card
            skip_key = _elo_key(skip_id(character, act), character, act)
            for card in offered:
                card_key = _elo_key(card, character, act)
                new_skip, new_card = _update(ratings[skip_key], ratings[card_key], a_won=True)
                ratings[skip_key] = new_skip
                ratings[card_key] = new_card

    return dict(ratings)


def ratings_to_df(ratings: dict[tuple, float]) -> pd.DataFrame:
    rows = [
        {"card": card, "character": character, "act": act, "elo": round(rating, 1)}
        for (card, character, act), rating in ratings.items()
    ]
    df = pd.DataFrame(rows)
    return df.sort_values(["character", "act", "elo"], ascending=[True, True, False]).reset_index(drop=True)


def compute_ratings_history(events: list[dict]) -> pd.DataFrame:
    """
    Returns a DataFrame with columns: run_index, run_id, card, character, act, elo.
    One row per (card, character, act) per run, snapshotting ELO after each run completes.
    """
    from itertools import groupby

    ratings: dict[tuple, float] = defaultdict(lambda: INITIAL_RATING)
    rows = []
    run_index = 0

    for run_id, run_events in groupby(events, key=lambda e: e["run_id"]):
        run_index += 1
        touched: set[tuple] = set()

        for event in run_events:
            character = event["character"]
            act = event["act"]
            offered = event["offered"]
            chosen = event["chosen"]

            if chosen is not None:
                winner_key = _elo_key(chosen, character, act)
                for card in offered:
                    if card == chosen:
                        continue
                    loser_key = _elo_key(card, character, act)
                    new_w, new_l = _update(ratings[winner_key], ratings[loser_key], a_won=True)
                    ratings[winner_key] = new_w
                    ratings[loser_key] = new_l
                    touched.add(winner_key)
                    touched.add(loser_key)
            else:
                sk = _elo_key(skip_id(character, act), character, act)
                for card in offered:
                    card_key = _elo_key(card, character, act)
                    new_skip, new_card = _update(ratings[sk], ratings[card_key], a_won=True)
                    ratings[sk] = new_skip
                    ratings[card_key] = new_card
                    touched.add(sk)
                    touched.add(card_key)

        for key in touched:
            card, character, act = key
            rows.append({
                "run_index": run_index,
                "run_id": run_id,
                "card": card,
                "character": character,
                "act": act,
                "elo": round(ratings[key], 1),
            })

    return pd.DataFrame(rows)


def match_counts(events: list[dict]) -> pd.DataFrame:
    """Return (card, character, act) with times offered and times picked."""
    counts: dict[tuple, dict] = defaultdict(lambda: {"offered": 0, "picked": 0})
    for event in events:
        character = event["character"]
        act = event["act"]
        chosen = event["chosen"]
        for card in event["offered"]:
            key = _elo_key(card, character, act)
            counts[key]["offered"] += 1
            if card == chosen:
                counts[key]["picked"] += 1

    rows = [
        {
            "card": k[0],
            "character": k[1],
            "act": k[2],
            "times_offered": v["offered"],
            "times_picked": v["picked"],
            "pick_rate": round(v["picked"] / v["offered"] * 100, 1) if v["offered"] else 0.0,
        }
        for k, v in counts.items()
    ]
    return pd.DataFrame(rows)
