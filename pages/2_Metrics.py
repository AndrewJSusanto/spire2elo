import json
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))
import run_parser
from assets import character_icon_uri

st.set_page_config(page_title="Metrics — Spire2ELO", page_icon="📊", layout="wide")


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


def _get_runs_raw() -> dict:
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
    for data in _get_runs_raw().values():
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
    st.caption("Relics — coming soon.")
