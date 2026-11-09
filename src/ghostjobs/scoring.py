"""Combine signals into a 0-100 ghost score.

Starts from hand-picked weights. Once you've labelled real outcomes, `ghostjobs calibrate
--apply` writes learned weights to weights.json, which are used instead.
"""

import json
from pathlib import Path

from ghostjobs.config import get_settings
from ghostjobs.signals import Signal

DEFAULT_WEIGHTS: dict[str, float] = {
    "age": 0.20,
    "reposts": 0.25,
    "evergreen": 0.20,
    "no_salary": 0.10,
    "vague": 0.10,
    "volume": 0.10,
    "applications": 0.05,
}


def load_weights(path: str | None = None) -> dict[str, float]:
    p = Path(path or get_settings().weights_path)
    if p.is_file():
        try:
            learned = json.loads(p.read_text())
            return {k: float(learned.get(k, v)) for k, v in DEFAULT_WEIGHTS.items()}
        except (ValueError, TypeError):
            pass  # broken file -> fall back to defaults
    return dict(DEFAULT_WEIGHTS)


def score(
    signals: list[Signal], weights: dict[str, float] | None = None
) -> tuple[float, list[str]]:
    w = weights if weights is not None else DEFAULT_WEIGHTS
    total_weight = sum(w.get(s.name, 0) for s in signals) or 1
    raw = sum(w.get(s.name, 0) * s.value for s in signals) / total_weight
    reasons = [
        s.reason for s in sorted(signals, key=lambda s: -s.value) if s.value > 0 and s.reason
    ]
    return round(raw * 100, 1), reasons


def verdict(score_value: float) -> str:
    if score_value >= 55:
        return "Likely ghost"
    if score_value >= 30:
        return "Suspicious"
    return "Looks genuine"
