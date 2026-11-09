"""Learn signal weights from your own labelled outcomes.

Label postings with `ghostjobs label <id> ghosted|responded|rejected`. "ghosted" counts as a
ghost job; "responded" and "rejected" count as real (a rejection means someone read it).

For each signal we compare how strongly it fires on ghost jobs vs real ones. Signals that
separate them well get more weight. With few labels the result is blended towards the
default weights, so a handful of applications can't swing everything.
"""

from dataclasses import dataclass

from ghostjobs.db import Posting
from ghostjobs.scoring import DEFAULT_WEIGHTS
from ghostjobs.signals import SIGNAL_NAMES, compute_signals

MIN_PER_CLASS = 5
PRIOR_STRENGTH = 30  # labels needed before learned weights count as much as the defaults


@dataclass
class CalibrationResult:
    n_ghost: int
    n_real: int
    rows: list[tuple[str, float, float, float, float]]  # name, ghost avg, real avg, old, new
    weights: dict[str, float]
    enough_data: bool


def calibrate(postings: list[Posting]) -> CalibrationResult:
    labelled = [p for p in postings if p.label]
    ghost = [p for p in labelled if p.label == "ghosted"]
    real = [p for p in labelled if p.label in ("responded", "rejected")]
    enough = len(ghost) >= MIN_PER_CLASS and len(real) >= MIN_PER_CLASS
    if not enough:
        return CalibrationResult(len(ghost), len(real), [], dict(DEFAULT_WEIGHTS), False)

    def means(group: list[Posting]) -> dict[str, float]:
        totals = dict.fromkeys(SIGNAL_NAMES, 0.0)
        for p in group:
            for s in compute_signals(p, postings):
                totals[s.name] += s.value
        return {k: v / len(group) for k, v in totals.items()}

    g, r = means(ghost), means(real)
    # Separation: how much more the signal fires on ghosts. Negative = misleading -> 0.
    sep = {k: max(0.0, g[k] - r[k]) for k in SIGNAL_NAMES}
    total = sum(sep.values())
    learned = {k: (v / total if total else DEFAULT_WEIGHTS[k]) for k, v in sep.items()}

    n = len(ghost) + len(real)
    alpha = n / (n + PRIOR_STRENGTH)
    new = {k: round(alpha * learned[k] + (1 - alpha) * DEFAULT_WEIGHTS[k], 3) for k in SIGNAL_NAMES}
    rows = [(k, g[k], r[k], DEFAULT_WEIGHTS[k], new[k]) for k in SIGNAL_NAMES]
    return CalibrationResult(len(ghost), len(real), rows, new, True)
