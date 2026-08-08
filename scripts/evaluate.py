#!/usr/bin/env python3
"""Compute recall@k, MRR, and nDCG from judgments and a result CSV."""
from __future__ import annotations
import argparse, csv, gzip, math
from collections import defaultdict
from pathlib import Path

def open_text(path: Path):
    return gzip.open(path, "rt", encoding="utf-8", newline="") if path.suffix == ".gz" else path.open("r", encoding="utf-8", newline="")

def dcg(grades):
    return sum((2**g - 1) / math.log2(i + 2) for i, g in enumerate(grades))

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--judgments", type=Path, default=Path("data/evals/judgments.csv.gz"))
    ap.add_argument("--results", type=Path, required=True, help="CSV: query_id,product_id,rank")
    ap.add_argument("--k", type=int, default=10)
    a=ap.parse_args()
    truth=defaultdict(dict)
    with open_text(a.judgments) as f:
        for r in csv.DictReader(f): truth[r["query_id"]][int(r["product_id"])]=int(r["relevance_grade"])
    ranked=defaultdict(list)
    with open_text(a.results) as f:
        for r in csv.DictReader(f): ranked[r["query_id"]].append((int(r["rank"]),int(r["product_id"])))
    recalls=[]; mrr=[]; ndcgs=[]
    for q, judgments in truth.items():
        got=[pid for _,pid in sorted(ranked.get(q,[]))[:a.k]]
        relevant={pid for pid,g in judgments.items() if g>=2}
        recalls.append(len(relevant & set(got))/max(1,len(relevant)))
        first=next((i+1 for i,pid in enumerate(got) if pid in relevant),None); mrr.append(0 if first is None else 1/first)
        grades=[judgments.get(pid,0) for pid in got]; ideal=sorted(judgments.values(),reverse=True)[:a.k]
        ndcgs.append(dcg(grades)/(dcg(ideal) or 1))
    print(f"queries={len(truth)} recall@{a.k}={sum(recalls)/len(recalls):.4f} MRR={sum(mrr)/len(mrr):.4f} nDCG@{a.k}={sum(ndcgs)/len(ndcgs):.4f}")
if __name__=="__main__": main()
