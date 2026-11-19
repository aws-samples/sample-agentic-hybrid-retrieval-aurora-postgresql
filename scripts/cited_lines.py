"""The line of a cited record closest to the claim citing it, as the terminal prints it.

A citation covers its whole record; the agent chooses no line. This picks the one to show.

Ask Mosaic and Playground choose the same line in `ui/src/components/ask-mosaic/
quoteLines.ts`; `data/cited_line_cases.json` holds both to one set of cases, and the unit
spellings are the answer check's own (`service.synthesis.UNIT_ALIASES`). A record is stored
as ingested, with `Title:` and `Categories:` headers, `<br />` breaks and a review's
`[[VIDEOID:...]]` and `[[ASIN:...]]` markup; none of it is quoted.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from service.claim_review import CITATION, passages
from service.synthesis import UNIT_ALIASES

_HEADER = re.compile(r"^(?:title|categories)\s*:", re.IGNORECASE)
_VIDEO_MARKER = re.compile(r"\[\[VIDEOID:[^\]]*\]\]\s*")
_PRODUCT_LINK = re.compile(r"\[\[ASIN:[^\]\s]*\s*([^\]]*)\]\]")
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


def without_review_markup(text: str) -> str:
    """A review's text as a shopper reads it on the source site.

    Amazon's review text marks an attached video as `[[VIDEOID:...]]`, which reads as
    nothing, and a linked product as `[[ASIN:B0... name]]`, which reads as its name.
    """
    return _PRODUCT_LINK.sub(r"\1", _VIDEO_MARKER.sub("", text))


def record_sentences(quote: str) -> list[str]:
    """Sentences and spec lines of a record, boilerplate and markup removed."""
    lines = []
    for raw in re.split(
        r"<br\s*/?>|\n", without_review_markup(quote), flags=re.IGNORECASE
    ):
        line = _DESCRIPTION_LABEL.sub("", raw.strip())
        if line and not _HEADER.match(line):
            lines.extend(part.strip() for part in _SENTENCE_END.split(line))
    return [line for line in lines if len(line) >= _MIN_LINE]


def cited_claim(answer: str, number: int) -> str:
    """Every clause of the answer that carries citation `number`, without citation marks.

    A record gets one excerpt, so it has to serve each sentence that cites it: with only the
    first, a USB-hub sentence before a 90W one (both citing [1]) picked a line with no wattage.
    """
    marker = f"[{number}]"
    clauses = []
    at = answer.find(marker)
    while at >= 0:
        clause = _BOUNDARY.split(answer[:at])[-1]
        clauses.append(re.sub(r"\[\d+\]", "", clause).strip())
        at = answer.find(marker, at + len(marker))
    return " ".join(clause for clause in dict.fromkeys(clauses) if clause)


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


def _squash(text: str) -> str:
    return " ".join(without_review_markup(text).split())


def saved_support_quotes(
    receipt: dict[str, Any] | None, answer: str, number: int
) -> list[str]:
    """What the answer check saved as support for citation `number`, in its own words.

    Only a review bound to this exact answer counts (`answer_sha256`, as
    `service.lab_followup.claim_review_problem` binds it). A quote counts when its passage is
    supported and the passage's own text, numbered as the review numbered it, cites `number`.
    Runs saved before the review kept quotes, or with another answer's review, give none.
    """
    if not isinstance(receipt, dict) or not answer:
        return []
    if receipt.get("answer_sha256") != hashlib.sha256(answer.encode()).hexdigest():
        return []
    texts = {part["id"]: part["text"] for part in passages(answer)}
    quotes: list[str] = []
    for passage in receipt.get("passages") or []:
        if not isinstance(passage, dict) or passage.get("verdict") != "supported":
            continue
        text = texts.get(passage.get("id"), "")
        if number not in {int(n) for n in CITATION.findall(text)}:
            continue
        for support in passage.get("support") or []:
            quote = _squash(str(support.get("quote", ""))) if support else ""
            if support and support.get("number") == number and quote:
                quotes.append(quote)
    return list(dict.fromkeys(quotes))


def locate_quotes(
    lines: list[str], quotes: list[str]
) -> dict[int, list[tuple[int, int]]] | None:
    """Where each saved quote sits in the record: its line index and character span.

    Every quote must occur exactly once in the record and inside one line. When one is
    missing, repeated or runs across lines, the place is not certain and the result is
    None, so the reader falls back rather than point at a guess. Overlapping quotes merge.
    """
    squashed = [_squash(line) for line in lines]
    found: dict[int, list[tuple[int, int]]] = {}
    for quote in quotes:
        hits = [(i, line) for i, line in enumerate(squashed) if quote in line]
        if len(hits) != 1 or hits[0][1].count(quote) != 1:
            return None
        index, line = hits[0]
        start = line.index(quote)
        found.setdefault(index, []).append((start, start + len(quote)))
    merged: dict[int, list[tuple[int, int]]] = {}
    for index, spans in found.items():
        for start, end in sorted(spans):
            if merged.get(index) and start <= merged[index][-1][1]:
                merged[index][-1] = (
                    merged[index][-1][0],
                    max(end, merged[index][-1][1]),
                )
            else:
                merged.setdefault(index, []).append((start, end))
    return merged or None


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
