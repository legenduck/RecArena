"""Publish configured baseline policies in a new server config; no platform file loading.

The server is restarted with the output config. Existing versions remain intact.
"""
import argparse
import json
from pathlib import Path
from recarena_contracts.artifacts import verify_manifest
from ..profiles import PolicyProfile, create_profile, from_legacy_environment
from ..config import CF_IMPLEMENTATION


def connect_training(config, job, index, *, policy_id='personalization', name=None):
    """Consume completed factor output; no training-package import or platform DB access."""
    job, index = Path(job).resolve(), Path(index).resolve()
    result = json.loads((job / 'result.json').read_text())
    if result.get('status') != 'complete':
        raise ValueError('Expected a completed training job')
    serving_path = job / 'serving' / 'manifest.json'
    serving = verify_manifest(serving_path)
    metadata = json.loads((serving_path.parent / 'model.json').read_text())
    catalog = verify_manifest(index)
    if (serving['artifact_type'] != 'cf_serving' or result['artifact_id'] != serving['artifact_id']
            or metadata.get('model') not in ('BPR', 'LightGCN') or metadata['model'] != result['model']):
        raise ValueError('Training result does not identify supported inference factors')
    if (catalog['artifact_type'] != 'lucene_index'
            or catalog['parent_artifact_ids'] != serving['parent_artifact_ids'][:1]):
        raise ValueError('Model and search index must use the same catalog')
    profile = create_profile(policy_id=policy_id, name=name or f'Personalization ({metadata["model"]})',
        catalog_snapshot_id=catalog['parent_artifact_ids'][0], index_artifact_id=catalog['artifact_id'],
        configuration={'family': 'personalization', 'implementation_id': CF_IMPLEMENTATION, 'combination': 'cf'},
        artifact_ids=[serving['artifact_id']])
    config = {**config}
    for key, path in (('indices', index), ('cf', serving_path)):
        config[key] = list(dict.fromkeys([*config.get(key, []), str(path)]))
    return config, profile


def include_profiles(config, profiles):
    declared = {(item['policy_id'], item['version']): item for item in config.get('policies', [])}
    for profile in profiles:
        value = profile.model_dump(mode='json')
        key = (profile.policy_id, profile.version)
        if key in declared and PolicyProfile.model_validate(declared[key]) != profile:
            raise ValueError('Policy version has conflicting contents')
        declared[key] = value
    return {**config, 'policies': list(declared.values())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, help='Existing server config; omitted starts a new one')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--policy-file', type=Path, help='JSON profile settings; version is derived from its contents')
    mode.add_argument('--legacy-environments', type=Path, help='One-time import of exported pre-service environment records')
    mode.add_argument('--training-job', type=Path, help='Completed BPR/LightGCN training output')
    parser.add_argument('--index', type=Path, help='Lucene manifest for --training-job')
    parser.add_argument('--policy-id', default='personalization', help='Policy name for --training-job')
    parser.add_argument('--name', help='Display name for --training-job')
    parser.add_argument('--output', type=Path, required=True, help='New config file; never overwrites an existing file')
    args = parser.parse_args()
    config = json.loads(args.config.read_text()) if args.config else {}
    if args.training_job:
        if not args.index:
            parser.error('--training-job requires --index')
        config, profile = connect_training(config, args.training_job, args.index,
                                           policy_id=args.policy_id, name=args.name)
        profiles = [profile]
    elif args.policy_file:
        profiles = [create_profile(**json.loads(args.policy_file.read_text()))]
    else:
        profiles = [profile for environment in json.loads(args.legacy_environments.read_text())
                    for profile in from_legacy_environment(environment)]
    config = include_profiles(config, profiles)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        json.dump(config, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write('\n')
    print(f'Wrote {args.output}: {len(config["policies"])} configured policy versions')


if __name__ == '__main__':
    main()
