from collections import defaultdict
import pandas as pd


def wins_above_replacement(events: list[dict]) -> pd.DataFrame:
    """
    Per (card, character, act):
        picks            = times the card was chosen
        wins             = of those picks, runs that were won
        win_rate         = wins / picks
        baseline_wr      = character-level run win rate (avg over all runs)
        expected_wins    = picks * baseline_wr
        war              = wins - expected_wins
    """
    runs_per_char: dict[str, dict] = defaultdict(lambda: {"won": set(), "all": set()})
    for e in events:
        runs_per_char[e["character"]]["all"].add(e["run_id"])
        if e["run_won"]:
            runs_per_char[e["character"]]["won"].add(e["run_id"])

    baseline = {
        char: (len(s["won"]) / len(s["all"]) if s["all"] else 0.0)
        for char, s in runs_per_char.items()
    }

    counts: dict[tuple, dict] = defaultdict(lambda: {"picks": 0, "wins": 0})
    for e in events:
        if e["chosen"] is None:
            continue
        key = (e["chosen"], e["character"], e["act"])
        counts[key]["picks"] += 1
        if e["run_won"]:
            counts[key]["wins"] += 1

    rows = []
    for (card, character, act), s in counts.items():
        bl = baseline.get(character, 0.0)
        expected = s["picks"] * bl
        war = s["wins"] - expected
        rows.append({
            "card": card,
            "character": character,
            "act": act,
            "picks": s["picks"],
            "wins": s["wins"],
            "win_rate": round(s["wins"] / s["picks"] * 100, 1) if s["picks"] else 0.0,
            "baseline_wr": round(bl * 100, 1),
            "war": round(war, 2),
        })
    return pd.DataFrame(rows)
