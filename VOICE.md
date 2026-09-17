# Participant-facing language

Write for an experienced builder who is new to this application. Explain the
action, result, and reason in ordinary language. L400 depth comes from inspecting
real SQL, settings, records, failure conditions, and tradeoffs.

- Lead with what a person can do or check: "Where this result came from",
  "Compare each search method", "Sources used", "Saved search", "What changed".
- Do not use research or internal engineering labels as interface copy:
  ablation, provenance, attribution, substrate, canonical, cohort, artifact,
  invariant, or harness. Explain the specific meaning in context.
- Use "answer with sources" for a cited answer. A source link alone does not
  prove that every claim is correct. Describe the checks that actually ran.
- For memory, use facts, preferences, summaries, and past outcomes. Explain
  background processing, storage, user/session boundaries, and expiry directly.
- Avoid promotional filler and vague claims: seamless, powerful, intelligent,
  robust, leverage, unlock, and bulletproof. Name the observable behavior.
- Introduce necessary technical terms through their purpose. Keep exact SQL,
  formulas, parameter names, API fields, AWS service names, and error codes in
  clearly labelled implementation details. Never rename a machine-readable
  field or rewrite source evidence just to make its raw display sound simpler.
- Preserve numbers, units, uncertainty, and measurement dates. Distinguish a
  saved measurement, a live request, and an estimate. Explain a statistical
  measure before expecting participants to interpret its abbreviation.
- Apply this to headings, controls, help text, empty states, errors, accessible
  names, and explanations supplied by the service, as well as the main page.
  Review generated answers and imported source text separately; they are not
  fixed interface copy.

Keep advanced details available. Replace jargon with the mechanism it describes;
do not remove the mechanism or weaken its checks.
