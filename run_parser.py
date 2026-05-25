import io
import json
import zipfile
from pathlib import Path
from typing import Iterator, Optional

HISTORY_DIR = Path(
    "/Users/andrewsusanto/Library/Application Support/SlayTheSpire2"
    "/steam/76561198045292273/profile1/saves/history"
)


def _fmt_character(raw: str) -> str:
    return raw.removeprefix("CHARACTER.").title()


def _fmt_card(raw: str, upgraded: bool = False) -> str:
    name = raw.removeprefix("CARD.").replace("_", " ")
    return f"{name}+" if upgraded else name


def _card_label(card: dict) -> str:
    return _fmt_card(card["id"], upgraded=card.get("current_upgrade_level", 0) >= 1)


def _act_label(act_index: int) -> str:
    return f"Act {act_index + 1}"


def iter_choice_events_from_data(data: dict, run_id: str) -> Iterator[dict]:
    """Same as iter_choice_events but takes parsed JSON + run_id directly (no disk read)."""
    character = _fmt_character(data["players"][0]["character"])
    ascension = data.get("ascension", 0)
    run_won = data.get("win", False)

    raw_acts = data.get("acts", [])
    act1_variant = raw_acts[0].removeprefix("ACT.").title() if raw_acts else None

    final_floor = sum(len(act_points) for act_points in data.get("map_point_history", []))
    final_deck_size = len(data["players"][0].get("deck", []))

    for act_index, act_points in enumerate(data.get("map_point_history", [])):
        act = _act_label(act_index)
        for point in act_points:
            room_type = point.get("rooms", [{}])[0].get("room_type", "unknown")
            if room_type == "shop":
                continue
            for player in point.get("player_stats", []):
                choices = player.get("card_choices", [])
                if not choices:
                    continue
                offered = [_card_label(c["card"]) for c in choices]
                picked = next(
                    (_card_label(c["card"]) for c in choices if c["was_picked"]),
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
                    "final_floor": final_floor,
                    "final_deck_size": final_deck_size,
                    "room_type": room_type,
                    "run_won": run_won,
                    "offered": offered,
                    "chosen": picked,
                }


def iter_choice_events(path: Path) -> Iterator[dict]:
    """Yield one dict per card choice event from a single .run file on disk."""
    with open(path) as f:
        data = json.load(f)
    yield from iter_choice_events_from_data(data, path.stem)


def load_all_events(history_dir: Path = HISTORY_DIR) -> list[dict]:
    events = []
    for path in sorted(history_dir.glob("*.run")):
        try:
            events.extend(iter_choice_events(path))
        except Exception:
            pass
    return events


def load_run_detail_from_data(data: dict, run_id: str) -> dict:
    """Same as load_run_detail but takes parsed JSON + run_id directly (no disk read)."""
    acts: list[list[dict]] = []
    floor_counter = 0
    for act_idx, act_points in enumerate(data.get("map_point_history", [])):
        act_rows = []
        for pos, point in enumerate(act_points):
            floor_counter += 1
            rooms = point.get("rooms", [{}])
            room = rooms[0] if rooms else {}
            act_rows.append({
                "floor": floor_counter,
                "act_idx": act_idx,
                "position": pos,
                "map_point_type": point.get("map_point_type", "unknown"),
                "room_type": room.get("room_type", "unknown"),
                "raw_point": point,
            })
        acts.append(act_rows)
    return {
        "run_id": run_id,
        "character": _fmt_character(data["players"][0]["character"]),
        "ascension": data.get("ascension", 0),
        "win": data.get("win", False),
        "acts": acts,
        "deck": data["players"][0].get("deck", []),
    }


def load_run_detail(run_id: str, history_dir: Path = HISTORY_DIR) -> dict:
    """Returns per-point detail for a single run from disk."""
    path = history_dir / f"{run_id}.run"
    with open(path) as f:
        data = json.load(f)
    return load_run_detail_from_data(data, run_id)


def parse_uploaded_zip(zip_bytes: bytes) -> dict:
    """
    Walk a zip of the saves/ folder.
    Returns:
        {
            "runs_by_id": {run_id: raw_json_data_dict, ...},
            "progress":    parsed progress.save dict or None,
        }
    Looks for any *.run anywhere in the zip, plus a top-level/nested progress.save.
    """
    runs_by_id: dict = {}
    progress: Optional[dict] = None

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for name in zf.namelist():
            base = Path(name).name
            if base.endswith(".run"):
                try:
                    with zf.open(name) as f:
                        data = json.loads(f.read().decode("utf-8"))
                    run_id = Path(base).stem
                    runs_by_id[run_id] = data
                except Exception:
                    continue
            elif base == "progress.save":
                try:
                    with zf.open(name) as f:
                        progress = json.loads(f.read().decode("utf-8"))
                except Exception:
                    continue

    return {"runs_by_id": runs_by_id, "progress": progress}


def events_from_runs_by_id(runs_by_id: dict) -> list:
    """Flatten an uploaded runs_by_id dict into a list of choice events."""
    events = []
    for run_id, data in runs_by_id.items():
        try:
            events.extend(iter_choice_events_from_data(data, run_id))
        except Exception:
            pass
    return events
