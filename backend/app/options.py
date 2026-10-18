"""Voice-design options. Values come from OmniVoice's docs/voice-design.md.
Within a category only one value may be chosen; categories combine freely."""
from typing import Dict, Optional, Tuple

MIN_SPEED, MAX_SPEED = 0.5, 2.0
MIN_STEPS, MAX_STEPS = 8, 64

DESIGN_OPTIONS: Dict[str, Tuple[str, ...]] = {
    "gender": ("male", "female"),
    "age": ("child", "teenager", "young adult", "middle-aged", "elderly"),
    "pitch": ("very low pitch", "low pitch", "moderate pitch", "high pitch", "very high pitch"),
    "style": ("whisper",),
    # English accents only take effect when the text is English.
    "accent": ("american accent", "british accent", "australian accent", "canadian accent",
               "indian accent", "chinese accent", "korean accent", "japanese accent",
               "portuguese accent", "russian accent"),
}
_ORDER = ("gender", "age", "pitch", "style", "accent")


def build_instruct(values: Dict[str, Optional[str]]) -> Optional[str]:
    """Validate against the allow-list and build the comma-separated `instruct`
    string. Empty / 'auto' values are skipped. Returns None if nothing chosen."""
    extra = set(values) - set(_ORDER)
    if extra:
        raise ValueError("Unknown design option")
    parts = []
    for key in _ORDER:
        raw = values.get(key)
        if raw is None:
            continue
        value = raw.strip().lower()
        if value in ("", "auto"):
            continue
        if value not in DESIGN_OPTIONS[key]:
            raise ValueError(f"Unsupported {key} value")
        parts.append(value)
    return ", ".join(parts) or None
