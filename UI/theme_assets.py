"""Theme-aware versions of shared static UI artwork."""
from pathlib import Path
from Utils.gui_utils import Colors


def themed_empty_state_svg(path: str, *, transparent_background: bool = False) -> bytes:
    """Map the original SVG palette to the current theme without changing geometry."""
    svg = Path(path).read_text(encoding="utf-8")
    if transparent_background:
        svg = svg.replace('fill="#0F172A"', 'fill="none"', 1)
    palette = {
        "#0F172A": Colors.BG_DARK,
        "#111827": Colors.BG_CARD,
        "#334155": Colors.BG_LIGHT,
        "#1F2937": Colors.BG_MEDIUM,
        "#0B1220": Colors.BG_DARK,
        "#22C55E": Colors.PRIMARY,
        "#94A3B8": Colors.TEXT_LIGHT,
    }
    import re
    return re.sub(r"#[0-9A-Fa-f]{6}", lambda match: palette.get(match[0].upper(), match[0]), svg).encode("utf-8")
