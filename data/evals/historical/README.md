# Historical evaluation inputs

`queries.jsonl` contains the 720 generated eligibility cases for the synthetic
catalog. `canonical_queries.jsonl` contains the twelve synthetic-catalog requests
removed from the active canonical set. These files preserve historical checks;
they are not participant bootstrap inputs and require an operator's historical
Aurora catalog. The active canonical queries, coverage probe and held-out ESCI
corpus target real Mosaic products.

Legacy Aurora assertions run explicitly with `make test-aurora-historical`
against an operator database that already retains that catalog. The normal
workshop test lanes deselect them; they never load rows to satisfy these tests.
