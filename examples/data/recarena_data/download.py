"""Download category originals linked by the official Amazon Reviews 2023 site."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

SOURCE_PAGE = 'https://amazon-reviews-2023.github.io/'
RAW_BASE = 'https://mcauleylab.ucsd.edu/public_datasets/data/amazon_2023/raw'


def source_urls(category):
    if not re.fullmatch(r'[A-Za-z0-9_]+', category):
        raise ValueError('Use the official category name, for example Grocery_and_Gourmet_Food')
    return {'metadata': f'{RAW_BASE}/meta_categories/meta_{category}.jsonl.gz',
            'reviews': f'{RAW_BASE}/review_categories/{category}.jsonl.gz'}


def download_file(url, destination):
    destination = Path(destination)
    if destination.is_file():
        if destination.stat().st_size == 0:
            raise ValueError(f'Existing file is empty: {destination}')
        return 'existing'
    if shutil.which('curl') is None:
        raise ValueError('Install curl to download originals, or supply existing files to prepare')
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + '.part')
    subprocess.run(['curl', '--fail', '--location', '--silent', '--show-error', '--retry', '3',
                    '--continue-at', '-', '--output', str(partial), url], check=True)
    if partial.stat().st_size == 0:
        raise ValueError(f'Download returned an empty file: {url}')
    # Publish only a completed transfer, without replacing an existing original.
    os.link(partial, destination)
    partial.unlink()
    return 'downloaded'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--category', required=True)
    parser.add_argument('--output', type=Path, required=True, help='Raw data root; complete files are reused')
    parser.add_argument('--print-urls', action='store_true', help='Print sources without downloading anything')
    args = parser.parse_args()
    try:
        urls = source_urls(args.category)
        if args.print_urls:
            print(json.dumps(urls, indent=2))
            return
        for kind, url in urls.items():
            folder = 'meta_categories' if kind == 'metadata' else 'review_categories'
            destination = args.output / folder / url.rsplit('/', 1)[1]
            status = download_file(url, destination)
            print(json.dumps({'kind': kind, 'url': url, 'path': str(destination.resolve()), 'status': status}), flush=True)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'Download failed: {error}\n')


if __name__ == '__main__':
    main()
