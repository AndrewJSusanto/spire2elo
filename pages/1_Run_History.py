import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))
import run_parser
from assets import character_icon_uri, relic_icon_uri
from save_panel import render_save_panel


def _rr_char_icon(character: str) -> str:
    uri = character_icon_uri(character)
    if not uri:
        return ""
    return f'<img src="{uri}" style="height:1em; vertical-align:-0.18em; margin-right:6px;" alt="">'


# ── Data source helpers ────────────────────────────────────────────────────────
def _source_key() -> str:
    """Cache-invalidation key. 'local' or the upload hash."""
    return st.session_state.get("uploaded_hash", "local")


def _get_events_data() -> list:
    runs = st.session_state.get("uploaded_runs_by_id")
    if runs:
        return run_parser.events_from_runs_by_id(runs)
    return run_parser.load_all_events()


def _get_progress_data() -> Optional[dict]:
    if st.session_state.get("uploaded_progress"):
        return st.session_state["uploaded_progress"]
    try:
        with open(run_parser.HISTORY_DIR.parent / "progress.save") as f:
            return json.load(f)
    except Exception:
        return None


def _get_run_detail_data(run_id: str) -> dict:
    runs = st.session_state.get("uploaded_runs_by_id")
    if runs and run_id in runs:
        return run_parser.load_run_detail_from_data(runs[run_id], run_id)
    return run_parser.load_run_detail(run_id)


@st.cache_data
def _get_runs_raw(source_key: str) -> dict:
    """Returns {run_id: raw_run_data} for all available runs (uploaded or local).

    Cached on `source_key` so disk-backed runs are read+parsed once per session,
    and an upload swap (different source_key) triggers a refresh.
    """
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

ROOM_COLORS = {
    "monster": "#c75a5a",
    "elite":   "#7a3030",
    "boss":    "#1f1f1f",
    "rest_site": "#5e9bd1",
    "treasure": "#e0c060",
    "shop":    "#7b69b0",
    "event":   "#9bb37a",
    "ancient": "#d76edb",
    "unknown": "#888888",
}

CURSE_CARDS = {
    "ASCENDERS_BANE", "GREED", "NECRONOMICURSE", "CURSE_OF_THE_BELL",
    "PAIN", "REGRET", "SHAME", "PARASITE", "PRIDE", "WRITHE", "INJURY",
    "DOUBT", "NORMALITY", "DECAY", "CLUMSY",
}
STATUS_CARDS = {"WOUND", "DAZED", "SLIMED", "BURN", "VOID"}

CHIP_PALETTE = {
    "starter":   "#888888",
    "curse":     "#7a4ab8",
    "enchanted": "#d8c4ff",
    "upgraded":  "#5ec76d",
}

# Monster ids that are companions/summons rather than real enemies — exclude from encounter lists.
ALLY_MONSTERS = {"MONSTER.OSTY"}


@st.cache_data
def _build_card_owner_map(source_key: str) -> dict:
    """Card display name (w/o '+') -> character that most frequently offers it in card_choices."""
    events = _get_events_data()
    counts: dict = {}
    for e in events:
        char = e["character"]
        for name in e["offered"]:
            base = name.rstrip("+")
            counts.setdefault(base, {}).setdefault(char, 0)
            counts[base][char] += 1
    return {card: max(by_char.items(), key=lambda kv: kv[1])[0] for card, by_char in counts.items()}


def _card_color(card: dict, current_character: str) -> Optional[str]:
    short = card["id"].removeprefix("CARD.")
    if card.get("enchantment"):
        return CHIP_PALETTE["enchanted"]
    if card.get("current_upgrade_level", 0) >= 1:
        return CHIP_PALETTE["upgraded"]
    if short in CURSE_CARDS or short in STATUS_CARDS or short.startswith("CURSE_"):
        return CHIP_PALETTE["curse"]
    if "STRIKE_" in short or "DEFEND_" in short:
        return CHIP_PALETTE["starter"]
    if card.get("floor_added_to_deck", 0) == 1:
        return CHARACTER_COLORS.get(current_character)
    owner = _build_card_owner_map(_source_key()).get(_strip("CARD.", card["id"]))
    if owner and owner != current_character:
        return CHARACTER_COLORS.get(owner)
    return None


def _strip(prefix: str, raw: str) -> str:
    return raw.removeprefix(prefix).replace("_", " ").title()


def _picked_card(stats: dict) -> Optional[str]:
    for c in stats.get("card_choices", []):
        if c.get("was_picked"):
            return _strip("CARD.", c["card"]["id"])
    return None


def _skipped_cards(stats: dict) -> list[str]:
    return [_strip("CARD.", c["card"]["id"]) for c in stats.get("card_choices", []) if not c.get("was_picked")]


def _picked_relic(stats: dict) -> Optional[str]:
    for r in stats.get("relic_choices", []):
        if r.get("was_picked"):
            return _strip("RELIC.", r["choice"])
    return None


def _format_ancient(point: dict) -> list[str]:
    stats = point["raw_point"].get("player_stats", [{}])[0]
    ancient_name = None
    for a in stats.get("ancient_choice", []):
        if a.get("was_chosen"):
            ancient_name = a.get("TextKey", "?").replace("_", " ").title()
            break
    lines = ["<b>Ancient</b>"]
    if ancient_name:
        lines.append(f"Chose: {ancient_name}")
    relic = _picked_relic(stats)
    if relic:
        lines.append(f"Relic: {relic}")
    added_cards = [_strip("CARD.", c["id"]) for c in stats.get("cards_gained", [])]
    if added_cards:
        lines.append(f"Added to deck: {', '.join(added_cards)}")
    return lines


def _format_combat(point: dict) -> list[str]:
    stats = point["raw_point"].get("player_stats", [{}])[0]
    rooms = point["raw_point"].get("rooms", [{}])
    room = rooms[0] if rooms else {}
    monsters = [m for m in room.get("monster_ids", []) if m not in ALLY_MONSTERS]
    mob_label = ", ".join(_strip("MONSTER.", m) for m in monsters) if monsters else _strip("ENCOUNTER.", room.get("model_id", "Unknown"))
    type_label = point["map_point_type"].upper()
    lines = [f"<b>{type_label}</b> · {mob_label}"]
    turns = room.get("turns_taken")
    if turns:
        lines.append(f"Turns: {turns}")
    lines.append(f"Damage taken: {stats.get('damage_taken', 0)}")
    healed = stats.get("hp_healed", 0)
    if healed:
        lines.append(f"Healed: {healed}")
    picked = _picked_card(stats)
    if picked:
        lines.append(f"Picked: {picked}")
    skipped = _skipped_cards(stats)
    if skipped:
        lines.append(f"Skipped: {', '.join(skipped)}")
    relic = _picked_relic(stats)
    if relic:
        lines.append(f"Relic: {relic}")
    return lines


def _format_shop(point: dict) -> list[str]:
    stats = point["raw_point"].get("player_stats", [{}])[0]
    bought_cards = [_strip("CARD.", c["card"]["id"]) for c in stats.get("card_choices", []) if c.get("was_picked")]
    skipped_cards = [_strip("CARD.", c["card"]["id"]) for c in stats.get("card_choices", []) if not c.get("was_picked")]
    bought_relics = [_strip("RELIC.", r["choice"]) for r in stats.get("relic_choices", []) if r.get("was_picked")]
    removed_cards = [_strip("CARD.", c["id"]) for c in stats.get("cards_removed", [])]

    lines = ["<b>Shop</b>"]
    if bought_cards:
        lines.append(f"Cards taken: {', '.join(bought_cards)}")
    if bought_relics:
        lines.append(f"Relics taken: {', '.join(bought_relics)}")
    if removed_cards:
        lines.append(f"Cards removed: {', '.join(removed_cards)}")
    if skipped_cards:
        lines.append(f"Cards skipped: {', '.join(skipped_cards)}")
    return lines


def _format_event(point: dict) -> list[str]:
    rooms = point["raw_point"].get("rooms", [{}])
    room = rooms[0] if rooms else {}
    event_name = _strip("EVENT.", room.get("model_id", "Unknown Event"))
    # skeleton — to be expanded later
    return [f"<b>Event</b> · {event_name}"]


def _format_rest(point: dict) -> list[str]:
    stats = point["raw_point"].get("player_stats", [{}])[0]
    choices = stats.get("rest_site_choices", [])
    lines = ["<b>Rest Site</b>"]
    for choice in choices:
        if choice == "REST":
            lines.append(f"Rested · healed {stats.get('hp_healed', 0)}")
        elif choice == "SMITH":
            upgraded = [_strip("CARD.", c) for c in stats.get("upgraded_cards", [])]
            lines.append(f"Smithed: {', '.join(upgraded) if upgraded else '?'}")
        else:
            lines.append(choice.replace("_", " ").title())
    return lines


def _format_default(point: dict) -> list[str]:
    return [f"<b>{point['map_point_type'].title()}</b>", f"Floor {point['floor']}"]


def _hover_for(point: dict) -> str:
    t = point["map_point_type"]
    if t == "ancient":
        lines = _format_ancient(point)
    elif t in ("monster", "elite", "boss"):
        lines = _format_combat(point)
    elif t in ("event", "unknown"):
        lines = _format_event(point)
    elif t == "rest_site":
        lines = _format_rest(point)
    elif t == "shop":
        lines = _format_shop(point)
    else:
        lines = _format_default(point)

    stats = point["raw_point"].get("player_stats", [{}])[0]
    lines.append(f"HP: {stats.get('current_hp', '?')}/{stats.get('max_hp', '?')}")
    lines.append(f"Gold: {stats.get('current_gold', '?')}")

    return f"Act {point['act_idx'] + 1} · Floor {point['floor']}<br>" + "<br>".join(lines)


def _render_run_map(detail: dict):
    fig = go.Figure()
    MAX_SAG = 0.85
    MAX_RISE = 0.3
    ACT_SPACING = 2.6
    prev_end = None

    starting_hp = 1
    if detail["acts"] and detail["acts"][0]:
        first_stats = detail["acts"][0][0]["raw_point"].get("player_stats", [{}])[0]
        starting_hp = first_stats.get("current_hp") or first_stats.get("max_hp") or 1

    last_act_idx = max((a[0]["act_idx"] for a in detail["acts"] if a), default=-1)
    END_COLOR = "#2e8b3d" if detail["win"] else "#8b1a1a"

    def _hp_offset(point: dict) -> float:
        stats = point["raw_point"].get("player_stats", [{}])[0]
        cur = stats.get("current_hp")
        if cur is None or starting_hp <= 0:
            return 0.0
        delta_ratio = (cur - starting_hp) / starting_hp
        if delta_ratio < 0:
            return max(-MAX_SAG, MAX_SAG * delta_ratio)
        return min(MAX_RISE, MAX_RISE * delta_ratio)

    for act in detail["acts"]:
        if not act:
            continue
        act_idx = act[0]["act_idx"]
        xs = [p["position"] for p in act]
        base_y = -act_idx * ACT_SPACING
        ys = [base_y + _hp_offset(p) for p in act]
        colors = [ROOM_COLORS.get(p["map_point_type"], "#888") for p in act]
        if act_idx == last_act_idx and colors:
            colors[-1] = END_COLOR
        hovers = [_hover_for(p) for p in act]

        if prev_end is not None:
            fig.add_trace(go.Scatter(
                x=[prev_end[0], xs[0]],
                y=[prev_end[1], ys[0]],
                mode="lines",
                line=dict(color="rgba(200,200,200,0.35)", width=1.5, dash="dot", shape="spline", smoothing=1.3),
                hoverinfo="skip", showlegend=False,
            ))

        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="lines",
            line=dict(color="rgba(160,160,160,0.4)", width=2, shape="spline", smoothing=1.0),
            hoverinfo="skip", showlegend=False,
        ))
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="markers",
            marker=dict(size=22, color=colors, line=dict(color="white", width=1)),
            text=hovers,
            hovertemplate="%{text}<extra></extra>",
            showlegend=False,
        ))

        prev_end = (xs[-1], ys[-1])

    fig.update_yaxes(
        tickmode="array",
        tickvals=[-i * ACT_SPACING for i in range(len(detail["acts"]))],
        ticktext=[f"Act {i + 1}" for i in range(len(detail["acts"]))],
        showgrid=False, zeroline=False,
    )
    fig.update_xaxes(showticklabels=False, showgrid=False, zeroline=False)
    max_nodes = max((len(a) for a in detail["acts"]), default=1)
    NODE_SPACING_PX = 60
    fig_width = max(700, max_nodes * NODE_SPACING_PX + 120)

    fig.update_layout(
        height=220,
        width=fig_width,
        margin=dict(t=5, b=5, l=60, r=20),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )

    chart_html = pio.to_html(fig, include_plotlyjs="cdn", full_html=False, config={"displayModeBar": False})
    wrapped = (
        '<div style="overflow-x:auto; overflow-y:hidden; width:100%;">'
        f'{chart_html}'
        '</div>'
    )
    st.components.v1.html(wrapped, height=240, scrolling=False)


def _mob_label(point: dict) -> str:
    room = point["raw_point"].get("rooms", [{}])[0]
    monsters = [m for m in room.get("monster_ids", []) if m not in ALLY_MONSTERS]
    if monsters:
        return ", ".join(_strip("MONSTER.", m) for m in monsters)
    return _strip("ENCOUNTER.", room.get("model_id", "Unknown"))


def _render_decklist(detail: dict):
    deck = detail.get("deck", [])
    if not deck:
        st.caption("No deck data.")
        return

    char_suffixes = {f"_{c.upper()}" for c in CHARACTER_COLORS}

    def _card_chip_label(card: dict) -> str:
        short = card["id"].removeprefix("CARD.")
        for suffix in char_suffixes:
            if short.endswith(suffix):
                short = short[: -len(suffix)]
                break
        name = short.replace("_", " ").title()
        if card.get("current_upgrade_level", 0) >= 1:
            name += "+"
        ench = card.get("enchantment")
        if ench:
            ench_name = ench["id"].removeprefix("ENCHANTMENT.").replace("_", " ").title()
            amount = ench.get("amount", 1)
            name += f" ({ench_name} {amount})"
        return name

    current_char = detail.get("character", "")

    # Walk deck in original order; stack contiguous identical entries.
    chips: list[dict] = []
    for card in deck:
        label = _card_chip_label(card)
        color = _card_color(card, current_char)
        if chips and chips[-1]["name"] == label and chips[-1]["color"] == color:
            chips[-1]["count"] += 1
        else:
            chips.append({"name": label, "count": 1, "color": color})

    html = []
    for c in chips:
        if c["color"]:
            style = (
                f'background:{c["color"]}26; '
                f'border:1px solid {c["color"]}99; '
                f'color:{c["color"]};'
            )
        else:
            style = (
                'background:rgba(255,255,255,0.06); '
                'border:1px solid rgba(255,255,255,0.1); '
                'color:inherit;'
            )
        html.append(
            f'<span style="display:inline-block; padding:2px 8px; margin:2px; '
            f'border-radius:10px; font-size:0.85rem; {style}">'
            f'<b>{c["count"]}x</b> {c["name"]}</span>'
        )
    st.markdown(
        f'<div style="line-height:1.8;">{"".join(html)}</div>',
        unsafe_allow_html=True,
    )


def _compute_insights(detail: dict) -> dict:
    """
    Returns:
        hardest:   {act, floor, mob, damage} or None
        closest:   {act, floor, hp, max_hp} or None
        deck_online: {after_floor, before_avg, after_avg, drop_pct} or None
    """
    combat_types = {"monster", "elite", "boss"}
    all_points = [p for act in detail["acts"] for p in act]

    # Hardest fight — any combat
    combat_points = [p for p in all_points if p["map_point_type"] in combat_types]
    hardest = None
    if combat_points:
        worst = max(combat_points, key=lambda p: p["raw_point"]["player_stats"][0].get("damage_taken", 0))
        worst_stats = worst["raw_point"]["player_stats"][0]
        if worst_stats.get("damage_taken", 0) > 0:
            hardest = {
                "act": worst["act_idx"] + 1,
                "floor": worst["floor"],
                "mob": _mob_label(worst),
                "damage": worst_stats["damage_taken"],
            }

    # Lowest health reached — exclude HP=0 (death/end-of-run)
    closest = None
    hp_points = [p for p in all_points if p["raw_point"]["player_stats"]
                 and p["raw_point"]["player_stats"][0].get("current_hp") not in (None, 0)]
    if hp_points:
        worst = min(hp_points, key=lambda p: p["raw_point"]["player_stats"][0]["current_hp"])
        s = worst["raw_point"]["player_stats"][0]
        closest = {
            "act": worst["act_idx"] + 1,
            "floor": worst["floor"],
            "hp": s["current_hp"],
            "max_hp": s.get("max_hp", "?"),
        }

    # Deck came online — split anywhere (combat or non-combat).
    # Measure non-boss combat damage before vs after each split index.
    measured = [(i, p) for i, p in enumerate(all_points) if p["map_point_type"] in ("monster", "elite")]
    deck_online = None
    if len(measured) >= 6:
        best_drop = 0.0
        best_split = None
        # Iterate every node as a candidate split point; require ≥3 measured combats on each side.
        for split_idx in range(1, len(all_points)):
            before = [d for i, p in measured if i < split_idx for d in [p["raw_point"]["player_stats"][0].get("damage_taken", 0)]]
            after = [d for i, p in measured if i >= split_idx for d in [p["raw_point"]["player_stats"][0].get("damage_taken", 0)]]
            if len(before) < 3 or len(after) < 3:
                continue
            before_avg = sum(before) / len(before)
            after_avg = sum(after) / len(after)
            if before_avg <= 0:
                continue
            drop = (before_avg - after_avg) / before_avg
            if drop > best_drop:
                best_drop = drop
                best_split = (split_idx, before, after)
        if best_split is not None and best_drop >= 0.35:
            split_idx, before_dmg, after_dmg = best_split
            split_node = all_points[split_idx - 1]  # the node that completed the inflection
            deck_online = {
                "after_floor": split_node["floor"],
                "after_act": split_node["act_idx"] + 1,
                "after_type": split_node["map_point_type"],
                "before_avg": sum(before_dmg) / len(before_dmg),
                "after_avg": sum(after_dmg) / len(after_dmg),
                "drop_pct": best_drop * 100,
            }

    # Big shop trip — shop with the most gold spent
    shops = [p for p in all_points if p["map_point_type"] == "shop"]
    big_shop = None
    if shops:
        biggest = max(shops, key=lambda p: p["raw_point"]["player_stats"][0].get("gold_spent", 0))
        bs = biggest["raw_point"]["player_stats"][0]
        spent = bs.get("gold_spent", 0)
        if spent > 0:
            bought_cards = [_strip("CARD.", c["card"]["id"]) for c in bs.get("card_choices", []) if c.get("was_picked")]
            bought_relics = [_strip("RELIC.", r["choice"]) for r in bs.get("relic_choices", []) if r.get("was_picked")]
            removed_cards = [_strip("CARD.", c["id"]) for c in bs.get("cards_removed", [])]
            big_shop = {
                "act": biggest["act_idx"] + 1,
                "floor": biggest["floor"],
                "spent": spent,
                "cards": bought_cards,
                "relics": bought_relics,
                "removed": removed_cards,
            }

    return {"hardest": hardest, "closest": closest, "deck_online": deck_online, "big_shop": big_shop}


def _render_relics_bar(detail: dict):
    relics = detail.get("relics", [])
    if not relics:
        st.caption("No relics.")
        return
    char = detail.get("character", "")
    sorted_relics = sorted(relics, key=lambda r: r.get("floor_added_to_deck", 0))
    items = []
    for r in sorted_relics:
        rid = r.get("id", "")
        if not rid:
            continue
        label = rid.removeprefix("RELIC.").replace("_", " ").title()
        uri = relic_icon_uri(rid, character=char)
        if uri:
            items.append(
                f'<span class="relic-tip" data-tooltip="{label}">'
                f'<img src="{uri}" class="dl-relic-icon" alt="{label}"></span>'
            )
        else:
            items.append(
                f'<span class="relic-tip dl-relic-fallback" data-tooltip="{label}">{label}</span>'
            )
    st.markdown(
        """
        <style>
        .dl-relic-bar {
            display: flex;
            flex-wrap: wrap;
            gap: 5px;
            align-items: center;
            padding: 4px 0;
        }
        .dl-relic-icon {
            height: 30px;
            width: 30px;
            object-fit: contain;
            border-radius: 4px;
        }
        .dl-relic-fallback {
            font-size: 0.78rem;
            padding: 2px 6px;
            border-radius: 4px;
            background: rgba(255,255,255,0.06);
            border: 1px solid rgba(255,255,255,0.15);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(f'<div class="dl-relic-bar">{"".join(items)}</div>', unsafe_allow_html=True)


# Stashed
def _render_insights(detail: dict):
    insights = _compute_insights(detail)

    st.markdown(
        """
        <style>
        .insight-label {
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            opacity: 0.6;
            margin-top: 10px;
            margin-bottom: 2px;
        }
        .insight-chip {
            display: inline-block;
            padding: 6px 12px;
            margin: 4px 4px 4px 0;
            border-radius: 6px;
            font-size: 0.88rem;
            border: 1px solid rgba(255,255,255,0.2);
            background: rgba(255,255,255,0.06);
            color: inherit;
            font-weight: 500;
        }
        .insight-chip b { font-weight: 700; }
        .insight-chip .ctx {
            opacity: 0.55;
            font-weight: 400;
            font-size: 0.85em;
        }
        .insight-extra {
            font-size: 0.82rem;
            opacity: 0.65;
            padding-left: 4px;
            margin-top: -2px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    def _emit(label: str, body: str, extra: str = ""):
        html = f'<div class="insight-label">{label}</div><span class="insight-chip">{body}</span>'
        if extra:
            html += f'<div class="insight-extra">{extra}</div>'
        st.markdown(html, unsafe_allow_html=True)

    if insights["hardest"]:
        h = insights["hardest"]
        _emit(
            "Highest Damage Taken",
            f'<b>{h["damage"]} dmg</b> · {h["mob"]} '
            f'<span class="ctx">(Act {h["act"]} · Floor {h["floor"]})</span>',
        )
    if insights["closest"]:
        c = insights["closest"]
        _emit(
            "Lowest Health Reached",
            f'<b>{c["hp"]}/{c["max_hp"]} HP</b> '
            f'<span class="ctx">(Act {c["act"]} · Floor {c["floor"]})</span>',
        )
    if insights["deck_online"]:
        d = insights["deck_online"]
        _emit(
            "Deck Came Online",
            f'<b>{d["before_avg"]:.1f} → {d["after_avg"]:.1f}</b> avg dmg '
            f'<span class="ctx">({d["drop_pct"]:.0f}% drop · after Act {d["after_act"]} · Floor {d["after_floor"]})</span>',
        )
    elif insights["hardest"]:
        st.caption("No clear 'deck online' inflection — damage stayed relatively steady throughout.")
    if insights["big_shop"]:
        s = insights["big_shop"]
        parts = []
        if s["cards"]:
            parts.append(f"Cards: {', '.join(s['cards'])}")
        if s["relics"]:
            parts.append(f"Relics: {', '.join(s['relics'])}")
        if s["removed"]:
            parts.append(f"Removed: {', '.join(s['removed'])}")
        _emit(
            "Largest Sum Spent",
            f'<b>{s["spent"]}g</b> '
            f'<span class="ctx">(Act {s["act"]} · Floor {s["floor"]})</span>',
            extra=" · ".join(parts),
        )


def _render_legend(win: bool):
    end_color = "#2e8b3d" if win else "#8b1a1a"
    end_label = "Final (Win)" if win else "Final (Loss)"
    items = list(ROOM_COLORS.items()) + [("end", end_color)]
    html = ['<div style="font-size:0.8rem; line-height:1.6; padding-top:4px;">']
    for room_type, color in items:
        label = end_label if room_type == "end" else room_type.replace("_", " ").title()
        if room_type == "end":
            color = end_color
        html.append(
            f'<div style="display:flex; align-items:center; gap:6px;">'
            f'<span style="display:inline-block; width:11px; height:11px; background:{color}; border-radius:50%; border:1px solid rgba(255,255,255,0.3);"></span>'
            f'<span>{label}</span>'
            f'</div>'
        )
    html.append('</div>')
    st.markdown("".join(html), unsafe_allow_html=True)


@st.dialog("Run Timeline", width="large")
def show_run_detail(run_id: str):
    detail = _get_run_detail_data(run_id)
    result_label = "Win" if detail["win"] else "Loss"
    result_color = WIN_COLOR if detail["win"] else LOSS_COLOR
    char_hex = CHARACTER_COLORS.get(detail["character"], "inherit")
    icon_html = _rr_char_icon(detail["character"])
    st.markdown(
        f'<h4 style="margin:0;">{icon_html}'
        f'<span style="color:{char_hex}">{detail["character"]}</span> - '
        f'A{detail["ascension"]} - '
        f'<span style="color:{result_color}">{result_label}</span></h4>',
        unsafe_allow_html=True,
    )

    graph_col, legend_col = st.columns([8, 1])
    with graph_col:
        _render_run_map(detail)
    with legend_col:
        _render_legend(detail["win"])

    with st.container(height=480, border=True):
        deck_col, insights_col = st.columns(2)
        TIGHT_HR = '<hr style="margin:0.1rem 0 0.6rem 0; border:none; border-top:1px solid rgba(255,255,255,0.15);">'
        with deck_col:
            st.markdown(f"##### Decklist{TIGHT_HR}", unsafe_allow_html=True)
            _render_decklist(detail)
            st.markdown(f"##### Relics{TIGHT_HR}", unsafe_allow_html=True)
            _render_relics_bar(detail)
        with insights_col:
            # Insights intentionally blank — see _render_insights for stashed code.
            pass

st.set_page_config(page_title="Run History — Spire2ELO", page_icon="📜", layout="wide")

CHARACTER_COLORS = {
    "Ironclad": "#e05555",
    "Regent": "#e07b30",
    "Necrobinder": "#b39ddb",
    "Silent": "#4caf50",
    "Defect": "#64b5f6",
}
WIN_COLOR = "#4caf50"
LOSS_COLOR = "#e05555"


@st.cache_data
def load_run_summaries(source_key: str) -> pd.DataFrame:
    """Build the Run History row list directly from raw run dicts.

    Skips the heavier event-extraction path (`events_from_runs_by_id`) which
    walks every card_choice in every player_stats — none of which the row list
    needs. Also fuses the ancient-relic extraction into the same map_point_history
    walk, so we visit each run's history exactly once.
    """
    columns = [
        "run_id", "date", "character", "ascension", "act1_variant",
        "won", "final_floor", "final_deck_size", "ancient_relics",
    ]
    runs_raw = _get_runs_raw(source_key)
    if not runs_raw:
        return pd.DataFrame(columns=columns)

    rows = []
    for rid, data in runs_raw.items():
        # Single walk over map_point_history: count floors + collect ancient relics.
        floor_count = 0
        relics = []
        for act in data.get("map_point_history", []):
            floor_count += len(act)
            for point in act:
                if point.get("map_point_type") != "ancient":
                    continue
                for ps in point.get("player_stats", []):
                    for ac in ps.get("ancient_choice", []):
                        if ac.get("was_chosen") and ac.get("TextKey"):
                            relics.append(f"RELIC.{ac['TextKey']}")

        raw_acts = data.get("acts", [])
        try:
            ts = int(rid)
            date = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            date = rid

        rows.append({
            "run_id": rid,
            "date": date,
            "character": data["players"][0]["character"].removeprefix("CHARACTER.").title(),
            "ascension": data.get("ascension", 0),
            "act1_variant": raw_acts[0].removeprefix("ACT.").title() if raw_acts else "—",
            "won": data.get("win", False),
            "final_floor": floor_count,
            "final_deck_size": len(data["players"][0].get("deck", [])),
            "ancient_relics": relics,
        })

    return pd.DataFrame(rows).sort_values("run_id", ascending=False).reset_index(drop=True)


def load_progress() -> dict:
    return _get_progress_data() or {}


def _fmt_secs(s: int) -> str:
    if not s:
        return "—"
    h, rem = divmod(int(s), 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {sec}s"
    return f"{sec}s"


def _filter_char_entries(progress: dict, filter_char: str) -> list:
    entries = [e for e in progress.get("character_stats", []) if e.get("id") != "CHARACTER.RANDOM_CHARACTER"]
    if filter_char == "All":
        return entries
    target = f"CHARACTER.{filter_char.upper()}"
    return [e for e in entries if e.get("id") == target]


def _aggregate_badges(entries: list) -> dict:
    """Returns {(id, rarity): total_count}."""
    out: dict = {}
    for e in entries:
        for b in e.get("badges", []):
            key = (b["id"], b["rarity"])
            out[key] = out.get(key, 0) + b.get("count", 1)
    return out


ANCIENT_ORDER = [
    ("EVENT.NEOW", "1"),
    ("EVENT.OROBAS", "2"),
    ("EVENT.PAEL", "2"),
    ("EVENT.TEZCATARA", "2"),
    ("EVENT.TANX", "3"),
    ("EVENT.NONUPEIPE", "3"),
    ("EVENT.VAKUU", "3"),
    ("EVENT.DARV", None),  # special — split into Act 2 / Act 3 from .run files
]


@st.cache_data
def load_ancient_encounters(source_key: str) -> list:
    """One row per ancient encounter: {run_id, character, ancient_id, act_idx (0-based), won}."""
    out = []
    for run_id, data in _get_runs_raw(source_key).items():
        won = data.get("win", False)
        char = data["players"][0]["character"]
        for act_idx, act in enumerate(data.get("map_point_history", [])):
            for point in act:
                if point.get("map_point_type") != "ancient":
                    continue
                for room in point.get("rooms", []):
                    aid = room.get("model_id")
                    if aid:
                        out.append({
                            "run_id": run_id,
                            "character": char,
                            "ancient_id": aid,
                            "act_idx": act_idx,
                            "won": won,
                        })
    return out


def _darv_rows(filter_char: str) -> list:
    target = None if filter_char == "All" else f"CHARACTER.{filter_char.upper()}"
    encs = [e for e in load_ancient_encounters(_source_key()) if e["ancient_id"] == "EVENT.DARV"]
    if target:
        encs = [e for e in encs if e["character"] == target]
    by_act: dict = {}
    for e in encs:
        bucket = by_act.setdefault(e["act_idx"], {"wins": 0, "losses": 0})
        if e["won"]:
            bucket["wins"] += 1
        else:
            bucket["losses"] += 1
    rows = []
    for act_idx in (1, 2):  # Act 2 then Act 3
        if act_idx not in by_act:
            continue
        s = by_act[act_idx]
        total = s["wins"] + s["losses"]
        if total > 0:
            rows.append({
                "Act": str(act_idx + 1),
                "Ancient": "Darv",
                "W": s["wins"], "L": s["losses"],
                "Win Rate %": round(s["wins"] / total * 100, 1),
            })
    return rows


def _ancient_winrates(progress: dict, filter_char: str) -> list:
    target = None if filter_char == "All" else f"CHARACTER.{filter_char.upper()}"
    by_id = {a["ancient_id"]: a for a in progress.get("ancient_stats", [])}

    rows = []
    for aid, act in ANCIENT_ORDER:
        if aid == "EVENT.DARV":
            rows.extend(_darv_rows(filter_char))
            continue
        ancient = by_id.get(aid)
        if not ancient:
            continue
        wins, losses = 0, 0
        for entry in ancient.get("character_stats", []):
            if target is None or entry["character"] == target:
                wins += entry.get("wins", 0)
                losses += entry.get("losses", 0)
        total = wins + losses
        if total > 0:
            rows.append({
                "Act": act,
                "Ancient": aid.removeprefix("EVENT.").replace("_", " ").title(),
                "W": wins, "L": losses, "Win Rate %": round(wins / total * 100, 1),
            })
    rows.sort(key=lambda r: int(r["Act"]))
    return rows


BADGE_RARITY_COLOR = {"gold": "#e7c14e", "silver": "#c0c4cc", "bronze": "#c98758"}


def _render_lifetime_panel(progress: dict, filter_char: str):
    entries = _filter_char_entries(progress, filter_char)
    if not entries:
        st.info("No lifetime stats available.")
        return

    total_wins = sum(e.get("total_wins", 0) for e in entries)
    total_losses = sum(e.get("total_losses", 0) for e in entries)
    total = total_wins + total_losses
    win_rate = (total_wins / total * 100) if total else 0
    best_streak = max((e.get("best_win_streak", 0) for e in entries), default=0)
    fastest_vals = [e.get("fastest_win_time", 0) for e in entries if e.get("fastest_win_time", 0) > 0]
    fastest = min(fastest_vals) if fastest_vals else 0
    max_asc = max((e.get("max_ascension", 0) for e in entries), default=0)
    playtime = sum(e.get("playtime", 0) for e in entries)

    metrics = [
        ("Record", f"{total_wins}W / {total_losses}L"),
        ("Win Rate", f"{win_rate:.1f}%"),
        ("Best Streak", best_streak),
        ("Fastest", _fmt_secs(fastest)),
        ("Max Asc", max_asc),
    ]

    st.markdown(
        """
        <style>
        [data-testid="stMetricValue"] { font-size: 1.2rem; }
        [data-testid="stMetricLabel"] { font-size: 0.78rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    cols = st.columns(len(metrics))
    for col, (label, value) in zip(cols, metrics):
        col.metric(label, value)
    st.caption(f"Total playtime: {_fmt_secs(playtime)}")

    badges = _aggregate_badges(entries)
    if badges:
        chips = []
        rarity_rank = {"gold": 0, "silver": 1, "bronze": 2}
        for (badge_id, rarity), count in sorted(
            badges.items(),
            key=lambda kv: (rarity_rank.get(kv[0][1], 99), -kv[1], kv[0][0]),
        ):
            color = BADGE_RARITY_COLOR.get(rarity, "#888")
            label = badge_id.replace("_", " ").title()
            chips.append(
                f'<span style="display:inline-block; padding:2px 8px; margin:2px; '
                f'border-radius:10px; background:{color}22; border:1px solid {color}99; '
                f'color:{color}; font-size:0.8rem;"><b>{count}x</b> {label}</span>'
            )
        st.markdown(
            f'<div style="line-height:1.8;">{"".join(chips)}</div>',
            unsafe_allow_html=True,
        )


def _current_streak_chars(df: pd.DataFrame, filter_char: str = "All") -> list:
    """Return the list of characters (most-recent first) for the current consecutive-win streak.

    Iterates rows of `df` (which is already most-recent first), stopping at the first loss.
    """
    view = df if filter_char == "All" else df[df["character"] == filter_char]
    chars: list = []
    for _, row in view.iterrows():
        if row["won"]:
            chars.append(row["character"])
        else:
            break
    return chars


def _render_streak_indicator(df: pd.DataFrame, selected_char: str):
    rotating_count = len(_current_streak_chars(df, "All"))
    char_count = len(_current_streak_chars(df, selected_char)) if selected_char != "All" else 0

    # Character line — always rendered so layout stays put; hidden when on "All".
    if selected_char != "All":
        char_hex = CHARACTER_COLORS.get(selected_char, "#ccc")
        char_line = (
            f'<div style="font-size:0.92rem;">'
            f'<span style="color:{char_hex}; font-weight:600;">{selected_char}</span>: '
            f'<b>{char_count}</b></div>'
        )
    else:
        char_line = '<div style="font-size:0.92rem; visibility:hidden;">&nbsp;</div>'

    # Flourish indicator — always rendered (placeholder when not relevant) for
    # layout stability. Only visible on a character tab with an active streak.
    if selected_char != "All" and char_count > 0:
        icon = _rr_char_icon(selected_char)
        indicator_inner = f'{icon}{char_count}-streak!'
        indicator_style = ""
    else:
        indicator_inner = "&nbsp;"
        indicator_style = "visibility:hidden;"

    st.markdown(
        f'<div style="text-align:right; padding-top:14px;">'
        f'<div style="font-size:0.72rem; text-transform:uppercase; '
        f'letter-spacing:0.08em; opacity:0.55;">Current Streaks</div>'
        f'<div style="font-size:0.92rem; margin-top:2px;">Rotating: <b>{rotating_count}</b></div>'
        f'{char_line}'
        f'<div style="margin-top:10px; font-size:1.05rem; font-weight:700; '
        f'letter-spacing:0.01em; min-height:1.4em; {indicator_style}">'
        f'{indicator_inner}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def _render_recent_panel(df: pd.DataFrame, filter_char: str, n: int = 10):
    """Aggregates from the first N rows of the run-summaries DataFrame
    (already sorted most-recent first by `load_run_summaries`)."""
    view = df if filter_char == "All" else df[df["character"] == filter_char]
    recent = view.head(n)
    if recent.empty:
        st.info("No runs available for the selected character.")
        return

    wons = recent["won"].tolist()  # most-recent first
    wins = sum(1 for w in wons if w)
    losses = len(wons) - wins
    win_rate = (wins / len(wons) * 100) if wons else 0
    max_asc = int(recent["ascension"].max())

    metrics = [
        ("Record", f"{wins}W / {losses}L"),
        ("Win Rate", f"{win_rate:.1f}%"),
        ("Max Asc", max_asc),
    ]

    st.markdown(
        """
        <style>
        [data-testid="stMetricValue"] { font-size: 1.2rem; }
        [data-testid="stMetricLabel"] { font-size: 0.78rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    cols = st.columns(len(metrics))
    for col, (label, value) in zip(cols, metrics):
        col.metric(label, value)
    st.caption(f"Based on the **{len(recent)}** most recent runs")

    # ── Last-N visualizer: one box per run (most recent on the left) ────────
    boxes = []
    for _, row in recent.iterrows():
        color = "#4caf50" if row["won"] else "#e05555"
        tooltip = (
            f"{'WIN' if row['won'] else 'LOSS'} · {row['character']} "
            f"A{row['ascension']} · Floor {row['final_floor']}"
        )
        boxes.append(
            f'<div class="last10-box" style="background:{color};" title="{tooltip}"></div>'
        )
    st.markdown(
        """
        <style>
        .last10-strip {
            display: flex;
            gap: 5px;
            margin-top: 8px;
            align-items: center;
        }
        .last10-box {
            width: 26px;
            height: 26px;
            border-radius: 4px;
            border: 1px solid rgba(255,255,255,0.12);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="last10-strip">{"".join(boxes)}</div>',
        unsafe_allow_html=True,
    )


def _render_ancient_panel(progress: dict, filter_char: str):
    rows = _ancient_winrates(progress, filter_char)
    if not rows:
        st.caption("No ancient encounters recorded.")
        return
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        use_container_width=True,
        height=min(40 + 36 * len(rows), 320),
    )


# ── Save data uploader (shared) ───────────────────────────────────────────────
render_save_panel()

df = load_run_summaries(_source_key())

if df.empty:
    st.title("Run History")
    st.info(
        "👋 No run data loaded yet. Upload your zipped Slay the Spire 2 `saves/` "
        "folder in the sidebar."
    )
    st.caption(
        "Your `saves/` folder lives at "
        "`~/Library/Application Support/SlayTheSpire2/steam/<id>/profile<n>/saves` on macOS, "
        r"or something like `C:\Users\<user>\AppData\Roaming\SlayTheSpire2\steam` on Windows. "
        "Zip the folder (containing `progress.save` and `history/`) and drop it into the uploader."
    )
    st.stop()

all_chars = sorted(df["character"].unique())

# Title slot rendered first (visually on top)
title_slot = st.empty()

selected_char = st.segmented_control("Character", ["All"] + all_chars, default="All")
if selected_char is None:
    selected_char = "All"

with title_slot.container():
    title_col, streak_col = st.columns([3, 2])
    with title_col:
        st.title("Run History")
        st.caption("Most recent runs at the top. Click a run to inspect its full timeline.")
    with streak_col:
        _render_streak_indicator(df, selected_char)

progress = load_progress()
header_label = "All Characters" if selected_char == "All" else selected_char
header_icon = "" if selected_char == "All" else _rr_char_icon(selected_char)

overview_mode = st.segmented_control(
    "Overview window",
    ["Lifetime", "Last 10 runs"],
    default="Last 10 runs",
    key="overview_mode",
    label_visibility="collapsed",
)
if overview_mode is None:
    overview_mode = "Last 10 runs"

header_prefix = "Lifetime" if overview_mode == "Lifetime" else "Last 10"
st.markdown(
    f'<h5>{header_prefix} — {header_icon}{header_label}</h5>',
    unsafe_allow_html=True,
)

stats_col, ancient_col = st.columns([3, 2])
with stats_col:
    if overview_mode == "Last 10 runs":
        _render_recent_panel(df, selected_char, n=10)
    else:
        _render_lifetime_panel(progress, selected_char)
with ancient_col:
    st.markdown("**Ancient win rates**")
    _render_ancient_panel(progress, selected_char)

st.markdown("---")

view = df if selected_char == "All" else df[df["character"] == selected_char].reset_index(drop=True)

st.markdown(
    """
    <style>
    .run-row {
        display: flex;
        align-items: center;
        padding: 10px 14px;
        margin-bottom: 6px;
        border-radius: 6px;
        border-left: 4px solid;
        background: rgba(255,255,255,0.02);
        font-size: 0.92rem;
        line-height: 1.3;
    }
    .run-row.win  { border-left-color: #4caf50; background: rgba(76,175,80,0.06); }
    .run-row.loss { border-left-color: #e05555; background: rgba(224,85,85,0.05); }
    .rr-result { width: 60px; font-weight: 700; }
    .rr-char   { width: 165px; font-weight: 600; display: flex; align-items: center; }
    .rr-meta   { flex: 1; opacity: 0.85; display: flex; gap: 12px; align-items: center; }
    .rr-meta .rr-sep { opacity: 0.3; }
    .rr-meta small { opacity: 0.7; }
    .rr-relics { display: flex; gap: 3px; align-items: center; }
    .rr-relic-icon { height: 22px; width: 22px; object-fit: contain; border-radius: 3px; }
    .rr-date   { width: 130px; text-align: right; opacity: 0.65; font-size: 0.85rem; }
    .relic-tip { position: relative; display: inline-flex; }
    .relic-tip:hover::after {
        content: attr(data-tooltip);
        position: absolute;
        bottom: 115%;
        left: 50%;
        transform: translateX(-50%);
        background: #1e1e1e;
        color: white;
        padding: 4px 8px;
        border-radius: 4px;
        font-size: 0.75rem;
        white-space: nowrap;
        z-index: 100;
        border: 1px solid rgba(255,255,255,0.2);
        pointer-events: none;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

PAGE_SIZE = 25
total = len(view)
if total > PAGE_SIZE:
    page = st.number_input("Page", 1, (total + PAGE_SIZE - 1) // PAGE_SIZE, 1, key="rh_page")
    start = (page - 1) * PAGE_SIZE
    view_page = view.iloc[start:start + PAGE_SIZE].reset_index(drop=True)
    st.caption(f"Showing {start + 1}–{start + len(view_page)} of {total} runs")
else:
    view_page = view
    st.caption(f"Showing {total} of {total} runs")

for run in view_page.itertuples(index=False):
    char_color = CHARACTER_COLORS.get(run.character, "#cccccc")
    result_class = "win" if run.won else "loss"
    result_label = "WIN" if run.won else "LOSS"
    result_color = WIN_COLOR if run.won else LOSS_COLOR

    relic_imgs = []
    for relic_id in run.ancient_relics:
        uri = relic_icon_uri(relic_id, character=run.character)
        if not uri:
            continue
        label = relic_id.removeprefix("RELIC.").replace("_", " ").title()
        relic_imgs.append(
            f'<span class="relic-tip" data-tooltip="{label}">'
            f'<img src="{uri}" class="rr-relic-icon" alt="{label}"></span>'
        )
    relics_html = (
        f'<span class="rr-sep">|</span><div class="rr-relics">{"".join(relic_imgs)}</div>'
        if relic_imgs else ""
    )

    card_html = (
        f'<div class="run-row {result_class}">'
        f'<div class="rr-result" style="color:{result_color}">{result_label}</div>'
        f'<div class="rr-char" style="color:{char_color}">{_rr_char_icon(run.character)}{run.character}</div>'
        f'<div class="rr-meta">'
        f'<span>A{run.ascension}</span>'
        f'<span class="rr-sep">|</span>'
        f'<small>{run.act1_variant}</small>'
        f'<span class="rr-sep">|</span>'
        f'<small><span style="display:inline-block;min-width:4.5em">Floor {run.final_floor}</span>{"👑" if run.won else "💀"}</small>'
        f'<span class="rr-sep">|</span>'
        f'<small>{run.final_deck_size} card deck</small>'
        f'{relics_html}'
        f'</div>'
        f'<div class="rr-date">{run.date}</div>'
        f'</div>'
    )

    cols = st.columns([10, 1])
    with cols[0]:
        st.markdown(card_html, unsafe_allow_html=True)
    with cols[1]:
        if st.button("→", key=f"view_{run.run_id}", use_container_width=True):
            show_run_detail(run.run_id)
