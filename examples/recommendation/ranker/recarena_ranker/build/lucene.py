from pathlib import Path
import subprocess
import sys


def build_index(documents: Path, output: Path) -> None:
    if output.exists():
        raise FileExistsError('Index output must be a new path; published indices are immutable')
    subprocess.run([
        sys.executable, '-m', 'pyserini.index.lucene', '-collection', 'JsonCollection',
        '-input', str(documents.resolve()), '-index', str(output.resolve()),
        '-generator', 'DefaultLuceneDocumentGenerator', '-threads', '1',
        '-language', 'en', '-storePositions', '-storeDocvectors', '-storeRaw',
    ], check=True)
