"""Read and preserve the general-model partitions prepared before training."""
import csv
from collections import Counter
import json
import math
from pathlib import Path
import re
import shutil

import numpy as np
import pandas as pd

from recarena_contracts.artifacts import digest
from recarena_contracts.history import history_fingerprint_sorted

FIELDS = ('user_id:token', 'item_id:token', 'rating:float', 'timestamp:float')


def inspect_partitions(directory, dataset=None, train_split='train'):
    directory = Path(directory).resolve(strict=True)
    conversion_path = directory / 'conversion.json'
    conversion = json.loads(conversion_path.read_text()) if conversion_path.exists() else None
    dataset = dataset or (conversion['dataset'] if conversion else directory.name)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', dataset):
        raise ValueError('Invalid dataset name')
    if train_split not in ('train', 'trainval'):
        raise ValueError('Choose train or trainval')
    if conversion and (conversion['format'] != 'general' or conversion['dataset'] != dataset
                       or conversion['timestamp_unit'] != 'milliseconds'):
        raise ValueError('BPR/LightGCN require general .inter files with millisecond timestamps')
    files, counts = {}, {}
    for label, filename in (('train', train_split), ('valid', 'valid'), ('test', 'test')):
        path = directory / f'{dataset}.{filename}.inter'
        count = 0
        with path.open(encoding='utf-8', newline='') as stream:
            reader = csv.DictReader(stream, delimiter='\t')
            if tuple(reader.fieldnames or ()) != FIELDS:
                raise ValueError(f'{path.name}: expected general user/item/rating/timestamp columns')
            for row in reader:
                if (None in row or any(row.get(field) in (None, '') for field in FIELDS)
                        or not all(math.isfinite(float(row[field])) for field in FIELDS[2:])):
                    raise ValueError(f'{path.name}: incomplete or non-finite interaction at row {count + 1}')
                count += 1
        if not count:
            raise ValueError(f'{path.name}: empty partition; choose data with evaluable fixed partitions')
        if conversion and count != conversion['counts'][filename]:
            raise ValueError(f'{path.name}: count differs from conversion.json')
        files[label], counts[label] = path, count
    return files, {
        'dataset': dataset, 'origin': 'prepared_interactions', 'training_file': train_split,
        'benchmark_filename': [train_split, 'valid', 'test'], 'timestamp_unit': 'milliseconds',
        'counts': counts, 'time_split': conversion.get('time_split') if conversion else None,
        'inputs': {label: {'path': str(path), 'sha256': digest(path)} for label, path in files.items()},
        'validation_used_for_selection': train_split == 'train',
    }


def snapshot_inputs(files, report, training):
    directory = training / 'atomic' / report['dataset']
    directory.mkdir(parents=True)
    for label, source in files.items():
        target = directory / source.name
        shutil.copyfile(source, target)
        if digest(target) != report['inputs'][label]['sha256']:
            raise ValueError('Input changed while copying; use completed preparation outputs')
    return directory


def prepare_refit_inputs(selection_directory, selection_report, training):
    """Combine the exact frozen train/valid inputs of epoch selection, without a new split."""
    dataset = selection_report['dataset']
    original = selection_directory / 'training' / 'atomic' / dataset
    directory = training / 'atomic' / dataset
    directory.mkdir(parents=True)
    for label in ('valid', 'test'):
        shutil.copyfile(original / f'{dataset}.{label}.inter', directory / f'{dataset}.{label}.inter')
    with (directory / f'{dataset}.trainval.inter').open('wb') as destination:
        for label in ('train', 'valid'):
            with (original / f'{dataset}.{label}.inter').open('rb') as source:
                header = source.readline()
                if label == 'train':
                    destination.write(header)
                shutil.copyfileobj(source, destination)
                source.seek(-1, 2)
                if source.read(1) not in (b'\n', b'\r'):
                    destination.write(b'\n')
    files, report = inspect_partitions(directory, dataset, 'trainval')
    if report['counts']['train'] != selection_report['counts']['train'] + selection_report['counts']['valid']:
        raise ValueError('Refit input must contain all selected train and validation rows')
    report['time_split'] = selection_report['time_split']
    report['origin'] = 'frozen_train_plus_validation'
    report['derived_from'] = {name: selection_report['inputs'][name] for name in ('train', 'valid')}
    return directory, files, report


def verify_partitions(dataset, partitions, directory, report):
    """Preserve every row; evaluation loaders group rows by user before training.

    Compare ratings/times in RecBole's float32 representation. The original
    millisecond times remain in the frozen inputs and exported training history.
    """
    for label, part, filename in zip(('train', 'valid', 'test'), partitions, report['benchmark_filename']):
        if len(part.dataset) != report['counts'][label]:
            raise ValueError(f'RecBole changed the {label} partition size')
        users = part.dataset.inter_feat['user_id'].numpy()
        items = part.dataset.inter_feat['item_id'].numpy()
        remaining = Counter(zip(users, items, part.dataset.inter_feat['rating'].numpy(),
                                part.dataset.inter_feat['timestamp'].numpy()))
        path = directory / f'{report["dataset"]}.{filename}.inter'
        with path.open(encoding='utf-8', newline='') as stream:
            for row in csv.DictReader(stream, delimiter='\t'):
                key = (dataset.field2token_id['user_id'].get(row[FIELDS[0]]),
                       dataset.field2token_id['item_id'].get(row[FIELDS[1]]),
                       np.float32(row[FIELDS[2]]), np.float32(row[FIELDS[3]]))
                if remaining[key] == 0:
                    raise ValueError(f'RecBole changed rows in the {label} partition')
                remaining[key] -= 1


def training_history(path):
    """Platform history uses seconds; retain exact source time before float32 conversion."""
    frame = pd.read_csv(path, sep='\t', usecols=[FIELDS[0], FIELDS[1], FIELDS[3]],
                        dtype={FIELDS[0]: str, FIELDS[1]: str, FIELDS[3]: np.float64}, keep_default_na=False)
    frame.columns = ['user_id', 'product_id', 'timestamp']
    frame['timestamp'] /= 1000
    frame = frame.groupby(['user_id', 'product_id'], as_index=False, sort=True)['timestamp'].min()
    fingerprint = history_fingerprint_sorted(frame.itertuples(index=False, name=None))
    return frame, fingerprint


class HistoryRows:
    def __init__(self, frame):
        self.frame = frame

    def __iter__(self):
        for user, item, timestamp in self.frame.itertuples(index=False, name=None):
            yield {'user_id': user, 'product_id': item, 'timestamp': timestamp}
