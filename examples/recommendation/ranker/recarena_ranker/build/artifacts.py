"""Optional local artifact management for the bundled ranker only."""
import argparse
import json
import os
from pathlib import Path
import httpx
from recarena_contracts.artifacts import verify_manifest
from .stage import stage


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=['verify', 'stage', 'register'])
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output-root', type=Path, default=Path('artifacts/runtime'))
    args = parser.parse_args()
    if args.operation == 'register':
        with httpx.Client(base_url=os.environ.get('RECARENA_RANKER_URL', 'http://127.0.0.1:8011'),
            headers={'Authorization':'Bearer '+os.environ.get('RECARENA_INTERNAL_TOKEN','')}, timeout=120) as client:
            response = client.post('/internal/v1/artifacts/register', json={'manifest_path':str(args.manifest.resolve())})
            response.raise_for_status()
            result = response.json()
    else:
        path = stage(args.manifest, args.output_root) if args.operation == 'stage' else args.manifest.resolve()
        result = {'manifest_path': str(path), 'manifest': verify_manifest(path)}
    print(json.dumps(result, allow_nan=False))


if __name__ == '__main__': main()
