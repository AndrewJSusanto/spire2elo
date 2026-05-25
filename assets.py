import base64
from pathlib import Path

import streamlit as st

CHARACTER_ICON_NAMES = {
    "Ironclad":    "spire2_yc_clad",
    "Silent":      "spire2_yc_silent",
    "Defect":      "spire2_yc_defect",
    "Necrobinder": "spire2_yc_necro",
    "Regent":      "spire2_yc_regent",
}

_STATIC_DIR = Path(__file__).parent / "static" / "characters"


@st.cache_data
def character_icon_uri(character: str) -> str:
    """Return a base64-encoded data URI for the character's .webp icon, or '' if missing."""
    name = CHARACTER_ICON_NAMES.get(character)
    if not name:
        return ""
    path = _STATIC_DIR / f"{name}.webp"
    if not path.exists():
        return ""
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/webp;base64,{b64}"
