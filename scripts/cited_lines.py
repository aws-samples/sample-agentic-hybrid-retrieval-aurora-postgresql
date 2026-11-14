"""The line of an evidence record that a citation was cited for, as the terminal prints it.

Ask Mosaic and Playground choose the same line in `ui/src/components/ask-mosaic/
quoteLines.ts`; `data/cited_line_cases.json` holds both to one set of cases, and the unit
spellings are the answer check's own (`service.synthesis.UNIT_ALIASES`). A record is stored
as ingested, with `Title:` and `Categories:` headers and `<br />` breaks; neither is quoted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from service.synthesis import UNIT_ALIASES

_HEADER = re.compile(r"^(?:title|categories)\s*:", re.IGNORECASE)
_DESCRIPTION_LABEL = re.compile(r"^description\s*:\s*", re.IGNORECASE)
# A sentence end, then a capital or digit; sellers also run sentences together ("more.A new").
_SENTENCE_END = re.compile(r"(?<=[a-z0-9”\")][.!?])(?:\s+|(?=[A-Z]))(?=[A-Z0-9“\"(])")
_MIN_LINE = 12
_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-Z#])|[;\n]")
_STOPWORDS = frozenset(
    {
        "this",
        "that",
        "with",
        "from",
        "have",
        "has",
        "their",
        "your",
        "they",
        "them",
        "than",
        "then",
        "though",
        "which",
        "while",
        "over",
        "into",
        "also",
        "such",
        "does",
        "doesn",
        "about",
        "here",
        "there",
        "when",
        "what",
        "were",
        "been",
        "being",
        "will",
        "would",
        "could",
        "should",
        "very",
        "reviewer",
        "reviewers",
        "reports",
        "describes",
        "says",
        "lists",
        "listing",
        "specifies",
    }
)
# The answer check's own token: letters, digits, letters. Letters first make it a model
# ID (VG2756), and a bare number (Zone 900) is not a measurement.
_TOKEN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]*\d[\d,]*(?:\.\d+)?[A-Za-z]*")
_RESOLUTION = re.compile(
    r"(?<![A-Za-z0-9])(\d+)\s*[x×]\s*(\d+)(?![A-Za-z0-9])", re.IGNORECASE
)


@dataclass(frozen=True)
class Figure:
    """A measurement the claim states: its wording, digits and unit family."""

    text: str
    value: str
    family: str


@dataclass(frozen=True)
class CitedExcerpt:
    """A whole line of the record, where it states the claim's figures, and what it lacks."""

    line: str
    marks: list[tuple[int, int]] = field(default_factory=list)
    unstated: list[str] = field(default_factory=list)


def record_sentences(quote: str) -> list[str]:
    """Sentences and spec lines of a record, boilerplate and markup removed."""
    lines = []
    for raw in re.split(r"<br\s*/?>|\n", quote, flags=re.IGNORECASE):
        line = _DESCRIPTION_LABEL.sub("", raw.strip())
        if line and not _HEADER.match(line):
            lines.extend(part.strip() for part in _SENTENCE_END.split(line))
    return [line for line in lines if len(line) >= _MIN_LINE]


def cited_claim(answer: str, number: int) -> str:
    """The clause of the answer that carries citation `number`, without citation marks."""
    at = answer.find(f"[{number}]")
    if at < 0:
        return ""
    clause = _BOUNDARY.split(answer[:at])[-1]
    return re.sub(r"\[\d+\]", "", clause).strip()


def _terms(text: str) -> set[str]:
    return {
        word
        for word in re.findall(r"[a-z0-9]{4,}", text.lower())
        if word not in _STOPWORDS
    }


def figures(text: str) -> list[Figure]:
    """Each figure-and-unit the text states; 90W, 90 W and 90 watts are one figure."""
    found: list[Figure] = []
    taken: list[tuple[int, int]] = []
    for match in _RESOLUTION.finditer(text):
        found.append(Figure(match.group(), f"{match[1]}x{match[2]}", "resolution"))
        taken.append(match.span())
    for match in _TOKEN.finditer(text):
        if any(start <= match.start() < end for start, end in taken):
            continue
        token = match.group().replace(",", "")
        if re.match(r"^[A-Za-z]+\d", token):
            continue
        attached = re.search(r"[A-Za-z]+$", token)
        following = re.match(r"[\s-]+([A-Za-z]+)", text[match.end() :])
        unit = attached.group() if attached else following[1] if following else None
        family = UNIT_ALIASES.get(unit.lower()) if unit else None
        if family is None:
            continue
        value = re.search(r"\d+(?:\.\d+)?", token)
        end = match.end() + (0 if attached or not following else len(following.group()))
        found.append(
            Figure(text[match.start() : end], value.group() if value else token, family)
        )
    unique: list[Figure] = []
    for figure in found:
        if all((f.value, f.family) != (figure.value, figure.family) for f in unique):
            unique.append(figure)
    return unique


def _stated_at(line: str, figure: Figure) -> tuple[int, int] | None:
    """Where `line` states `figure` in the same unit family."""
    if figure.family == "resolution":
        pattern = figure.value.replace("x", r"\s*[x×]\s*")
    else:
        aliases = sorted(
            (re.escape(a) for a, f in UNIT_ALIASES.items() if f == figure.family),
            key=len,
            reverse=True,
        )
        pattern = rf"{re.escape(figure.value)}[\s-]*(?:{'|'.join(aliases)})"
    found = re.search(
        rf"(?<![A-Za-z0-9.,]){pattern}(?![A-Za-z0-9])", line, re.IGNORECASE
    )
    return found.span() if found else None


def cited_excerpt(quote: str, answer: str, number: int) -> CitedExcerpt:
    """The record line that best supports what the answer cited it for.

    A line stating the claim's figure in the same unit wins; otherwise the line sharing
    the most of the claim's words, with ties kept by the earliest line.
    """
    claim_text = cited_claim(answer, number)
    wanted = figures(claim_text)
    unstated = [f.text for f in wanted if _stated_at(quote, f) is None]
    lines = record_sentences(quote)
    if not lines:
        return CitedExcerpt("", [], unstated)
    # The product's own name appears in every line of the claim and says nothing about support.
    title = re.search(r"^title\s*:(.*)$", quote, re.IGNORECASE | re.MULTILINE)
    name = _terms(title[1] if title else "")
    claim = _terms(claim_text)
    best, best_marks, best_score = lines[0], [], 0
    for line in lines:
        marks = sorted(span for f in wanted if (span := _stated_at(line, f)))
        score = len({w for w in _terms(line) if w in claim and w not in name})
        if len(marks) > len(best_marks) or (
            len(marks) == len(best_marks) and score > best_score
        ):
            best, best_marks, best_score = line, marks, score
    return CitedExcerpt(best, best_marks, unstated)


# Words kept before a figure the line has to be cut to show, so it reads as a phrase.
_LEAD_IN = 30


def clip_around(line: str, marks: list[tuple[int, int]], limit: int) -> str:
    """At most `limit` characters of `line`, keeping its first marked figure in view.

    A line is cut at its end, as any long quote is. When that would hide the figure, the
    cut moves to the start instead, at a word, with a few words before the figure.
    """
    if len(line) <= limit:
        return line
    start = 0
    if marks and marks[0][1] > limit - 1:
        start = max(0, min(marks[0][0] - _LEAD_IN, len(line) - (limit - 1)))
        start = line.find(" ", start) + 1 or start
    text = line[start:]
    head = "…" if start else ""
    room = limit - len(head)
    return head + (text if len(text) <= room else text[: room - 1].rstrip() + "…")
