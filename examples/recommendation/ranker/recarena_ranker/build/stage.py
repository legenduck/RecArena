"""Copy verified runtime artifacts into a mount that cannot contain hidden tasks."""
import argparse
from pathlib import Path
import re
import shutil
from uuid import uuid4

from recarena_contracts.artifacts import verify_manifest

FILES={
    'review_timestamps':{'timestamps_ms.npy','offsets.npy','product_id_to_row.json','reference.json'},
    'tfidf':{'idf.npy','item_id_to_row.json','matrix.npz','vectorizer_config.json','vocabulary.json'},
    'bpr_serving':{'model.json','export_equivalence_report.json','item_factors.npy','item_id_to_row.json','popularity_counts.json',
        'quality_report.json','split_report.json','test_metrics.json','trained_item_ids.json','trained_user_ids.json',
        'training_config.json','training_history.json','training_manifest.json','user_factors.npy','user_id_to_row.json','validation_metrics.json'},
}
FILES['cf_serving'] = FILES['bpr_serving']
LUCENE_FILE=re.compile(r'index/(?:write\.lock|(?:pending_)?segments_[0-9a-z]+|_[A-Za-z0-9_]+\.(?:cfs|cfe|si|fnm|fdm|fdt|fdx|nvd|nvm|tvd|tvm|tvx|doc|pos|pay|psm|tim|tip|tmd|dvd|dvm|dvs|liv|dim|dii|kdd|kdi|kdm|vec|vem|vex))')


def stage(manifest_path,destination_root):
    manifest_path=Path(manifest_path).resolve()
    manifest=verify_manifest(manifest_path)
    kind=manifest['artifact_type']
    names={entry['path'] for entry in manifest['files']}
    if kind=='lucene_index':
        if not {'documents/products.jsonl','index_config.json'}<=names or any(
            name not in {'documents/products.jsonl','index_config.json'} and not LUCENE_FILE.fullmatch(name)
            for name in names):
            raise ValueError('Unexpected file in runtime Lucene artifact')
    elif kind not in FILES or not names.issubset(FILES[kind]):
        raise ValueError('Only allowlisted serving artifact files may enter runtime mount')
    destination_root=Path(destination_root).resolve()
    destination_root.mkdir(parents=True,exist_ok=True)
    destination=destination_root/manifest['artifact_id']
    if destination.exists():
        if verify_manifest(destination/'manifest.json')!=manifest: raise ValueError('Runtime artifact ID is immutable')
        return destination/'manifest.json'
    temporary=destination_root/('.staging-'+uuid4().hex)
    temporary.mkdir()
    for name in [*names,'manifest.json']:
        target=temporary/name;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(manifest_path.parent/name,target)
    if verify_manifest(temporary/'manifest.json')!=manifest: raise ValueError('Staging integrity mismatch')
    temporary.rename(destination)
    return destination/'manifest.json'


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--output-root',type=Path,default=Path('artifacts/runtime'))
    args=parser.parse_args()
    print(stage(args.manifest,args.output_root))
