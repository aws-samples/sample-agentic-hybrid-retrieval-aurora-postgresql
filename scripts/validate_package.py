#!/usr/bin/env python3
from __future__ import annotations
import csv, gzip, hashlib, json
from collections import Counter
from pathlib import Path
from catalog_contract import unsupported_filter_keys

ROOT=Path(__file__).resolve().parents[1]
manifest=json.loads((ROOT/'data/full/manifest.json').read_text())
quality=json.loads((ROOT/'data/full/quality_report.json').read_text())
assert manifest['total_products']==500000, manifest['total_products']
assert manifest['domain_counts']=={'consumer_electronics':210000,'running_fitness':160000,'home_office':130000}, manifest['domain_counts']
shards=[ROOT/path for path in manifest['full_datasets']]
assert len(shards)==3, shards
assert all(path.is_file() for path in shards), shards
assert all(path.stat().st_size < 100_000_000 for path in shards), [path.stat().st_size for path in shards]
expected_hashes={item['path']:item['sha256'] for item in quality['full_dataset_shards']}
for path in shards:
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest==expected_hashes[str(path.relative_to(ROOT))], path
media=manifest['media_mapping']
media_path=ROOT/media['path']
assert media_path.is_file(), media_path
assert media_path.stat().st_size < 100_000_000, media_path.stat().st_size
assert hashlib.sha256(media_path.read_bytes()).hexdigest()==media['sha256']
with gzip.open(media_path,'rt',encoding='utf-8',newline='') as f:
    assert sum(1 for _ in f)-1==media['rows']==500000
assert quality['invalid_updated_before_launch']==0, quality['invalid_updated_before_launch']
assert quality['malformed_skus']==0, quality['malformed_skus']
assert quality['unsupported_filter_queries']==0, quality['unsupported_filter_queries']
assert quality['filter_target_mismatches']==0, quality['filter_target_mismatches']
queries=[json.loads(line) for line in (ROOT/'data/evals/queries.jsonl').read_text().splitlines() if line.strip()]
assert not {q['query_id']:sorted(unsupported_filter_keys(q.get('filters') or {})) for q in queries if unsupported_filter_keys(q.get('filters') or {})}
with gzip.open(ROOT/'data/sample/products_5000.csv.gz','rt',encoding='utf-8',newline='') as f:
    rows=list(csv.DictReader(f))
assert len(rows)==5000, len(rows)
assert Counter(r['domain'] for r in rows)==Counter({'consumer_electronics':2100,'running_fitness':1600,'home_office':1300})
with (ROOT/'data/evals/typo_cases.csv').open() as f:
    assert sum(1 for _ in f)-1==5000
print('Package validation passed: shards, hashes, row quality, eval filters, sample, and typo cohort.')
