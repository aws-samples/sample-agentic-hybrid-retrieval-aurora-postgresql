#!/usr/bin/env python3
"""Rerank a JSONL candidate file with a pluggable local strategy.

Input rows:
  {"query_id":"...","query":"...","candidates":[{"product_id":1,"title":"...","text":"...","attributes":{...},"rrf_score":0.03}]}

The heuristic provider is deterministic and transparent for workshop mechanics.
The cross-encoder provider requires sentence-transformers and a downloaded model.
"""
from __future__ import annotations
import argparse, json, math, re
from pathlib import Path


def heuristic(query, candidate):
    q=set(re.findall(r'[a-z0-9]+',query.lower()))
    text=' '.join([candidate.get('title',''),candidate.get('text',''),json.dumps(candidate.get('attributes',{}))]).lower()
    t=set(re.findall(r'[a-z0-9]+',text))
    overlap=len(q&t)/max(1,len(q))
    hard=1.0
    attrs=candidate.get('attributes') or {}
    if 'carbon' in q and not attrs.get('carbon_plate',False): hard*=.35
    if 'noise' in q and 'cancelling' in q and not attrs.get('active_noise_cancellation',False): hard*=.45
    if 'lumbar' in q and not attrs.get('lumbar_support'): hard*=.45
    base=float(candidate.get('rrf_score',0))*20
    return hard*(.58*overlap+.28*min(1,base)+.14*float(candidate.get('quality_score',.6)))


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--input',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--provider',choices=['heuristic','cross-encoder'],default='heuristic')
    ap.add_argument('--model',default='cross-encoder/ms-marco-MiniLM-L-6-v2')
    a=ap.parse_args()
    encoder=None
    if a.provider=='cross-encoder':
        from sentence_transformers import CrossEncoder
        encoder=CrossEncoder(a.model)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.input.open(encoding='utf-8') as src,a.output.open('w',encoding='utf-8') as dst:
        for line in src:
            row=json.loads(line);cands=row['candidates']
            if encoder:
                scores=encoder.predict([(row['query'],c.get('text') or c.get('title','')) for c in cands]).tolist()
            else:scores=[heuristic(row['query'],c) for c in cands]
            for c,s in zip(cands,scores): c['rerank_score']=round(float(s),6)
            cands.sort(key=lambda c:c['rerank_score'],reverse=True)
            row['candidates']=cands;row['reranker']={'provider':a.provider,'model':a.model if encoder else 'transparent-heuristic-v1'}
            dst.write(json.dumps(row,separators=(',',':'))+'\n')
    print(f'Wrote {a.output}')
if __name__=='__main__':main()
