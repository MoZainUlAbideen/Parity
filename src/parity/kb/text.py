"""Tokenizing for keyword search.

"Captions", "captioned" and "captioning" should all match "caption", so we
stem words (Snowball English stemmer). Very common words are dropped because
they match everything and tell us nothing.
"""

from __future__ import annotations

import re

import snowballstemmer

_stemmer = snowballstemmer.stemmer("english")
_WORD = re.compile(r"[a-z0-9]+")

STOPWORDS = frozenset(
    """a an and are as at be but by can do does for from has have how i if in into is it its
    my no not of on or our so such that the their then there these they this to was we what
    when where which who why will with you your me us than too very should would could""".split()
)


def tokenize(text: str) -> list[str]:
    words = [w for w in _WORD.findall(text.lower()) if w not in STOPWORDS]
    return _stemmer.stemWords(words)
