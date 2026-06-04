import base64
from pathlib import Path
from typing import Optional

import streamlit as st

CHARACTER_ICON_NAMES = {
    "Ironclad":    "spire2_yc_clad",
    "Silent":      "spire2_yc_silent",
    "Defect":      "spire2_yc_defect",
    "Necrobinder": "spire2_yc_necro",
    "Regent":      "spire2_yc_regent",
}

# Suffix used by yummy_cookie_<suffix>.webp per character.
# Necrobinder is shortened to "necro"; others use lowercase character name.
YUMMY_COOKIE_CHAR_SUFFIX = {
    "Ironclad":    "ironclad",
    "Silent":      "silent",
    "Defect":      "defect",
    "Necrobinder": "necro",
    "Regent":      "regent",
}

_STATIC_DIR = Path(__file__).parent / "static"


def _file_to_data_uri(path: Path) -> str:
    if not path.exists():
        return ""
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/webp;base64,{b64}"


@st.cache_data
def character_icon_uri(character: str) -> str:
    """Return a base64-encoded data URI for the character's .webp icon, or '' if missing."""
    name = CHARACTER_ICON_NAMES.get(character)
    if not name:
        return ""
    return _file_to_data_uri(_STATIC_DIR / "characters" / f"{name}.webp")


@st.cache_data
def relic_icon_uri(relic_id: str, character: Optional[str] = None) -> str:
    """Return a base64-encoded data URI for a relic's .webp.

    For Yummy Cookie, pass `character` to get the per-character variant.
    """
    name = relic_id.removeprefix("RELIC.").lower()
    if name == "yummy_cookie" and character:
        suffix = YUMMY_COOKIE_CHAR_SUFFIX.get(character, character.lower())
        name = f"yummy_cookie_{suffix}"
    return _file_to_data_uri(_STATIC_DIR / "relics" / f"{name}.webp")


@st.cache_data
def potion_icon_uri(potion_id: str) -> str:
    """Return a base64-encoded data URI for a potion's .webp."""
    name = potion_id.removeprefix("POTION.").lower()
    return _file_to_data_uri(_STATIC_DIR / "potions" / f"{name}.webp")
