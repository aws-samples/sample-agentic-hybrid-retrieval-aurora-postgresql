# Lab 3 claim review quotes, 8 November 2026

On the dry run of release `657e40a49ad8aa2f` (source `28c000d7`), five of ten 100W follow-ups
had a synthesis call refused because the claim review's quote "is not in record 1", the
ViewSonic VG2756-4K listing. Every follow-up still answered, but each refusal cost a draft and
up to two reviews. The refused quote was not saved. This record finds the quote and measures
the change in this commit. Per-run results are in
[lab3-quote-check-2026-11-08.json](lab3-quote-check-2026-11-08.json).

## Cause

The review is shown each record whole: its title, its text and `source_context`, which holds
Mosaic's scope note, such as "Historical parent-product listing. Confirm exact variant and
current offer separately." The check looked for each quote in the record's text only.

- Of 8 quotes the released check rejected on the follow-up, all 8 were scope notes: 7 the
  listing's and 1 the review's.
- On the setup request, the one rejected quote was a review's title, "Great work monitor,
  especially for laptops with USB-C connection". A review's title is the reviewer's own words
  but not part of its text.

## Change

- A quote counts when it is in the cited record's title or text. A review's title now counts.
- A scope note is not the record's words: a citation must lead a reader to a record that says
  the sentence. A quote found only there means the passage rests on Mosaic's note, so the
  draft is refused with "write that caveat as a plain step without a citation". That message
  reaches the next draft. A scope quote beside a quote of the same record's words adds nothing
  and is ignored. A quote found nowhere is still the review breaking its rules, and the
  message now names the quote.
- The review prompt says to quote a record's title or text and to use `source_context` to
  judge, never as a quote.

No check was loosened: every quote must still be the cited record's own words. A drafting
instruction to write scope caveats as uncited steps was also measured and dropped: it left
the follow-up's refusals at 6 of 12 and led drafts to state the caveat as an uncited fact.

## Method

`synthesize_cited_answer` was called directly against the development cluster's catalog with
`global.anthropic.claude-sonnet-5-5`, on fixed records: the follow-up with the ViewSonic's
listing and a review that reports charging a laptop (evidence 140 and 155), the setup request
with a listing and a review for each of the three products. One run is one synthesis call:
one draft and up to two reviews. The production agent retries a refused call with the refusal
as feedback, so a refused call costs time, not the answer.

## Results

| Request | Code | Calls | Refused | Review quoting outside title and text | Refused as resting on a scope note |
|---|---|---:|---:|---:|---:|
| 100W follow-up | `28c000d7` | 12 | 8 | 4 | none, check absent |
| 100W follow-up | this commit | 12 | 7 | 0 | 1 |
| Setup request | `28c000d7` | 10 | 4 | 0 | none, check absent |
| Setup request | this commit | 10 | 0 | 0 | 0 |

The change removes the review rule breaks. The follow-up's remaining refusals are draft faults
the checks exist to catch: uncited factual sentences, a product named without its citation, a
review of the VG2755-2K and VG2756-2K attributed to this monitor, and a derived "10W" that no
record states. Their rate did not change. The setup request's four refusals on `28c000d7` were
also draft faults unrelated to quotes, so its 10 of 10 reads as no regression, not as an
improvement. Calls ran two or three at a time, so per-call times are not compared.

## Not measured here

- The deployed agent on a fresh event, where the next walk of this release measures both
  requests end to end.
