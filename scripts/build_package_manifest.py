#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
EXCLUDE={'PACKAGE_MANIFEST.json','PACKAGE_MANIFEST.md','SHA256SUMS'}

def human(size:int)->str:
    if size>=1024**2:return f'{size/1024**2:.1f} MiB'
    if size>=1024:return f'{size/1024:.1f} KiB'
    return f'{size} B'

def main():
    manifest=json.loads((ROOT/'data/full/manifest.json').read_text())
    quality=json.loads((ROOT/'data/full/quality_report.json').read_text())
    dataset_paths=[ROOT/path for path in manifest['full_datasets']]
    files=[]
    for p in sorted(ROOT.rglob('*')):
        rel=str(p.relative_to(ROOT))
        if not p.is_file() or '__pycache__' in p.parts or p.suffix=='.pyc' or p.name in EXCLUDE or rel.endswith('.zip'):continue
        files.append({'path':rel,'bytes':p.stat().st_size})
    obj={'package':'catalog-product-catalog-workshop','version':(ROOT/'VERSION').read_text().strip(),'payload_files':len(files),'payload_bytes':sum(f['bytes'] for f in files),
         'dataset':{'products':manifest['total_products'],'domains':manifest['domain_counts'],'compressed_bytes':sum(path.stat().st_size for path in dataset_paths),
                    'shards':[str(path.relative_to(ROOT)) for path in dataset_paths],
                    'eval_queries':manifest['evaluation']['eval_queries'],'demo_queries':manifest['evaluation']['demo_queries'],'typo_cases':manifest['evaluation']['typo_cases'],'quality_report':quality},
         'complete':['500K sharded catalog','5K balanced sample','15K review sample','720 eval queries','graded judgments','5K typo cases','SQL schema/load/search/index/labs','embedding and rerank adapters','measured benchmark harness','projection model','full documentation'],
         'environment_dependent':['React catalog UI','real model embeddings','physical HNSW index','measured Aurora results','managed reranker model credentials','typed MCP product tools','deployment and bootstrap automation','full licensed product image pack'],
         'files':files}
    (ROOT/'PACKAGE_MANIFEST.json').write_text(json.dumps(obj,indent=2),encoding='utf-8')
    lines=['# Package manifest','',f"Version: `{obj['version']}`  ",f"Payload files: **{obj['payload_files']}**  ",f"Unpacked payload: **{obj['payload_bytes']/1024/1024:.1f} MiB**",'', '## Dataset','',
           f"- 500,000 products ({manifest['domain_counts']['consumer_electronics']:,} electronics; {manifest['domain_counts']['running_fitness']:,} running/fitness; {manifest['domain_counts']['home_office']:,} home office)",
           f"- Full catalog: {len(dataset_paths)} shards ({obj['dataset']['compressed_bytes']/1024/1024:.1f} MiB total; largest {max(path.stat().st_size for path in dataset_paths)/1024/1024:.1f} MiB)",
           f"- {manifest['evaluation']['eval_queries']:,} eval queries, {manifest['evaluation']['demo_queries']:,} demo queries, {manifest['evaluation']['typo_cases']:,} typo cases",
           f"- {quality['brands']:,} synthetic brands and {quality['subcategories']:,} subcategories",
           f"- {quality['canonical_variant_groups_with_multiple_rows']:,} multi-row canonical variant groups",'', '## Complete','']
    lines += [f'- {x}' for x in obj['complete']]
    lines += ['', '## Requires target environment','']+[f'- {x}' for x in obj['environment_dependent']]
    lines += ['', '## File inventory','', '| Path | Size |','|---|---:|']+[f"| `{f['path']}` | {human(f['bytes'])} |" for f in files]
    (ROOT/'PACKAGE_MANIFEST.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(f"Manifest: {obj['payload_files']} files, {human(obj['payload_bytes'])}")
if __name__=='__main__':main()
