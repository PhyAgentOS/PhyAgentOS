"""Morandi-derived color themes for the TUI."""

from textual.theme import Theme

THEMES: dict[str, Theme] = {
    "morandi": Theme(
        name="morandi",
        primary="#5c7385",
        secondary="#3f5666",
        accent="#6b8ca8",
        foreground="#2d3a45",
        background="#f6f4ef",
        surface="#fcfaf5",
        panel="#efebe2",
        boost="#e6e1d6",
        success="#7ba88a",
        warning="#c9a96a",
        error="#b96a72",
        dark=False,
    ),
    "morandi-dark": Theme(
        name="morandi-dark",
        primary="#8a9dad",
        secondary="#5c7385",
        accent="#6b8ca8",
        foreground="#e6e1d6",
        background="#1f2a33",
        surface="#26343f",
        panel="#2d3a45",
        boost="#3a4a57",
        success="#7ba88a",
        warning="#c9a96a",
        error="#c0717a",
        dark=True,
    ),
    "morandi-sage": Theme(
        name="morandi-sage",
        primary="#6b8264",
        secondary="#4a5d45",
        accent="#7ba88a",
        foreground="#33402f",
        background="#f4f5ef",
        surface="#fbfcf6",
        panel="#eaecdf",
        boost="#dde0cf",
        success="#5f9a6e",
        warning="#c9a96a",
        error="#b96a72",
        dark=False,
    ),
    "morandi-rose": Theme(
        name="morandi-rose",
        primary="#a97a82",
        secondary="#7d565e",
        accent="#b98d94",
        foreground="#453237",
        background="#f7f2f1",
        surface="#fdf9f8",
        panel="#f1e6e4",
        boost="#e6d6d3",
        success="#7ba88a",
        warning="#c9a96a",
        error="#b0515c",
        dark=False,
    ),
}

THEME_LABELS: dict[str, str] = {
    "morandi": "Morandi Cream",
    "morandi-dark": "Morandi Dark",
    "morandi-sage": "Morandi Sage",
    "morandi-rose": "Morandi Rose",
}

DEFAULT_THEME = "morandi"


def get_theme_name(name: str | None) -> str:
    """Return a valid theme name, falling back to the default."""
    if name and name in THEMES:
        return name
    return DEFAULT_THEME
