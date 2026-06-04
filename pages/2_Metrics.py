import json
import sys
from pathlib import Path
from typing import Optional

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))
import run_parser
from assets import character_icon_uri, relic_icon_uri
from save_panel import render_save_panel

st.set_page_config(page_title="Metrics — Spire2ELO", page_icon="📊", layout="wide")
render_save_panel()


CHARACTER_COLORS = {
    "Ironclad":    "#e05555",
    "Regent":      "#e07b30",
    "Necrobinder": "#b39ddb",
    "Silent":      "#4caf50",
    "Defect":      "#64b5f6",
}


# ── Shared data source helpers ────────────────────────────────────────────────
def _source_key() -> str:
    return st.session_state.get("uploaded_hash", "local")


@st.cache_data
def _get_runs_raw(source_key: str) -> dict:
    """Cached per `source_key` so disk-backed runs are parsed once per session."""
    runs = st.session_state.get("uploaded_runs_by_id")
    if runs:
        return runs
    out = {}
    for path in sorted(run_parser.HISTORY_DIR.glob("*.run")):
        try:
            with open(path) as f:
                out[path.stem] = json.load(f)
        except Exception:
            continue
    return out


def _get_progress_data() -> Optional[dict]:
    """progress.save — authoritative source for lifetime W/L (includes pre-`.run` history)."""
    if st.session_state.get("uploaded_progress"):
        return st.session_state["uploaded_progress"]
    try:
        with open(run_parser.HISTORY_DIR.parent / "progress.save") as f:
            return json.load(f)
    except Exception:
        return None


def _lifetime_wl(progress: Optional[dict], target_char: str) -> Optional[tuple]:
    """Returns (wins, losses) for target_char from progress.save, or None if unavailable."""
    if not progress:
        return None
    for cs in progress.get("character_stats", []):
        if cs.get("id") == target_char:
            return cs.get("total_wins", 0), cs.get("total_losses", 0)
    return None


# ── Encounter helpers ────────────────────────────────────────────────────────
POOL_FROM_SUFFIX = {
    "WEAK":   "Easy",
    "NORMAL": "Hard",
    "ELITE":  "Elite",
    "BOSS":   "Boss",
}
POOL_ORDER = ["Easy", "Hard", "Elite", "Boss"]
ANY_VARIANT = "_"  # bucket key for Act 2/3 (no variant)


def _parse_encounter_id(eid: str):
    short = eid.removeprefix("ENCOUNTER.")
    for suffix, pool in POOL_FROM_SUFFIX.items():
        if short.endswith(f"_{suffix}"):
            return short[:-(len(suffix) + 1)].replace("_", " ").title(), pool
    return short.replace("_", " ").title(), "Other"


@st.cache_data
def _encounter_stats_derived(source_key: str) -> dict:
    """
    Single comprehensive derivation from .run files.
    Returns: {
        encounter_id: {
            "act_idx": int,
            "variants": set[str],  # Act 1 variants this encounter has been seen in
            "per_char": {
                char_id: {
                    variant_key: {  # 'Overgrowth' / 'Underdocks' / ANY_VARIANT
                        "wins": int, "losses": int,
                        "dmg": int, "heal": int, "fights": int,
                    }
                }
            }
        }
    }
    """
    out: dict = {}
    for data in _get_runs_raw(source_key).values():
        char = data["players"][0]["character"]
        raw_acts = data.get("acts", [])
        variant = raw_acts[0].removeprefix("ACT.").title() if raw_acts else None
        for act_idx, act in enumerate(data.get("map_point_history", [])):
            v_key = variant if act_idx == 0 and variant else ANY_VARIANT
            for point in act:
                for room in point.get("rooms", []):
                    eid = room.get("model_id")
                    if not eid or not eid.startswith("ENCOUNTER."):
                        continue
                    info = out.setdefault(eid, {"act_idx": act_idx, "variants": set(), "per_char": {}})
                    if act_idx == 0 and variant:
                        info["variants"].add(variant)
                    for ps in point.get("player_stats", []):
                        char_buckets = info["per_char"].setdefault(char, {})
                        bucket = char_buckets.setdefault(v_key, {
                            "wins": 0, "losses": 0, "dmg": 0, "heal": 0, "fights": 0,
                        })
                        bucket["fights"] += 1
                        bucket["dmg"] += ps.get("damage_taken", 0)
                        bucket["heal"] += ps.get("hp_healed", 0)
                        if ps.get("current_hp", 1) > 0:
                            bucket["wins"] += 1
                        else:
                            bucket["losses"] += 1
    return out


def _delta_color(delta: float) -> str:
    """Chip color from avg HP delta per fight. Higher damage taken (more negative) leans red."""
    if delta >= -1:  return "#3e8e41"   # essentially no net damage
    if delta >= -3:  return "#7cb342"
    if delta >= -7:  return "#c0ca33"
    if delta >= -15: return "#ef6c00"
    return "#c62828"


def _render_pool_chips(encs: list):
    if not encs:
        st.caption("No data for this pool.")
        return
    chips = []
    for enc in sorted(encs, key=lambda e: e["avg_delta"]):  # most damaging first
        color = _delta_color(enc["avg_delta"])
        runs_ended = enc["losses"]
        tooltip = f"{runs_ended} runs ended · Δ {enc['avg_delta']:+.1f} average damage taken"
        chips.append(
            f'<span class="enc-chip" data-tooltip="{tooltip}" '
            f'style="background:{color}26; border-color:{color}; color:{color};">'
            f'{enc["name"]}</span>'
        )
    st.markdown("".join(chips), unsafe_allow_html=True)


def _collect_overview(stats: dict, target_char: str) -> list:
    """Per-encounter aggregate across all acts and variants for the target character."""
    out = []
    for eid, info in stats.items():
        char_buckets = info["per_char"].get(target_char)
        if not char_buckets:
            continue
        wins = sum(b["wins"] for b in char_buckets.values())
        losses = sum(b["losses"] for b in char_buckets.values())
        dmg = sum(b["dmg"] for b in char_buckets.values())
        heal = sum(b["heal"] for b in char_buckets.values())
        fights = sum(b["fights"] for b in char_buckets.values())
        if fights == 0:
            continue
        name, pool = _parse_encounter_id(eid)
        out.append({
            "name": name,
            "pool": pool,
            "act_idx": info["act_idx"],
            "variants": info.get("variants") or set(),
            "wins": wins, "losses": losses,
            "fights": fights,
            "avg_delta": (heal - dmg) / fights,
        })
    return out


def _render_overview_row(label: str, entries: list, value_fmt):
    if not entries:
        return
    st.markdown(f'<div class="pool-label">{label}</div>', unsafe_allow_html=True)
    chips = []
    for rank, enc in enumerate(entries, start=1):
        tooltip = f"{enc['losses']} runs ended · Δ {enc['avg_delta']:+.1f} average damage taken"
        act_label = f"Act {enc['act_idx'] + 1}"
        if enc["act_idx"] == 0 and enc.get("variants"):
            has_o = "Overgrowth" in enc["variants"]
            has_u = "Underdocks" in enc["variants"]
            if has_o and not has_u:
                act_label += " - O"
            elif has_u and not has_o:
                act_label += " - U"
            else:
                act_label += " - O/U"
        chips.append(
            f'<span class="enc-chip" data-tooltip="{tooltip}" '
            f'style="background:rgba(255,255,255,0.06); border-color:rgba(255,255,255,0.2); color:inherit; font-weight:600;">'
            f'#{rank} {enc["name"]} '
            f'<span style="opacity:0.55; font-weight:400; font-size:0.85em;">({act_label})</span>'
            f' · {value_fmt(enc)}</span>'
        )
    st.markdown("".join(chips), unsafe_allow_html=True)


# ── Ancient relic stats ───────────────────────────────────────────────────────
ANCIENT_ORDER = [
    ("EVENT.NEOW",      0),     # Act 1
    ("EVENT.OROBAS",    1),     # Act 2
    ("EVENT.PAEL",      1),
    ("EVENT.TEZCATARA", 1),
    ("EVENT.TANX",      2),     # Act 3
    ("EVENT.NONUPEIPE", 2),
    ("EVENT.VAKUU",     2),
    # Darv appears in either Act 2 or 3; split into per-act buckets at render time.
]


@st.cache_data
def _ancient_relic_stats(source_key: str, target_char: str) -> dict:
    """
    Per-ancient relic offering + pick + win stats for one character.

    Returns:
        {
            "ancients":    {ancient_id: bucket},                # aggregate across all runs
            "variants":    {(ancient_id, variant): bucket},     # Act-1 split (Overgrowth/Underdocks)
            "darv_by_act": {act_idx: bucket},                   # Darv split by which act it appeared in
            "total_runs":  int,
            "total_wins":  int,
        }
        bucket = {
            "encounters":     int,
            "encounter_wins": int,
            "options": {relic_id: {"offered": int, "picked": int, "wins_when_picked": int}},
        }
    """
    def _new_bucket():
        return {"encounters": 0, "encounter_wins": 0, "options": {}}

    def _tally_choice(bkt, relic_id, was_chosen, won):
        opt = bkt["options"].setdefault(relic_id, {
            "offered": 0, "picked": 0, "wins_when_picked": 0,
        })
        opt["offered"] += 1
        if was_chosen:
            opt["picked"] += 1
            if won:
                opt["wins_when_picked"] += 1

    ancients: dict = {}
    variants: dict = {}
    darv_by_act: dict = {}
    total_runs = 0
    total_wins = 0
    for data in _get_runs_raw(source_key).values():
        if data["players"][0]["character"] != target_char:
            continue
        won = data.get("win", False)
        total_runs += 1
        if won:
            total_wins += 1
        raw_acts = data.get("acts", [])
        act1_variant = raw_acts[0].removeprefix("ACT.").title() if raw_acts else None

        seen_id: set = set()
        seen_variant: set = set()
        for act_idx, act in enumerate(data.get("map_point_history", [])):
            for point in act:
                if point.get("map_point_type") != "ancient":
                    continue
                rooms = point.get("rooms", [])
                ancient_id = rooms[0].get("model_id") if rooms else None
                if not ancient_id:
                    continue
                bucket = ancients.setdefault(ancient_id, _new_bucket())
                vbucket = None
                if act_idx == 0 and act1_variant:
                    vbucket = variants.setdefault((ancient_id, act1_variant), _new_bucket())
                dbucket = None
                if ancient_id == "EVENT.DARV":
                    dbucket = darv_by_act.setdefault(act_idx, _new_bucket())

                if ancient_id not in seen_id:
                    bucket["encounters"] += 1
                    if won:
                        bucket["encounter_wins"] += 1
                    seen_id.add(ancient_id)
                if vbucket is not None and (ancient_id, act1_variant) not in seen_variant:
                    vbucket["encounters"] += 1
                    if won:
                        vbucket["encounter_wins"] += 1
                    seen_variant.add((ancient_id, act1_variant))
                if dbucket is not None:
                    dbucket["encounters"] += 1
                    if won:
                        dbucket["encounter_wins"] += 1

                for ps in point.get("player_stats", []):
                    for ac in ps.get("ancient_choice", []):
                        text_key = ac.get("TextKey")
                        if not text_key:
                            continue
                        relic_id = f"RELIC.{text_key}"
                        was_chosen = bool(ac.get("was_chosen"))
                        _tally_choice(bucket, relic_id, was_chosen, won)
                        if vbucket is not None:
                            _tally_choice(vbucket, relic_id, was_chosen, won)
                        if dbucket is not None:
                            _tally_choice(dbucket, relic_id, was_chosen, won)
    return {
        "ancients": ancients,
        "variants": variants,
        "darv_by_act": darv_by_act,
        "total_runs": total_runs,
        "total_wins": total_wins,
    }


def _wr_delta_color(delta: float) -> str:
    if delta >=  10: return "#4caf50"
    if delta >=   3: return "#7cb342"
    if delta >=  -3: return "#c0c4cc"
    if delta >= -10: return "#ef6c00"
    return "#c62828"


def _render_ancient_relics(target_char: str, selected_char: str, sort_by: str = "pickrate"):
    stats = _ancient_relic_stats(_source_key(), target_char)
    if stats["total_runs"] == 0:
        st.caption("No runs for this character.")
        return

    lifetime = _lifetime_wl(_get_progress_data(), target_char)
    if lifetime is not None:
        wins, losses = lifetime
        total = wins + losses
        baseline = (wins / total * 100) if total else 0
        st.caption(
            f"Character baseline: **{baseline:.1f}%** run win rate over "
            f"**{wins}W / {losses}L** (lifetime, from `progress.save`). "
            f"Per-relic stats below are based on **{stats['total_runs']}** runs "
            f"with detailed `.run` history."
        )
    else:
        baseline = (stats["total_wins"] / stats["total_runs"] * 100) if stats["total_runs"] else 0
        st.caption(
            f"Character baseline: **{baseline:.1f}%** run win rate over "
            f"{stats['total_wins']}W / {stats['total_runs'] - stats['total_wins']}L "
            "(from `.run` files; lifetime `progress.save` not available)."
        )

    st.markdown(
        """
        <style>
        .relic-row {
            display: flex; align-items: center; gap: 12px;
            padding: 6px 10px; margin: 3px 0;
            border-radius: 6px;
            background: rgba(255,255,255,0.03);
            border: 1px solid rgba(255,255,255,0.08);
            font-size: 0.88rem;
        }
        .relic-row-icon {
            width: 32px; height: 32px; flex-shrink: 0;
            display: flex; align-items: center; justify-content: center;
        }
        .relic-row-icon img {
            height: 30px; width: 30px; object-fit: contain; border-radius: 4px;
        }
        .relic-row-name { flex: 1; font-weight: 500; }
        .relic-row-stat { white-space: nowrap; opacity: 0.85; }
        .relic-row-stat small {
            opacity: 0.55; font-size: 0.78em; margin-right: 4px;
            text-transform: uppercase; letter-spacing: 0.05em;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    def _sort_key(kv):
        _, opt = kv
        picked, offered, wins = opt["picked"], opt["offered"], opt["wins_when_picked"]
        if sort_by == "winrate":
            # Never-picked sink to the bottom; ties broken by picks desc.
            wr = (wins / picked) if picked else -1
            return (-(wr >= 0), -wr, -picked)
        # pickrate (default)
        rate = (picked / offered) if offered else 0
        return (-rate, -picked)

    def _render_one(ancient_id: str, bucket: dict):
        enc = bucket["encounters"]
        enc_wins = bucket["encounter_wins"]
        reach_wr = (enc_wins / enc * 100) if enc else 0
        st.caption(
            f"Seen **{enc}×** · {enc_wins} / {enc} won "
            f"({reach_wr:.1f}% WR)"
        )
        options = sorted(bucket["options"].items(), key=_sort_key)
        rows = []
        for relic_id, opt in options:
            label = relic_id.removeprefix("RELIC.").replace("_", " ").title()
            uri = relic_icon_uri(relic_id, character=selected_char)
            picked = opt["picked"]
            offered = opt["offered"]
            wins = opt["wins_when_picked"]

            if picked > 0:
                wr = wins / picked * 100
                delta = wr - baseline
                color = _wr_delta_color(delta)
                sign = "+" if delta >= 0 else ""
                wr_chunk = (
                    f'<b>{wr:.1f}%</b> WR '
                    f'<span style="color:{color}; font-weight:600;">({sign}{delta:.1f})</span>'
                )
            else:
                wr_chunk = '<span style="opacity:0.45;">never picked</span>'

            img_html = f'<img src="{uri}" alt="">' if uri else ""
            rows.append(
                f'<div class="relic-row">'
                f'<div class="relic-row-icon">{img_html}</div>'
                f'<div class="relic-row-name">{label}</div>'
                f'<div class="relic-row-stat"><small>Picked</small>{picked}/{offered}</div>'
                f'<div class="relic-row-stat">{wr_chunk}</div>'
                f'</div>'
            )
        st.markdown("".join(rows), unsafe_allow_html=True)

    # Group present ancients by act. Each entry is (display_name, ancient_id, bucket).
    groups: dict = {}
    for ancient_id, act_idx in ANCIENT_ORDER:
        bucket = stats["ancients"].get(ancient_id)
        if not bucket or not bucket["options"]:
            continue
        display_name = ancient_id.removeprefix("EVENT.").title()
        groups.setdefault(act_idx, []).append((display_name, ancient_id, bucket))

    # Inject Darv as a per-act tab into the act it appeared in.
    for act_idx, dbucket in stats.get("darv_by_act", {}).items():
        if not dbucket["options"]:
            continue
        groups.setdefault(act_idx, []).append(
            (f"Darv (Act {act_idx + 1})", "EVENT.DARV", dbucket)
        )

    ACT_NAMES = {0: None, 1: "Hive", 2: "Glory"}

    def _group_label(key) -> str:
        suffix = ACT_NAMES.get(key)
        return f"Act {key + 1} - {suffix}" if suffix else f"Act {key + 1}"

    for act_key in sorted(groups.keys()):
        group = groups[act_key]
        with st.expander(_group_label(act_key), expanded=False):
            if act_key == 0:
                # Act 1: split Neow by Act 1 variant + an aggregate tab.
                _, ancient_id, bucket = group[0]
                variant_names = ["Aggregate", "Overgrowth", "Underdocks"]
                tabs = st.tabs(variant_names)
                for vname, tab in zip(variant_names, tabs):
                    with tab:
                        if vname == "Aggregate":
                            _render_one(ancient_id, bucket)
                            continue
                        vbucket = stats["variants"].get((ancient_id, vname))
                        if not vbucket or not vbucket["options"]:
                            st.caption(f"No {vname} runs for this character.")
                        else:
                            _render_one(ancient_id, vbucket)
            elif len(group) == 1:
                _, ancient_id, bucket = group[0]
                _render_one(ancient_id, bucket)
            else:
                tab_labels = [name for name, _, _ in group]
                tabs = st.tabs(tab_labels)
                for tab, (_, ancient_id, bucket) in zip(tabs, group):
                    with tab:
                        _render_one(ancient_id, bucket)


def _collect_for_act(stats: dict, target_char: str, act_idx: int, variant_key: str, hide_perfect: bool) -> dict:
    """Returns {pool: [encs]} for the selected character + act + variant."""
    grouped: dict = {p: [] for p in POOL_ORDER}
    for eid, info in stats.items():
        if info["act_idx"] != act_idx:
            continue
        if act_idx == 0 and variant_key not in (info.get("variants") or set()):
            continue
        char_buckets = info["per_char"].get(target_char)
        if not char_buckets:
            continue
        bucket = char_buckets.get(variant_key) or char_buckets.get(ANY_VARIANT)
        if not bucket or bucket["fights"] == 0:
            continue
        wins, losses, fights = bucket["wins"], bucket["losses"], bucket["fights"]
        wr = wins / (wins + losses) * 100 if (wins + losses) else 0
        if hide_perfect and wr >= 100:
            continue
        name, pool = _parse_encounter_id(eid)
        if pool not in grouped:
            grouped[pool] = []
        grouped[pool].append({
            "name": name,
            "wins": wins, "losses": losses,
            "wr": wr,
            "avg_delta": (bucket["heal"] - bucket["dmg"]) / fights,
        })
    return grouped


# ── Page ──────────────────────────────────────────────────────────────────────
header_slot = st.empty()

char_options = sorted(CHARACTER_COLORS.keys())
selected_char = st.segmented_control(
    "Character", char_options, default="Ironclad", key="metrics_char"
)
if selected_char is None:
    selected_char = "Ironclad"
target_char = f"CHARACTER.{selected_char.upper()}"

char_hex = CHARACTER_COLORS.get(selected_char, "inherit")
icon_uri = character_icon_uri(selected_char)
icon_html = (
    f'<img src="{icon_uri}" style="height:1.2em; vertical-align:-0.2em; margin:0 0.3em;" alt="">'
    if icon_uri else ""
)
header_slot.markdown(
    f'<h1>Metrics — <span style="color:{char_hex}">{selected_char}</span>{icon_html}</h1>',
    unsafe_allow_html=True,
)

tab_enc, tab_relic = st.tabs(["Encounters & Enemies", "Relics"])

with tab_enc:

    stats = _encounter_stats_derived(_source_key())

    st.markdown(
        """
        <style>
        .enc-chip {
            position: relative;
            display: inline-block;
            padding: 6px 12px;
            margin: 4px;
            border-radius: 6px;
            font-size: 0.88rem;
            border: 1px solid;
            cursor: default;
            font-weight: 500;
        }
        .enc-chip:hover::after {
            content: attr(data-tooltip);
            position: absolute;
            bottom: 110%;
            left: 50%;
            transform: translateX(-50%);
            background: #1e1e1e;
            color: white;
            padding: 6px 10px;
            border-radius: 4px;
            font-size: 0.78rem;
            white-space: nowrap;
            z-index: 100;
            border: 1px solid rgba(255,255,255,0.2);
            pointer-events: none;
        }
        .pool-label {
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            opacity: 0.6;
            margin-top: 8px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # ── Overview (non-act-filtered) ────────────────────────────────────────────
    overview = _collect_overview(stats, target_char)
    normal_pools = {"Easy", "Hard"}
    top_dmg = sorted(
        (e for e in overview if e["pool"] in normal_pools),
        key=lambda e: e["avg_delta"],
    )[:3]
    top_deadly = sorted(overview, key=lambda e: -e["losses"])[:3]
    _render_overview_row(
        "Highest damage delta (normal encounters)",
        top_dmg,
        lambda e: f"{e['avg_delta']:+.1f} avg damage taken",
    )
    _render_overview_row(
        "Most deadly encounters",
        top_deadly,
        lambda e: f"{e['losses']} runs ended",
    )

    st.markdown("---")

    hide_perfect = st.toggle("Hide 100% win-rate", value=True, key="metrics_hide_perfect")

    act_tabs = st.tabs(["Act 1", "Act 2", "Act 3"])

    with act_tabs[0]:
        variant = st.segmented_control(
            "Act 1 Variant", ["Overgrowth", "Underdocks"], default="Overgrowth",
            key="metrics_act1_variant",
        )
        if variant is None:
            variant = "Overgrowth"
        grouped = _collect_for_act(stats, target_char, act_idx=0, variant_key=variant, hide_perfect=hide_perfect)
        for pool in POOL_ORDER:
            st.markdown(f'<div class="pool-label">{pool}</div>', unsafe_allow_html=True)
            _render_pool_chips(grouped.get(pool, []))

    for act_i, tab in [(1, act_tabs[1]), (2, act_tabs[2])]:
        with tab:
            grouped = _collect_for_act(stats, target_char, act_idx=act_i, variant_key=ANY_VARIANT, hide_perfect=hide_perfect)
            for pool in POOL_ORDER:
                st.markdown(f'<div class="pool-label">{pool}</div>', unsafe_allow_html=True)
                _render_pool_chips(grouped.get(pool, []))

    st.markdown("---")
    st.caption("Enemies (individual monster stats) — coming soon.")

with tab_relic:
    st.markdown("##### Ancient Relic Picks")
    st.caption(
        "Per-ancient relic offerings — win rate when picked vs the baseline "
        "(this character's win rate among runs that reached this ancient). "
        "Δ = points above/below baseline."
    )
    sort_choice = st.segmented_control(
        "Sort by", ["Pick rate", "Win rate"],
        default="Pick rate", key="ancient_sort",
    )
    sort_key = "winrate" if sort_choice == "Win rate" else "pickrate"
    _render_ancient_relics(target_char, selected_char, sort_by=sort_key)
    st.markdown("---")
    st.caption("Full relics breakdown — coming next.")
