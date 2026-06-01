"""Parse a metric fastener size into (diameter, pitch, length).

Handles the catalog `maatvoering` forms and the size group at the end of a query:
  M-33X75            -> dia 33, length 75
  MF-12X1,5X16       -> dia 12, pitch 1.5, length 16   (fine thread)
  MLF-24X1,50        -> dia 24, pitch 1.5
  MF-58X2            -> dia 58, pitch 2                 (fine, single trailing = pitch)
  M-5X14_flZnZW      -> dia 5, length 14               (trailing _… ignored)
  M2x3 / M-2X3       -> dia 2, length 3
  M5x30              -> dia 5, length 30
  M20                -> dia 20

Rules for the numbers after the diameter:
  - 2 trailing numbers  -> (pitch, length)            e.g. 12 x 1,5 x 16
  - 1 trailing number   -> pitch if fine-thread marker (F) or the number is decimal,
                           otherwise length            e.g. MF-58X2 -> pitch; M5X30 -> length
  - 0 trailing numbers  -> diameter only
"""
import re
from typing import NamedTuple, Optional

# M, optional L/F markers, separator, diameter, then 0-2 "x <num>" groups.
_SIZE = re.compile(
    r"\bM([LF]*)[\s-]?(\d+(?:[.,]\d+)?)((?:\s*[xX]\s*\d+(?:[.,]\d+)?){0,2})",
)
_NUM = re.compile(r"\d+(?:[.,]\d+)?")


class Size(NamedTuple):
    dia: Optional[float]
    pitch: Optional[float]
    length: Optional[float]

    def is_empty(self) -> bool:
        return self.dia is None


def _f(s: str) -> float:
    return float(s.replace(",", "."))


def parse_size(text: str) -> Size:
    """Return the richest size match in text (prefers the one with most numbers,
    ties broken by later position — the size usually trails a query)."""
    best = None
    best_score = -1
    for m in _SIZE.finditer((text or "").upper()):
        tail_nums = _NUM.findall(m.group(3))
        score = len(tail_nums)
        if score >= best_score:  # >= so later matches win ties
            best_score = score
            best = (m.group(1), _f(m.group(2)), tail_nums)
    if best is None:
        return Size(None, None, None)

    markers, dia, tail = best
    fine = "F" in markers
    pitch = length = None
    if len(tail) == 2:
        pitch, length = _f(tail[0]), _f(tail[1])
    elif len(tail) == 1:
        n = _f(tail[0])
        if fine or "," in tail[0] or "." in tail[0]:
            pitch = n
        else:
            length = n
    return Size(dia, pitch, length)
