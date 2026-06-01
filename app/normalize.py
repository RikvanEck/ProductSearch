"""Text normalization used for keyword/trigram recall.

Customer queries and the catalog describe the SAME product differently:
DIN912 / "DIN 912" vs the catalog's D912; English vs Dutch words; and many size
spellings (M8x40 / M-8X40). We normalize both the query and an indexed
`search_norm` column with this identical function so the discriminating tokens
(norm code + dimensions + strength class) line up as matchable tokens.

Goals:
- Keep norm codes as single strong tokens: DIN/DIN<space>912 -> D912; ISO 4762 -> ISO4762.
- Make size spellings converge: M8x40 / M-8X40 -> "M8 40".
- Drop separators so [-/,.] don't fragment tokens.

The English<->Dutch word gap is left to the vector (embedding) retrieval; keyword
recall leans on the language-neutral norm/size/grade tokens.
"""
import re

# Glue norm prefixes to their number, and map the German DIN -> catalog's D.
_DIN = re.compile(r"\bDIN\s*(\d)")
_NORM_GLUE = re.compile(r"\b(ISO|EN|NEN|ANSI|ASME|UNI|D)\s+(\d)")
_SEP = re.compile(r"[-/,.\(\)\[\]+&|*~:;]")
_X_BETWEEN = re.compile(r"(?<=\d)[X](?=\d)")  # 8X40 -> 8 40 (after upper-casing)
_WS = re.compile(r"\s+")


def normalize_text(s: str) -> str:
    s = (s or "").upper()
    s = _DIN.sub(r"D\1", s)            # DIN 912 / DIN912 -> D912
    s = _NORM_GLUE.sub(r"\1\2", s)     # ISO 4762 -> ISO4762, D 934 -> D934
    s = _SEP.sub(" ", s)               # separators -> space
    s = _X_BETWEEN.sub(" ", s)         # 8X40 -> 8 40
    return _WS.sub(" ", s).strip()
