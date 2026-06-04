import streamlit as st
import plotly.express as px
import pandas as pd
import run_parser
import elo as elo_engine
import war as war_engine
from assets import character_icon_uri
from save_panel import render_save_panel

st.set_page_config(page_title="Spire2ELO", page_icon="⚔️", layout="wide")


def _source_key() -> str:
    return st.session_state.get("uploaded_hash", "local")


def _get_events_data() -> list:
    runs = st.session_state.get("uploaded_runs_by_id")
    if runs:
        return run_parser.events_from_runs_by_id(runs)
    return run_parser.load_all_events()


# ── Sidebar uploader (shared helper — renders before everything else needs the data) ──
render_save_panel()


_EMPTY_MERGED = pd.DataFrame(columns=[
    "card", "character", "act", "elo", "times_offered", "times_picked", "pick_rate",
])
_EMPTY_HISTORY = pd.DataFrame(columns=["run_index", "run_id", "card", "character", "act", "elo"])
_EMPTY_WAR = pd.DataFrame(columns=[
    "card", "character", "act", "picks", "wins", "win_rate", "baseline_wr", "war",
])


@st.cache_data
def compute(act1_variant_filter: str, source_key: str):
    events = _get_events_data()
    if act1_variant_filter != "All":
        events = [e for e in events
                  if e["act"] != "Act 1" or e.get("act1_variant") == act1_variant_filter]
    if not events:
        return events, _EMPTY_MERGED.copy(), _EMPTY_HISTORY.copy(), _EMPTY_WAR.copy()
    ratings = elo_engine.compute_ratings(events)
    ratings_df = elo_engine.ratings_to_df(ratings)
    counts_df = elo_engine.match_counts(events)
    merged = ratings_df.merge(counts_df, on=["card", "character", "act"], how="left")
    history_df = elo_engine.compute_ratings_history(events)
    war_df = war_engine.wins_above_replacement(events)
    return events, merged, history_df, war_df


@st.dialog("ELO History", width="large")
def show_elo_history(card: str, char: str, act: str, skip_elo: float, skip_label: str):
    card_history = history_df[
        (history_df["card"] == card) &
        (history_df["character"] == char) &
        (history_df["act"] == act)
    ].sort_values("run_index")

    st.caption(f"{char} · {act} · {len(card_history)} runs")

    if card_history.empty:
        st.warning("No history data found for this card.")
        return

    fig = px.line(
        card_history,
        x="run_index", y="elo",
        markers=True,
        height=360,
        labels={"run_index": "Run", "elo": "ELO"},
    )
    fig.add_hline(
        y=skip_elo,
        line_dash="dash",
        line_color="gray",
        annotation_text=f"{skip_label} ({skip_elo})",
        annotation_position="top right",
    )
    fig.add_hline(y=elo_engine.INITIAL_RATING, line_dash="dot", line_color="lightgray",
                  annotation_text="baseline", annotation_position="bottom right")
    fig.update_layout(margin=dict(t=10, b=40))
    st.plotly_chart(fig, use_container_width=True)


CHARACTER_COLORS = {
    "Ironclad": "color: #e05555",
    "Regent": "color: #e07b30",
    "Necrobinder": "color: #b39ddb",
    "Silent": "color: #4caf50",
    "Defect": "color: #64b5f6",
}


def _style_global(df_in):
    char_color = df_in["Character"].map(lambda c: CHARACTER_COLORS.get(c, ""))
    is_skip = df_in["Card"].str.contains("_SKIP_ACT")
    color = is_skip.map(lambda v: "color: #aaaaaa" if v else "").where(is_skip, char_color)
    return pd.DataFrame({"Card": color, "Character": color, "ELO": color})


# ── Sidebar ────────────────────────────────────────────────────────────────────
st.sidebar.title("spire elo")

all_acts = ["Act 1", "Act 2", "Act 3"]
selected_act = st.sidebar.selectbox("Act", all_acts)

act1_variant = "All"
if selected_act == "Act 1":
    act1_variant = st.sidebar.radio("Act 1 Variant", ["All", "Overgrowth", "Underdocks"])

events, df, history_df, war_df = compute(act1_variant, _source_key())

if not events:
    st.title("Spire2ELO")
    st.info(
        "👋 No run data loaded yet. Upload your zipped Slay the Spire 2 `saves/` "
        "folder in the sidebar."
    )
    st.caption(
        "Your `saves/` folder lives at "
        "`~/Library/Application Support/SlayTheSpire2/steam/<id>/profile<n>/saves` on macOS, "
        r"or `C:\Users\<user>\AppData\Roaming\SlayTheSpire2\steam` on Windows. "
        "Zip the folder (containing `progress.save` and `history/`) and drop it into the uploader."
    )
    st.stop()

all_characters = sorted(df[df["card"] != "SKIP"]["character"].unique())
selected_char = st.sidebar.selectbox("Character", all_characters)

min_offered = st.sidebar.slider("Min times offered", 1, 30, 5)

# ── Filter ─────────────────────────────────────────────────────────────────────
view = df[
    (df["character"] == selected_char) &
    (df["act"] == selected_act) &
    (df["times_offered"] >= min_offered)
].copy()

this_skip_id = elo_engine.skip_id(selected_char, selected_act)
cards_only = view[view["card"] != this_skip_id].sort_values("elo", ascending=False).reset_index(drop=True)
skip_row = df[df["card"] == this_skip_id]
skip_elo = round(skip_row["elo"].values[0], 1) if not skip_row.empty else elo_engine.INITIAL_RATING

# ── Header ─────────────────────────────────────────────────────────────────────
char_hex = CHARACTER_COLORS.get(selected_char, "color: inherit").replace("color: ", "")
total_runs = len({e["run_id"] for e in events if e["character"] == selected_char})
icon_uri = character_icon_uri(selected_char)
icon_html = (
    f'<img src="{icon_uri}" style="height:1.2em; vertical-align:-0.2em; margin:0 0.3em;" alt="">'
    if icon_uri else ""
)
st.markdown(
    f'<h1>Card ELO — <span style="color:{char_hex}">{selected_char}</span>{icon_html} · {selected_act}</h1>'
    f'<p style="margin-top:-0.5rem;opacity:0.7">Data collected over {total_runs} runs</p>',
    unsafe_allow_html=True,
)

col1, col2, col3 = st.columns(3)
col1.metric("Cards ranked", len(cards_only))
col2.metric("Total choice events", len([e for e in events
    if e["character"] == selected_char and e["act"] == selected_act]))
act_num = selected_act.split()[-1]
col3.markdown(
    f"""
    <div style="line-height:1.4">
        <div style="font-size:0.875rem">
            <span style="color:{char_hex}">{selected_char.upper()}</span> SKIP ACT{act_num} ELO
        </div>
        <div style="font-size:2rem;font-weight:700;letter-spacing:-0.01em">{skip_elo}</div>
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown("---")

# ── ELO leaderboard chart ──────────────────────────────────────────────────────
st.markdown(f'<h3 id="elo-leaderboard" style="color:{char_hex}">ELO Leaderboard</h3>', unsafe_allow_html=True)
st.caption("Click a bar to view that card's ELO history over time.")

n = st.slider("Show top N cards", 10, min(60, len(cards_only)), min(20, len(cards_only)))
top = cards_only.head(n)

fig = px.bar(
    top,
    x="card", y="elo",
    color="elo",
    color_continuous_scale="RdYlGn",
    range_color=[800, 1200],
    height=420,
    text="elo",
    hover_data={"times_offered": True, "times_picked": True, "pick_rate": True},
)
fig.add_hline(
    y=skip_elo,
    line_dash="dash",
    line_color="gray",
    annotation_text=f"{this_skip_id} ({skip_elo})",
    annotation_position="top right",
)
fig.update_traces(texttemplate="%{text:.0f}", textposition="outside")
fig.update_layout(
    xaxis_tickangle=-40,
    margin=dict(t=20, b=100),
    coloraxis_showscale=False,
    xaxis_title=None,
)

event = st.plotly_chart(fig, on_select="rerun", selection_mode="points", use_container_width=True)
if event.selection.points:
    clicked_card = event.selection.points[0]["x"]
    show_elo_history(clicked_card, selected_char, selected_act, skip_elo, this_skip_id)

# ── Below SKIP ─────────────────────────────────────────────────────────────────
st.markdown("---")
below_skip = cards_only[cards_only["elo"] < skip_elo]
st.markdown(f'<h3 style="color:{char_hex}">Below SKIP threshold — {len(below_skip)} cards</h3>', unsafe_allow_html=True)
st.caption("These cards are losing ELO to skipping. They were consistently passed over even when offered.")

if below_skip.empty:
    st.info("No cards fall below the SKIP threshold for the current filters.")
else:
    fig2 = px.bar(
        below_skip.tail(20).sort_values("elo"),
        x="card", y="elo",
        color="elo",
        color_continuous_scale="RdYlGn",
        range_color=[800, 1200],
        height=320,
        text="elo",
    )
    fig2.add_hline(y=skip_elo, line_dash="dash", line_color="gray")
    fig2.update_traces(texttemplate="%{text:.0f}", textposition="outside")
    fig2.update_layout(xaxis_tickangle=-40, margin=dict(t=10, b=100),
                       coloraxis_showscale=False, xaxis_title=None)

    event2 = st.plotly_chart(fig2, on_select="rerun", selection_mode="points", use_container_width=True)
    if event2.selection.points:
        clicked_card = event2.selection.points[0]["x"]
        show_elo_history(clicked_card, selected_char, selected_act, skip_elo, this_skip_id)

# ── Alternate Act ELO Variance ─────────────────────────────────────────────────
if selected_act == "Act 1":
    st.markdown("---")
    st.markdown(f'<h3 style="color:{char_hex}">Alternate Act ELO Variance</h3>', unsafe_allow_html=True)
    st.caption("ELO delta between Overgrowth and Underdocks runs (Overgrowth − Underdocks). Positive = favours Overgrowth, negative = favours Underdocks.")

    _, df_og, _, _ = compute("Overgrowth", _source_key())
    _, df_ud, _, _ = compute("Underdocks", _source_key())

    OVERGROWTH_COLOR = "#4a8c5c"
    UNDERDOCKS_COLOR = "#7baabf"

    def _variant_act1(vdf):
        return vdf[
            (vdf["character"] == selected_char) &
            (vdf["act"] == "Act 1") &
            (~vdf["card"].str.contains("_SKIP_ACT")) &
            (vdf["times_offered"] >= min_offered)
        ][["card", "elo"]]

    og_cards = _variant_act1(df_og).rename(columns={"elo": "Overgrowth"})
    ud_cards = _variant_act1(df_ud).rename(columns={"elo": "Underdocks"})

    variance_df = og_cards.merge(ud_cards, on="card", how="inner")
    variance_df["delta"] = (variance_df["Overgrowth"] - variance_df["Underdocks"]).round(1)
    variance_df["abs_delta"] = variance_df["delta"].abs()
    variance_df["favors"] = (variance_df["delta"] >= 0).map({True: "Overgrowth", False: "Underdocks"})

    col_a, col_b = st.columns([2, 1])
    with col_a:
        order_by = st.radio(
            "Show cards", ["Greatest Divergence", "Favoring Overgrowth", "Favoring Underdocks"],
            horizontal=True, key="variance_order",
        )
    with col_b:
        max_avail = max(1, len(variance_df))
        variance_n = st.slider(
            "Show N", 5, min(40, max_avail), min(15, max_avail), key="variance_n",
        )

    if order_by == "Favoring Overgrowth":
        plot_df = variance_df[variance_df["delta"] > 0].sort_values("delta", ascending=False).head(variance_n)
        plot_df = plot_df.sort_values("delta", ascending=True)
    elif order_by == "Favoring Underdocks":
        plot_df = variance_df[variance_df["delta"] < 0].sort_values("delta", ascending=True).head(variance_n)
        plot_df = plot_df.sort_values("delta", ascending=False)
    else:
        plot_df = variance_df.sort_values("abs_delta", ascending=False).head(variance_n)
        plot_df = plot_df.sort_values("abs_delta", ascending=True)

    if plot_df.empty:
        st.info("No cards meet the current filter criteria for this selection.")
    else:
        fig_var = px.bar(
            plot_df,
            x="delta", y="card",
            orientation="h",
            color="favors",
            color_discrete_map={"Overgrowth": OVERGROWTH_COLOR, "Underdocks": UNDERDOCKS_COLOR},
            text="delta",
            height=max(420, len(plot_df) * 22),
            labels={"delta": "ELO Delta (Overgrowth − Underdocks)", "card": "", "favors": "Favors"},
            hover_data={"Overgrowth": True, "Underdocks": True, "abs_delta": False, "favors": False},
        )
        fig_var.add_vline(x=0, line_color="gray", line_width=1)
        fig_var.update_traces(texttemplate="%{text:+.1f}", textposition="outside")
        fig_var.update_layout(
            margin=dict(t=20, b=40, l=10),
            xaxis_title="ELO Delta (Overgrowth − Underdocks)",
            legend=dict(orientation="h", y=1.02, x=0),
        )
        st.plotly_chart(fig_var, use_container_width=True)

# ── Wins Above Replacement ─────────────────────────────────────────────────────
st.markdown("---")
st.markdown(f'<h3 style="color:{char_hex}">Wins Above Replacement</h3>', unsafe_allow_html=True)
st.caption(
    "WAR = wins when picked − (picks × character baseline win rate). "
    "Positive WAR = card outperforms an average pick for this character."
)

war_view = war_df[
    (war_df["character"] == selected_char) &
    (war_df["act"] == selected_act) &
    (war_df["picks"] >= max(1, min_offered // 2))
].copy()

if war_view.empty:
    st.info("No cards meet the current filter criteria for WAR.")
else:
    war_view = war_view.sort_values("war", ascending=False).reset_index(drop=True)
    war_n = st.slider(
        "Show top N by WAR",
        5, min(50, len(war_view)), min(20, len(war_view)),
        key="war_n",
    )
    top_war = war_view.head(war_n)

    baseline_wr = war_view["baseline_wr"].iloc[0]

    fig_war = px.bar(
        top_war,
        x="card", y="war",
        color="war",
        color_continuous_scale="RdYlGn",
        range_color=[-top_war["war"].abs().max(), top_war["war"].abs().max()],
        height=420,
        text="war",
        hover_data={"picks": True, "wins": True, "win_rate": ":.1f", "baseline_wr": ":.1f"},
    )
    fig_war.add_hline(y=0, line_color="gray", line_width=1)
    fig_war.update_traces(texttemplate="%{text:+.1f}", textposition="outside")
    fig_war.update_layout(
        xaxis_tickangle=-40,
        margin=dict(t=20, b=100),
        coloraxis_showscale=False,
        xaxis_title=None,
        yaxis_title="WAR",
    )
    st.plotly_chart(fig_war, use_container_width=True)

    st.caption(f"Character baseline win rate: **{baseline_wr}%**")

    st.markdown("##### ELO vs WAR")
    st.caption(
        ""
    )
    elo_view = df[
        (df["character"] == selected_char) &
        (df["act"] == selected_act) &
        (~df["card"].str.contains("_SKIP_ACT"))
    ][["card", "elo"]]
    scatter_df = war_view.merge(elo_view, on="card", how="inner")
    if not scatter_df.empty:
        fig_sc = px.scatter(
            scatter_df,
            x="war", y="elo",
            hover_name="card",
            size="picks",
            color="win_rate",
            color_continuous_scale="RdYlGn",
            range_color=[0, 100],
            height=440,
            labels={"war": "WAR", "elo": "ELO", "win_rate": "Win Rate %"},
        )
        fig_sc.add_vline(x=0, line_dash="dash", line_color="gray")
        fig_sc.add_hline(y=elo_engine.INITIAL_RATING, line_dash="dash", line_color="gray")
        fig_sc.update_traces(textposition="top center")
        fig_sc.update_layout(margin=dict(t=10, b=40))
        st.plotly_chart(fig_sc, use_container_width=True)

# ── Full table ─────────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown(f'<h3 id="full-rankings-table" style="color:{char_hex}">{selected_char} Rankings Table</h3>', unsafe_allow_html=True)
st.dataframe(
    cards_only[["card", "elo", "times_offered", "times_picked", "pick_rate"]].rename(columns={
        "card": "Card", "elo": "ELO", "times_offered": "Offered",
        "times_picked": "Picked", "pick_rate": "Pick Rate %"
    }),
    column_config={"ELO": st.column_config.NumberColumn(format="%.1f")},
    use_container_width=True,
    height=400,
)

# ── Global rankings ────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown('<h3 id="all-cards-global-rankings">All Cards — Global Rankings</h3>', unsafe_allow_html=True)

tab1, tab2, tab3 = st.tabs(["Act 1", "Act 2", "Act 3"])

for tab, act_label in [(tab1, "Act 1"), (tab2, "Act 2"), (tab3, "Act 3")]:
    with tab:
        act_cards = (
            df[df["act"] == act_label]
            .sort_values("elo", ascending=False)
            [["card", "character", "elo"]]
            .rename(columns={"card": "Card", "character": "Character", "elo": "ELO"})
            .reset_index(drop=True)
        )
        st.dataframe(act_cards.style.apply(_style_global, axis=None).format({"ELO": "{:.1f}"}), use_container_width=True, height=500)

# ── Global WAR rankings ────────────────────────────────────────────────────────
st.markdown("---")
st.markdown('<h3 id="all-cards-global-war">All Cards — Global WAR Rankings</h3>', unsafe_allow_html=True)
st.caption(
    "WAR is character-relative (compared against that character's baseline win rate), "
    "so rows remain separated per character even when sorted globally."
)

war_tab1, war_tab2, war_tab3 = st.tabs(["Act 1", "Act 2", "Act 3"])


def _style_war_global(df_in):
    char_color = df_in["Character"].map(lambda c: CHARACTER_COLORS.get(c, ""))
    return pd.DataFrame({
        "Card": char_color,
        "Character": char_color,
        "Picks": char_color,
        "Wins": char_color,
        "Win Rate %": char_color,
        "Baseline %": char_color,
        "WAR": char_color,
    })


for tab, act_label in [(war_tab1, "Act 1"), (war_tab2, "Act 2"), (war_tab3, "Act 3")]:
    with tab:
        act_war = (
            war_df[war_df["act"] == act_label]
            .sort_values("war", ascending=False)
            [["card", "character", "picks", "wins", "win_rate", "baseline_wr", "war"]]
            .rename(columns={
                "card": "Card", "character": "Character",
                "picks": "Picks", "wins": "Wins",
                "win_rate": "Win Rate %", "baseline_wr": "Baseline %",
                "war": "WAR",
            })
            .reset_index(drop=True)
        )
        st.dataframe(
            act_war.style.apply(_style_war_global, axis=None).format({
                "Win Rate %": "{:.1f}",
                "Baseline %": "{:.1f}",
                "WAR": "{:+.2f}",
            }),
            use_container_width=True, height=500,
        )

