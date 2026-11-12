"""Import a researcher-owned RecBole BPR checkpoint without training.

The source atomic file and checkpoint are read-only inputs. RecBole itself
reconstructs token ordering and its declared split. Only verified NumPy/JSON
outputs enter the existing HTTP ranker; the checkpoint remains offline.
"""
from __future__ import annotations

import argparse
import ast
import copy
import json
import logging
import math
from pathlib import Path
import re
import shutil

import numpy as np
import pandas as pd
import recbole
from recbole.config import Config
from recbole.data import create_dataset
from recbole.model.general_recommender import BPR
from recbole.utils import EvaluatorType, FeatureSource, FeatureType, InputType, ModelType, init_seed
import torch
from yaml.loader import FullLoader

from recarena_contracts.artifacts import digest, make_manifest, write_json
from recarena_contracts.history import history_fingerprint_sorted
from .embeddings import export_model


class ProjectedRows:
    def __init__(self, frame):
        self.frame = frame

    def __iter__(self):
        for user, product, timestamp in self.frame.itertuples(index=False, name=None):
            yield {'user_id': str(user), 'product_id': str(product), 'timestamp': float(timestamp)}


def copy_verified(source, target):
    source = Path(source).resolve(strict=True)
    checksum = digest(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('xb') as destination, source.open('rb') as original:
        shutil.copyfileobj(original, destination, 1024 * 1024)
    if digest(target) != checksum:
        raise ValueError('Source changed during copy; select a completed immutable input')
    return checksum


def read_quality(log_path):
    result = {'validation_metrics': None, 'test_metrics': None, 'training_losses': {}}
    if log_path is None:
        return result
    for line in log_path.read_text().splitlines():
        for label, key in [('best valid', 'validation_metrics'), ('test result', 'test_metrics')]:
            if match := re.search(re.escape(label) + r'\s*:\s*OrderedDict\((\[.*\])\)', line):
                result[key] = {str(k): float(v) for k, v in ast.literal_eval(match.group(1))}
        if match := re.search(r'epoch (\d+) training.*train loss: ([0-9.eE+-]+)', line):
            result['training_losses'][match.group(1)] = float(match.group(2))
    return result


def import_checkpoint(checkpoint_path, atomic_path, output, *, catalog_id, history_id,
                      timestamp_unit, training_log=None, trusted_researcher_checkpoint=False):
    checkpoint_path, atomic_path = Path(checkpoint_path).resolve(), Path(atomic_path).resolve()
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    training = output / 'training'
    training.mkdir()
    logging.basicConfig(level=logging.INFO,
        handlers=[logging.FileHandler(output / 'import.log')], force=True)
    print('Copying explicitly supplied checkpoint and inputs with checksum verification', flush=True)
    checkpoint_hash = copy_verified(checkpoint_path, training / 'selected_checkpoint.pth')
    # The explicit researcher-owned checkpoint is deserialized only in this offline environment.
    if trusted_researcher_checkpoint:
        # Explicit offline researcher-owned inputs may use protocol4/RecBole
        # Config, which torch2.5's restricted loader cannot decode (FRAME149).
        # This path is never exposed to browser uploads or online serving.
        from .checkpoint_io import load_checkpoint
        checkpoint = load_checkpoint(training / 'selected_checkpoint.pth')
    else:
        with torch.serialization.safe_globals([Config, BPR, FullLoader, ModelType, InputType, EvaluatorType]):
            checkpoint = torch.load(training / 'selected_checkpoint.pth', map_location='cpu', weights_only=True)
    checkpoint.pop('optimizer', None)  # unused import state; sealed original checkpoint is unchanged
    config = copy.deepcopy(checkpoint['config'])
    if config['model'] != 'BPR':
        raise ValueError('This bridge imports the BPR component; it cannot relabel another model as BPR')
    if config['USER_ID_FIELD'] != 'user_id' or config['ITEM_ID_FIELD'] != 'item_id':
        raise ValueError('The atomic boundary requires user_id/item_id fields')
    original_config = json.loads(json.dumps(config.final_config_dict, default=str, allow_nan=False))
    dataset_name = str(config['dataset'])
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', dataset_name):
        raise ValueError('Invalid dataset name in checkpoint')
    atomic_directory = training / 'atomic' / dataset_name
    benchmarks = config['benchmark_filename']
    if benchmarks is None:
        copied_sources = [atomic_directory / (dataset_name + '.inter')]
        atomic_hashes = {copied_sources[0].name: copy_verified(atomic_path, copied_sources[0])}
    else:
        if (not atomic_path.is_dir() or len(benchmarks) != 3 or len(set(benchmarks)) != 3
                or any(not re.fullmatch(r'[A-Za-z0-9_.-]+', str(name)) for name in benchmarks)):
            raise ValueError('Supply the original directory containing the three declared benchmark files')
        copied_sources, atomic_hashes = [], {}
        for name in benchmarks:
            target = atomic_directory / f'{dataset_name}.{name}.inter'
            atomic_hashes[target.name] = copy_verified(atomic_path / target.name, target)
            copied_sources.append(target)
    log_path = None
    if training_log is not None:
        log_path = training / 'source_training.log'
        copy_verified(Path(training_log), log_path)
    # Device/path changes are import-runtime settings only; preserve the actual training config above.
    config['data_path'] = str(atomic_directory)
    config['device'] = torch.device('cpu')
    config['use_gpu'] = False
    config['save_dataset'] = False
    config['save_dataloaders'] = False
    init_seed(config['seed'], config['reproducibility'])
    print('Reconstructing original RecBole token mapping and declared partitions; no fit call', flush=True)
    dataset = create_dataset(config)
    expected_users = checkpoint['state_dict']['user_embedding.weight'].shape[0]
    expected_items = checkpoint['state_dict']['item_embedding.weight'].shape[0]
    if dataset.user_num != expected_users or dataset.item_num != expected_items:
        raise ValueError('Checkpoint vocabulary shape does not match the supplied atomic input')
    if any(not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}', str(token))
           for field in ('user_id', 'item_id') for token in dataset.field2id_token[field][1:]):
        raise ValueError('Source token cannot be represented by the stable sandbox ID contract')
    source_times = dataset.inter_feat[config['TIME_FIELD']].to_numpy(dtype=np.float64, copy=True)
    scale = {'seconds': 1., 'milliseconds': 1000.}[timestamp_unit]
    source_times /= scale
    if not np.isfinite(source_times).all():
        raise ValueError('Source timestamps must be finite')
    # RecBole converts timestamps to float32 before sorting. Attach a temporary
    # integer row marker AFTER its data processing to recover exact source times
    # after its own build(), without changing token mapping, sorting or splitting.
    marker = '_recarena_source_row'
    if marker in dataset.inter_feat:
        raise ValueError('Reserved import marker already exists')
    dataset.inter_feat[marker] = np.arange(len(dataset), dtype=np.int64)
    dataset.field2type[marker] = FeatureType.TOKEN
    dataset.field2source[marker] = FeatureSource.INTERACTION
    dataset.field2seqlen[marker] = 1
    partitions = dataset.build()
    if len(partitions) != 3 or any(len(partition) == 0 for partition in partitions):
        raise ValueError('Expected the supplied train/valid/test partition contract')
    frames = {}
    code_pairs = {}
    for label, partition in zip(('train', 'valid', 'test'), partitions):
        rows = partition.inter_feat.interaction.pop(marker).numpy()
        users = partition.inter_feat['user_id'].numpy()
        items = partition.inter_feat['item_id'].numpy()
        frames[label] = pd.DataFrame({'user_id': dataset.field2id_token['user_id'][users],
            'product_id': dataset.field2id_token['item_id'][items], 'timestamp': source_times[rows]})
        code_pairs[label] = np.unique(users * np.int64(dataset.item_num) + items)
    dataset.inter_feat.interaction.pop(marker, None)
    dataset.field2type.pop(marker)
    dataset.field2source.pop(marker)
    dataset.field2seqlen.pop(marker)
    # The fixed platform history is a support projection, not replacement training input.
    history = frames['train'].groupby(['user_id', 'product_id'], sort=True, as_index=False)['timestamp'].min()
    fingerprint = history_fingerprint_sorted(history.itertuples(index=False, name=None))
    history_file = training / 'history_projection.jsonl'
    with history_file.open('x') as stream:
        for record in ProjectedRows(history):
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True, allow_nan=False) + '\n')
    split_report = {'origin': 'researcher_supplied_checkpoint', 'eval_args': original_config['eval_args'],
        'benchmark_filename': benchmarks, 'training_file': benchmarks[0] if benchmarks else None,
        'counts': {key: len(frame) for key, frame in frames.items()},
        'time_ranges': {key: [float(frame.timestamp.min()), float(frame.timestamp.max())] for key, frame in frames.items()},
        'timestamp_unit': timestamp_unit, 'exact_source_timestamps_retained': True,
        'train_user_count': int(history.user_id.nunique()), 'train_item_count': int(history.product_id.nunique()),
        'platform_history_pairs': len(history), 'source_train_repeat_rows': len(frames['train']) - len(history),
        'train_valid_shared_pairs': len(np.intersect1d(code_pairs['train'], code_pairs['valid'])),
        'train_test_shared_pairs': len(np.intersect1d(code_pairs['train'], code_pairs['test']))}
    history_metadata = {'history_snapshot_id': history_id, 'catalog_snapshot_id': catalog_id,
        'interaction_count': len(history), 'fingerprint': fingerprint,
        'source_training_event_count': len(frames['train']),
        'projection': 'unique_user_parent_with_earliest_exact_source_time_within_actual_train'}
    model = BPR(config, partitions[0]).to('cpu')
    model.load_state_dict(checkpoint['state_dict'], strict=True)
    if checkpoint.get('other_parameter') is not None:
        model.load_other_parameter(checkpoint['other_parameter'])
    print('Exporting original fixed factors and comparing actual RecBole predictions', flush=True)
    report, users, items = export_model(model, dataset, {'train': ProjectedRows(history)}, output / 'serving')
    serving = output / 'serving'
    quality = read_quality(log_path)
    if quality['validation_metrics'] is not None and not np.isclose(
            quality['validation_metrics'][str(config['valid_metric']).lower()], checkpoint['best_valid_score']):
        raise ValueError('Supplied training log does not match checkpoint validation metric')
    warnings = ['Researcher-owned preprocessing/split retained; not trained by the sandbox reference pipeline.',
        'ID mapping reconstructed from the supplied atomic input; this legacy checkpoint contains no original input hash.',
        'Original supplied files preserved; new hashes pin the exact imported bytes.',
        'MostPop diagnostic is not supplied; no new full-sort model evaluation or training was performed.']
    if split_report['train_item_count'] < len(items):
        warnings.append('Untrained vocabulary items are excluded from BPR scoring via the support list.')
    validation_score = float(checkpoint['best_valid_score'])
    quality.update(origin='researcher_supplied_checkpoint', best_epoch=int(checkpoint['epoch']),
        validation_score=validation_score if math.isfinite(validation_score) else None,
        stopping_reason='supplied_checkpoint',
        support_coverage={'users': split_report['train_user_count'] / len(users),
                          'items': split_report['train_item_count'] / len(items)},
        mostpop=None, warnings=warnings)
    provenance = {'checkpoint_sha256': checkpoint_hash,
        'atomic_sha256': atomic_hashes[copied_sources[0].name] if benchmarks is None else None,
        'atomic_files_sha256': atomic_hashes,
        'source_checkpoint': str(checkpoint_path), 'source_atomic': str(atomic_path),
        'recbole_import_version': recbole.__version__, 'torch_import_version': torch.__version__,
        'training_performed': False, 'original_protocol': original_config['eval_args'],
        'benchmark_filename': benchmarks,
        'offline_trusted_researcher_checkpoint': trusted_researcher_checkpoint,
        'source_record_count_after_recbole_processing': int(sum(split_report['counts'].values())),
        'token_mapping': 'recbole_create_dataset_from_copied_original_atomic',
        'history_projection': history_metadata['projection']}
    for directory in (training, serving):
        for filename, value in [('training_config.json', original_config), ('training_history.json', history_metadata),
                                ('split_report.json', split_report), ('quality_report.json', quality)]:
            write_json(directory / filename, value)
    write_json(training / 'import_provenance.json', provenance)
    write_json(serving / 'validation_metrics.json', quality['validation_metrics'])
    write_json(serving / 'test_metrics.json', quality['test_metrics'])
    write_json(serving / 'popularity_counts.json', {str(key): int(value) for key, value in history.groupby('product_id').size().items()})
    counts = {'users': len(users), 'items': len(items), **split_report['counts']}
    # Hash the sealed input copies so a later researcher-side file update cannot
    # relabel this import's actual source bytes halfway through publication.
    source_files = [training / 'selected_checkpoint.pth', *copied_sources] + ([log_path] if log_path else [])
    training_manifest = make_manifest(training, 'bpr_training', original_config,
        sources=source_files, parents=[catalog_id, history_id], counts=counts, warnings=warnings, source_scope="examples/recommendation/training")
    write_json(serving / 'training_manifest.json', training_manifest)
    manifest = make_manifest(serving, 'bpr_serving', original_config, sources=source_files,
        parents=[catalog_id, history_id, training_manifest['artifact_id']], counts=counts, warnings=warnings, source_scope="examples/recommendation/training")
    result = {'artifact_id': manifest['artifact_id'], 'training_artifact_id': training_manifest['artifact_id'],
        'serving_path': str(serving), 'training_path': str(training),
        'history_projection_path': str(history_file), 'history_fingerprint': fingerprint,
        'equivalence': report, 'split_report': split_report, 'quality': quality, 'import_provenance': provenance}
    write_json(output / 'result.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkpoint', type=Path, required=True)
    parser.add_argument('--atomic', type=Path, required=True,
                        help='Original .inter file, or directory containing the checkpoint benchmark files')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--catalog', required=True)
    parser.add_argument('--history', required=True)
    parser.add_argument('--timestamp-unit', choices=['seconds', 'milliseconds'], required=True)
    parser.add_argument('--training-log', type=Path)
    parser.add_argument('--trusted-researcher-checkpoint', action='store_true',
                        help='Allow trusted researcher-owned legacy pickle only in this offline importer')
    args = parser.parse_args()
    result = import_checkpoint(args.checkpoint, args.atomic, args.output,
        catalog_id=args.catalog, history_id=args.history, timestamp_unit=args.timestamp_unit,
        training_log=args.training_log, trusted_researcher_checkpoint=args.trusted_researcher_checkpoint)
    print(json.dumps({'serving_path': result['serving_path'], 'artifact_id': result['artifact_id'],
                      'equivalence': result['equivalence']}, sort_keys=True, allow_nan=False))


if __name__ == '__main__':
    main()
