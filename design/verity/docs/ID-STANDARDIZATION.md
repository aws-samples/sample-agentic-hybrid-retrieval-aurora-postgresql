# Identifier standardization

## Mapping

| Old | New |
|---|---|
| `CHG-1842` | `CHG-1000` |
| `CHG-1838` | `CHG-1001` |
| `CHG-1907` | `CHG-1002` |
| `CHG-1731` | `CHG-1010` |
| `INC-2047` | `INC-2000` |
| `INC-1980` | `INC-2001` |
| `LOCK-2047-001` | `LOCK-3000` |
| `LOCK-2047-002` | `LOCK-3001` |
| `CASE-7419` | `CASE-4000` |
| `CASE-7421` | `CASE-4001` |
| `CASE-7424` | `CASE-4002` |
| `RB-017` | `RB-5000` |
| `RB-092` | `RB-5001` |
| `COMMIT-4471` | `COMMIT-6000` |
| `rr_9b41d7` | `RUN-7000` |
| `rr_9b41d4` | `RUN-7001` |
| `rr_9b41d5` | `RUN-7002` |
| `rr_9b41d6` | `RUN-7003` |
| `rr_9b41d2` | `RUN-7004` |
| typo `CHG-1482` | typo `CGH-1000` |

## Required migration surfaces

- SQL seed data;
- FK/join fixtures;
- synthetic generator;
- API development fixtures;
- evaluation queries;
- relevance judgments;
- relationship judgments;
- tests and snapshots;
- frontend fixtures;
- mockup text;
- lab guide;
- README and architecture docs;
- replay fixtures;
- contract parity goldens.

## Migration safety

Do not use blind global replacement for `LOCK-2047-001` before replacing `INC-2047`, because composite IDs can be corrupted.

Use `scripts/migrate_fixture_ids.py` and review the diff.

## Typo fixture: `CGH-1000`, not `CHG-0100`

The controlled trigram mutation is the **letter** transposition `CGH-1000`, replacing the
earlier digit transposition `CHG-0100`. Any package still carrying `CHG-0100` needs this
second migration applied.

`CHG-0100` is unusable because a digit transposition collides with the `x100+` background
range from the identifier scheme. Measured `pg_trgm` similarity against the canonical
thread plus a 198-identifier deterministic background corpus, at threshold `0.30`:

| Probe | Rows returned at 0.30 | Top matches |
|---|---:|---|
| `CGH-1000` | 1 | `CHG-1000` 0.5000; next-nearest `CHG-1100` 0.2857 |
| `CHG-0100` | 6 | `CHG-1100` 0.5000 **tied with** `CHG-1000` 0.5000; then `CHG-1001`/`CHG-1002`/`CHG-1010` at 0.3846 |

`CGH-1000` therefore makes "the typo resolves to `CHG-1000`" a deterministic checkpoint
instead of a tie-break accident. Do not reintroduce a digit transposition, and do not
allocate a background identifier that is one transposition away from a canonical one.
