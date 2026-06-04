import hashlib

import streamlit as st

import run_parser


def render_save_panel() -> None:
    """Sidebar widget for save-data upload.

    Shared across all pages so an uploaded zip persists when navigating between
    them. Previously each page had its own uploader; navigating to a new page
    rendered a fresh (empty) widget instance which then cleared session state.
    """
    with st.sidebar:
        st.markdown("### Save data")
        uploaded = st.file_uploader(
            "Upload your zipped `saves/` folder",
            type=["zip"],
            help=(
                "Zip your Slay the Spire 2 saves folder (containing "
                "`progress.save` and `history/`) and drop it here."
            ),
            key="saves_zip_uploader",
        )
        if uploaded is not None:
            new_hash = hashlib.sha1(uploaded.getvalue()).hexdigest()[:16]
            if st.session_state.get("uploaded_hash") != new_hash:
                with st.spinner("Parsing save data…"):
                    parsed = run_parser.parse_uploaded_zip(uploaded.getvalue())
                st.session_state["uploaded_runs_by_id"] = parsed["runs_by_id"]
                st.session_state["uploaded_progress"] = parsed["progress"]
                st.session_state["uploaded_hash"] = new_hash
                st.rerun()

        if st.session_state.get("uploaded_hash"):
            n_runs = len(st.session_state.get("uploaded_runs_by_id", {}))
            has_prog = "✓" if st.session_state.get("uploaded_progress") else "✗"
            st.caption(f"Uploaded: **{n_runs}** runs · progress.save {has_prog}")
            if st.button("Clear uploaded data", use_container_width=True, key="clear_uploaded_data"):
                for k in ("uploaded_runs_by_id", "uploaded_progress", "uploaded_hash"):
                    st.session_state.pop(k, None)
                st.rerun()
        else:
            st.caption("Using local save data")
            if st.button(
                "↻ Refresh data",
                use_container_width=True,
                help="Reload runs from disk (for new local runs)",
                key="refresh_local_data",
            ):
                st.cache_data.clear()
                st.rerun()
