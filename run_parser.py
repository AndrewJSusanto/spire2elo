import json
from pathlib import Path
from typing import Iterator

HISTORY_DIR = Path(
    "/Users/andrewsusanto/Library/Application Support/SlayTheSpire2"
    "/steam/76561198045292273/profile1/saves/history"
)

SKIP_ID = "SKIP"


def _fmt_character(raw: str) -> str:
    return raw.removeprefix("CHARACTER.").title()


def _fmt_card(raw: str) -> str:
    return raw.removeprefix("CARD.").replace("_", " ")


def _act_label(act_index: int) -> str:
    return f"Act {act_index + 1}"


def iter_choice_events(path: Path) -> Iterator[dict]:
    """
    Yield one dict per card choice event from a single .run file.
    Shop events are excluded. Each dict has:
        run_id      : str   (filename stem / start_time)
        character   : str
        ascension   : int
        act         : str   ("Act 1" / "Act 2" / "Act 3")
        floor       : int | None
        room_type   : str
        run_won     : bool
        offered     : list[str]   (card IDs, SKIP not included here)
        chosen      : str | None  (card ID, or None if all skipped)
    """
    with open(path) as f:
        data = json.load(f)

    character = _fmt_character(data["players"][0]["character"])
    ascension = data.get("ascension", 0)
    run_won = data.get("win", False)
    run_id = path.stem

    raw_acts = data.get("acts", [])
    act1_variant = raw_acts[0].removeprefix("ACT.").title() if raw_acts else None

    for act_index, act_points in enumerate(data.get("map_point_history", [])):
        act = _act_label(act_index)

        for point in act_points:
            room_type = point.get("rooms", [{}])[0].get("room_type", "unknown")

            # Exclude shop nodes entirely
            if room_type == "shop":
                continue

            for player in point.get("player_stats", []):
                choices = player.get("card_choices", [])
                if not choices:
                    continue

                offered = [_fmt_card(c["card"]["id"]) for c in choices]
                picked = next(
                    (_fmt_card(c["card"]["id"]) for c in choices if c["was_picked"]),
                    None,
                )
                floor = next(
                    (c["card"].get("floor_added_to_deck") for c in choices if c["was_picked"]),
                    None,
                )

                yield {
                    "run_id": run_id,
                    "character": character,
                    "ascension": ascension,
                    "act": act,
                    "act1_variant": act1_variant if act_index == 0 else None,
                    "floor": floor,
                    "room_type": room_type,
                    "run_won": run_won,
                    "offered": offered,
                    "chosen": picked,
                }


def load_all_events(history_dir: Path = HISTORY_DIR) -> list[dict]:
    events = []
    for path in sorted(history_dir.glob("*.run")):
        try:
            events.extend(iter_choice_events(path))
        except Exception:
            pass
    return events
