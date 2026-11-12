"""Optional build metadata; runtime never shells out to Git or scans source files."""
import json
import os
from pathlib import Path
import re


def provenance(scope="platform"):
    # Retain the argument for artifact-builder compatibility. Metadata describes
    # the supplied build, not a runtime inference from the surrounding checkout.
    unknown = {'code_commit': None, 'code_dirty': None, 'source_tree_sha256': None}
    filename = os.environ.get('RECARENA_BUILD_PROVENANCE')
    if not filename:
        return unknown
    value = json.loads(Path(filename).read_text())
    if not isinstance(value, dict) or set(value) != set(unknown):
        raise ValueError('Invalid build provenance')
    for key, pattern in [('code_commit', r'[0-9a-f]{40}'), ('source_tree_sha256', r'[0-9a-f]{64}')]:
        if value[key] is not None and (not isinstance(value[key], str) or not re.fullmatch(pattern, value[key])):
            raise ValueError('Invalid build provenance')
    if value['code_dirty'] is not None and type(value['code_dirty']) is not bool:
        raise ValueError('Invalid build provenance')
    return value
