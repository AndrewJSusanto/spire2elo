import streamlit as st
import plotly.express as px
import pandas as pd
import run_parser
import elo as elo_engine

st.set_page_config(page_title="Spire2ELO", page_icon="⚔️", layout="wide")


@st.cache_data
def load_raw_events():
    return run_parser.load_all_events()


@st.cache_data
def compute(act1_variant_filter: str = "All"):
    events = load_raw_events()
    if act1_variant_filter != "All":
        events = [e for e in events
                  if e["act"] != "Act 1" or e.get("act1_variant") == act1_variant_filter]
    ratings = elo_engine.compute_ratings(events)
    ratings_df = elo_engine.ratings_to_df(ratings)
    counts_df = elo_engine.match_counts(events)
    merged = ratings_df.merge(counts_df, on=["card", "character", "act"], how="left")
    history_df = elo_engine.compute_ratings_history(events)
    return events, merged, history_df


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

events, df, history_df = compute(act1_variant)

all_characters = sorted(df[df["card"] != "SKIP"]["character"].unique())
selected_char = st.sidebar.selectbox("Character", all_characters)

min_offered = st.sidebar.slider("Min times offered", 1, 30, 5)

st.sidebar.markdown("---")
nav_items = [
    ("↑ Top", "top"),
    ("Elo Leaderboard", "elo-leaderboard"),
    ("Cards Below SKIP Threshold", "below-skip-threshold"),
]
if selected_act == "Act 1":
    nav_items.append(("Alternate Act ELO Variance", "alt-act-variance"))
nav_items += [
    ("Character Rankings", "full-rankings-table"),
    ("All Cards — Global", "all-cards-global-rankings"),
]
for label, anchor in nav_items:
    if st.sidebar.button(label, use_container_width=True, key=f"nav_{anchor}"):
        st.session_state["_scroll_to"] = anchor

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
st.markdown('<div id="top"></div>', unsafe_allow_html=True)
char_hex = CHARACTER_COLORS.get(selected_char, "color: inherit").replace("color: ", "")
st.markdown(
    f'<h1>Card ELO — <span style="color:{char_hex}">{selected_char}</span> · {selected_act}</h1>',
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
st.markdown('<div id="below-skip-threshold"></div>', unsafe_allow_html=True)
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
    st.markdown('<div id="alt-act-variance"></div>', unsafe_allow_html=True)
    st.markdown(f'<h3 style="color:{char_hex}">Alternate Act ELO Variance</h3>', unsafe_allow_html=True)
    st.caption("ELO delta between Overgrowth and Underdocks runs (Overgrowth − Underdocks). Positive = favours Overgrowth, negative = favours Underdocks.")

    _, df_og, _ = compute("Overgrowth")
    _, df_ud, _ = compute("Underdocks")

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

    order_by = st.radio(
        "Show cards", ["Greatest Divergence", "Favoring Overgrowth", "Favoring Underdocks"],
        horizontal=True, key="variance_order",
    )

    if order_by == "Favoring Overgrowth":
        plot_df = variance_df[variance_df["delta"] > 0].sort_values("delta", ascending=True)
    elif order_by == "Favoring Underdocks":
        plot_df = variance_df[variance_df["delta"] < 0].sort_values("delta", ascending=False)
    else:
        plot_df = variance_df.sort_values("abs_delta", ascending=True)

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

# ── Full table ─────────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown(f'<h3 id="full-rankings-table" style="color:{char_hex}">Full Rankings Table</h3>', unsafe_allow_html=True)
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

# ── Scroll via JS ───────────────────────────────────────────────────────────────
if "_scroll_to" in st.session_state:
    target = st.session_state.pop("_scroll_to")
    st.components.v1.html(
        f"""
        <script>
            var el = window.parent.document.getElementById('{target}');
            if (el) el.scrollIntoView({{behavior: 'smooth', block: 'start'}});
        </script>
        """,
        height=0,
    )
