# Deprecated design elements

## Old fixture IDs

All old IDs are superseded by `docs/ID-STANDARDIZATION.md`.

## Scale page

`verity-scale.html` is retained only as a design reference.

Do not implement it in the core UI.

Reasons:

- outside the 50-minute teaching budget;
- contained an invalid instance/Optimized Reads combination;
- modeled numbers were not target-Aurora measurements;
- weakens the Aurora retrieval/proof narrative.

A measured scale appendix may be added later.

## Remote fonts

Concept HTML uses Google Fonts. The production React app must not.

## Seven-screen navigation

Ask, Lab, Fusion, Plan, Eval, Graph, and Scale are consolidated into Retrieve, Prove, and Port tools.
