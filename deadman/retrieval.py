"""BM25 keyword search over a figure's passages.

Plain keyword search works well here because the script planner writes search
terms in the figure's own vocabulary (e.g. "joint stock company", "monopoly")
rather than the modern words used in the host's question.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from .sources import Passage

_WORD = re.compile(r"[a-z]+")

STOP_WORDS = frozenset("""
a about above after again against all also am an and any are as at be because been before
being below between both but by can could did do does doing down during each few for from
further had has have having he her here hers herself him himself his how i if in into is it
its itself just me more most my myself no nor not now of off on once only or other ought our
ours ourselves out over own same shall she should so some such than that the their theirs
them themselves then there these they this those through thus to too under until up upon very
was we were what when where which while who whom why will with would yet you your yours
""".split())

# Map modern spellings onto 18th-century/British ones. Applied to passages and
# queries alike, so either spelling matches.
SPELLINGS = {
    "labor": "labour", "shown": "shewn", "show": "shew", "favor": "favour",
    "behavior": "behaviour", "neighbor": "neighbour", "honor": "honour",
    "economy": "oeconomy",
}


def _stem(word: str) -> str:
    for suffix in ("ies", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return word


def tokenize(text: str) -> list[str]:
    tokens = []
    for word in _WORD.findall(text.lower()):
        if word in STOP_WORDS or len(word) < 2:
            continue
        tokens.append(_stem(SPELLINGS.get(word, word)))
    return tokens


class BM25Index:
    def __init__(self, passages: list[Passage], k1: float = 1.5, b: float = 0.75):
        self.passages = passages
        self.k1, self.b = k1, b
        self._tf = [Counter(tokenize(p.text)) for p in passages]
        self._len = [sum(tf.values()) for tf in self._tf]
        self._avg_len = sum(self._len) / max(len(self._len), 1)
        df: Counter[str] = Counter()
        for tf in self._tf:
            df.update(tf.keys())
        n = len(passages)
        self._idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    def search(self, query: str, k: int = 5) -> list[tuple[Passage, float]]:
        terms = set(tokenize(query))
        scored = []
        for i, tf in enumerate(self._tf):
            score = 0.0
            norm = self.k1 * (1 - self.b + self.b * self._len[i] / self._avg_len)
            for t in terms:
                if f := tf.get(t):
                    score += self._idf[t] * f * (self.k1 + 1) / (f + norm)
            if score > 0:
                scored.append((score, i))
        scored.sort(reverse=True)
        return [(self.passages[i], s) for s, i in scored[:k]]
