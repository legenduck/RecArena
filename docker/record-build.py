"""Record optional build metadata; a source archive needs no Git checkout."""
import json
import os
from pathlib import Path
import re

commit=os.environ.get('RECARENA_CODE_COMMIT') or None
source=os.environ.get('RECARENA_SOURCE_TREE_SHA256') or None
dirty=os.environ.get('RECARENA_CODE_DIRTY') or None
if ((commit is not None and not re.fullmatch('[0-9a-f]{40}',commit)) or
    (source is not None and not re.fullmatch('[0-9a-f]{64}',source)) or dirty not in {None,'true','false'}):
    raise SystemExit('Invalid supplied build metadata')
Path('/app/build-provenance.json').write_text(json.dumps({'code_commit':commit,'source_tree_sha256':source,
    'code_dirty':None if dirty is None else dirty=='true'})+'\n')
