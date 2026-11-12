"""Inspect an existing BPR/LightGCN export, including legacy BPR jobs."""
import argparse
import json
from pathlib import Path
from recarena_contracts.artifacts import verify_manifest
from recarena_contracts.manifest import ArtifactManifest


def training_export(identifier):
    path = Path(identifier)
    if not path.exists():
        raise ValueError('Supply an existing training job directory or manifest path')
    if path.is_dir():
        path = path / ('manifest.json' if (path / 'manifest.json').is_file() else 'training/manifest.json')
    path = path.resolve()
    training = verify_manifest(path)
    serving_path = path.parent.parent / 'serving/manifest.json'
    serving = verify_manifest(serving_path)
    embedded = ArtifactManifest.model_validate_json(
        (serving_path.parent / 'training_manifest.json').read_text()).model_dump(mode='json')
    if ((training['artifact_type'], serving['artifact_type']) not in
            {('bpr_training', 'bpr_serving'), ('cf_training', 'cf_serving')}
            or embedded != training or serving['parent_artifact_ids'] !=
            [*training['parent_artifact_ids'], training['artifact_id']]
            or serving['counts'] != training['counts']):
        raise ValueError('Training/export ancestry mismatch')
    report = json.loads((serving_path.parent / 'export_equivalence_report.json').read_text())
    if (report.get('passed') is not True or report.get('sample_count') !=
            min(1000, training['counts']['users'] * training['counts']['items'])
            or report.get('seed') != 42 or report.get('atol') != 1e-5
            or report.get('rtol') != 1e-4 or report.get('includes_padding') is not False):
        raise ValueError('Training job has no qualifying prediction export')
    return {'manifest_path': str(serving_path), 'manifest': serving,
            'equivalence': report, 'already_exported': True,
            'scope': 'Existing train-and-export job integrity; no new training or equivalence run'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--training-job', required=True)
    print(json.dumps(training_export(parser.parse_args().training_job), allow_nan=False))
