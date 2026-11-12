"""Select epochs on train/valid, refit BPR (default) or LightGCN on trainval, then export."""
from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
import shutil
import sys

import torch
import yaml
from recbole.config import Config
from recbole.data import create_dataset, data_preparation
from recbole.model.general_recommender import BPR, LightGCN
from recbole.trainer import Trainer
from recbole.utils import init_seed

from recarena_contracts.artifacts import digest, make_manifest, write_json
from .embeddings import export_model
from .inputs import (HistoryRows, inspect_partitions, snapshot_inputs, prepare_refit_inputs,
                     training_history, verify_partitions)

MODELS = {'BPR': BPR, 'LightGCN': LightGCN}
DEFAULTS = {
    'seed': 42, 'reproducibility': True, 'embedding_size': 64, 'epochs': 300,
    'train_batch_size': 2048, 'learner': 'adam', 'learning_rate': .001, 'weight_decay': 0.0,
    'train_neg_sample_args': {'distribution': 'uniform', 'sample_num': 1, 'dynamic': False},
    'eval_step': 1, 'stopping_step': 10, 'metrics': ['Recall', 'NDCG'], 'topk': [10, 20],
    'valid_metric': 'NDCG@10', 'valid_metric_bigger': True, 'use_gpu': True,
    'log_wandb': False, 'show_progress': False,
}
# These are controlled by the prepared-input boundary, not model tuning.
INPUT_SETTINGS = {
    'model', 'dataset', 'data_path', 'checkpoint_dir', 'benchmark_filename', 'load_col', 'unload_col',
    'USER_ID_FIELD', 'ITEM_ID_FIELD', 'RATING_FIELD', 'TIME_FIELD', 'field_separator',
    'eval_args', 'rm_dup_inter', 'val_interval', 'user_inter_num_interval', 'item_inter_num_interval',
    'filter_inter_by_user_or_item', 'unused_col', 'threshold', 'normalize_field', 'normalize_all',
    'alias_of_user_id', 'alias_of_item_id', 'additional_feat_suffix', 'save_dataset', 'save_dataloaders',
}


def train(data: Path, output: Path, *, catalog_id, history_id, model=None, dataset=None,
          train_split='auto', config_path=None, _selection_only=False):
    supplied = yaml.safe_load(Path(config_path).read_text()) if config_path else {}
    if not isinstance(supplied, dict) or set(supplied) - {'model', 'training'}:
        raise ValueError('Training config accepts model and training settings')
    model_name = model or supplied.get('model', 'BPR')
    if not isinstance(model_name, str) or model_name not in MODELS:
        raise ValueError('Supported models: BPR, LightGCN (default: BPR)')
    overrides = supplied.get('training', {})
    if not isinstance(overrides, dict) or INPUT_SETTINGS.intersection(overrides):
        raise ValueError('Training settings cannot override prepared inputs, fields or partition rules')
    settings = DEFAULTS | overrides
    if type(settings['use_gpu']) is not bool:
        raise ValueError('use_gpu must be true or false')
    if settings['use_gpu'] and not torch.cuda.is_available():
        raise ValueError('GPU training requested but CUDA is unavailable; check the driver and training installation, '
                         'or explicitly select training-cpu and set training.use_gpu: false')
    if type(settings['epochs']) is not int or settings['epochs'] < 1:
        raise ValueError('epochs must be a positive integer')
    if train_split not in ('auto', 'train', 'trainval'):
        raise ValueError('Choose auto, train or trainval')
    if train_split in ('auto', 'train') and settings['eval_step'] < 1:
        raise ValueError('train uses validation selection; eval_step must be positive')
    if train_split == 'trainval' and 'epochs' not in overrides:
        raise ValueError('trainval requires an explicit fixed epoch count in the training config')
    files, split_report = inspect_partitions(data, dataset, 'train' if train_split == 'auto' else train_split)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    training = output / 'training'
    training.mkdir()
    previous, argv = Path.cwd(), sys.argv
    logger = logging.getLogger()
    previous_handlers, previous_level = logger.handlers[:], logger.level
    handler = logging.FileHandler(output / 'training.log')
    logger.handlers, logger.level = [handler], logging.INFO
    trainer = None
    try:
        epoch_selection = None
        if train_split == 'auto':
            selection_directory = output / 'selection'
            selection_path = train(data, selection_directory, catalog_id=catalog_id, history_id=history_id,
                model=model_name, dataset=dataset, train_split='train', config_path=config_path, _selection_only=True)
            epoch_selection = json.loads(selection_path.read_text())
            selected_report = json.loads((selection_directory / 'training/split_report.json').read_text())
            atomic, files, split_report = prepare_refit_inputs(selection_directory, selected_report, training)
            settings['epochs'] = epoch_selection['selected_epochs']
            write_json(training / 'epoch_selection.json', epoch_selection)
        else:
            atomic = snapshot_inputs(files, split_report, training)
        write_json(training / 'split_report.json', split_report)
        settings.update({
            'data_path': str(atomic.parent), 'checkpoint_dir': str(output / 'checkpoints'),
            'benchmark_filename': split_report['benchmark_filename'],
            'load_col': {'inter': ['user_id', 'item_id', 'rating', 'timestamp']},
            'eval_args': {'split': {'RS': [.8, .1, .1]}, 'order': 'TO', 'group_by': None, 'mode': 'full'},
            'worker': 0, 'save_dataset': False, 'save_dataloaders': False,
        })
        if train_split in ('auto', 'trainval'):
            settings['eval_step'] = 0
        os.chdir(output)
        sys.argv = [argv[0]]  # RecBole must not reinterpret this command's CLI options.
        config = Config(model=model_name, dataset=split_report['dataset'], config_dict=settings)
        init_seed(config['seed'], config['reproducibility'])
        recbole_dataset = create_dataset(config)
        partitions = data_preparation(config, recbole_dataset)
        verify_partitions(recbole_dataset, partitions, atomic, split_report)
        train_data, valid_data, test_data = partitions
        instance = MODELS[model_name](config, train_data.dataset).to(config['device'])
        trainer = Trainer(config, instance)
        _, validation = trainer.fit(train_data, valid_data if train_split == 'train' else None,
                                    saved=True, show_progress=False)
        # Only this job's own generated checkpoint is loaded here.
        checkpoint = torch.load(trainer.saved_model_file, map_location=config['device'], weights_only=False)
        instance.load_state_dict(checkpoint['state_dict'])
        if isinstance(instance, LightGCN):
            instance.restore_user_e = instance.restore_item_e = None
        if _selection_only:
            # This intermediate model is never exported or evaluated on test.
            selected_epochs = int(checkpoint['epoch']) + 1
            if selected_epochs < 1 or validation is None:
                raise ValueError('Validation did not select a valid training epoch')
            shutil.copy2(trainer.saved_model_file, training / 'selected_checkpoint.pth')
            write_json(training / 'training_config.json', json.loads(json.dumps(config.final_config_dict, default=str)))
            selection_path = output / 'epoch_selection.json'
            write_json(selection_path, {'model': model_name, 'best_epoch': int(checkpoint['epoch']),
                'selected_epochs': selected_epochs, 'maximum_epochs': config['epochs'],
                'completed_epochs': len(trainer.train_loss_dict), 'training_losses': trainer.train_loss_dict,
                'validation_metric': config['valid_metric'], 'validation_metrics': dict(validation),
                'test_metrics': None, 'training_file': 'train', 'counts': split_report['counts'],
                'checkpoint_sha256': digest(training / 'selected_checkpoint.pth')})
            return selection_path
        test_metrics = trainer.evaluate(test_data, load_best_model=False, show_progress=False)
        history, fingerprint = training_history(atomic / files['train'].name)
        serving = output / 'serving'
        equivalence, users, items = export_model(instance, recbole_dataset, {'train': HistoryRows(history)}, serving)
        history_metadata = {
            'history_snapshot_id': history_id, 'catalog_snapshot_id': catalog_id,
            'interaction_count': len(history), 'source_training_event_count': split_report['counts']['train'],
            'fingerprint': fingerprint, 'timestamp_unit': 'seconds',
            'projection': 'unique_user_parent_with_earliest_exact_source_time_within_actual_train',
        }
        warnings = []
        trained_users, trained_items = history.user_id.nunique(), history.product_id.nunique()
        if trained_users < len(users) or trained_items < len(items):
            warnings.append('Untrained vocabulary rows are excluded from scoring by the support lists.')
        quality = {
            'model': model_name, 'best_epoch': int(checkpoint['epoch']),
            'selection': ('validation_then_trainval_refit' if train_split == 'auto'
                          else 'validation' if train_split == 'train' else 'fixed_epochs'),
            'epoch_selection': epoch_selection, 'trained_epochs': len(trainer.train_loss_dict),
            'validation_metrics': dict(validation) if validation is not None else None,
            'test_metrics': dict(test_metrics), 'training_losses': trainer.train_loss_dict,
            'stopping_reason': 'patience' if len(trainer.train_loss_dict) < config['epochs'] else 'epoch_limit',
            'support_coverage': {'users': trained_users / len(users), 'items': trained_items / len(items)},
            'warnings': warnings,
        }
        resolved = json.loads(json.dumps(config.final_config_dict, default=str))
        for name, value in [('training_config', resolved), ('split_report', split_report),
                            ('training_history', history_metadata), ('quality_report', quality),
                            ('validation_metrics', quality['validation_metrics']), ('test_metrics', dict(test_metrics))]:
            write_json(serving / f'{name}.json', value)
        for name in ('training_config', 'training_history', 'quality_report'):
            shutil.copy2(serving / f'{name}.json', training / f'{name}.json')
        shutil.copy2(trainer.saved_model_file, training / 'selected_checkpoint.pth')
        counts = {'users': len(users), 'items': len(items), **split_report['counts']}
        identity = {'model': model_name, 'training': settings, 'split': split_report}
        training_manifest = make_manifest(training, 'cf_training', identity,
            sources=[atomic / path.name for path in files.values()], parents=[catalog_id, history_id],
            counts=counts, warnings=warnings, source_scope='examples/recommendation/training')
        write_json(serving / 'training_manifest.json', training_manifest)
        manifest = make_manifest(serving, 'cf_serving', identity,
            parents=[catalog_id, history_id, training_manifest['artifact_id']], counts=counts,
            warnings=warnings, source_scope='examples/recommendation/training')
        write_json(output / 'result.json', {'status': 'complete', 'model': model_name,
            'artifact_id': manifest['artifact_id'], 'training_artifact_id': training_manifest['artifact_id'],
            'serving_path': str(serving), 'equivalence': equivalence, 'quality': quality})
        return serving
    except Exception as error:
        write_json(output / 'failed.json', {'status': 'failed', 'error': type(error).__name__, 'message': str(error)})
        raise
    finally:
        if trainer is not None:
            trainer.tensorboard.close()
        sys.argv = argv
        os.chdir(previous)
        handler.close()
        logger.handlers, logger.level = previous_handlers, previous_level


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', required=True, type=Path, help='Directory containing prepared general .inter files')
    parser.add_argument('--dataset', help='Dataset name; defaults to conversion.json or directory name')
    parser.add_argument('--model', choices=tuple(MODELS), help='Model; defaults to config model or BPR')
    parser.add_argument('--train-split', choices=('auto', 'train', 'trainval'), default='auto',
                        help='auto (default): select epochs on train/valid, then refit from scratch on trainval')
    parser.add_argument('--catalog', required=True)
    parser.add_argument('--history', required=True)
    parser.add_argument('--config', type=Path, help='Optional model/training YAML settings')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        print(train(args.data, args.output, catalog_id=args.catalog, history_id=args.history,
                    model=args.model, dataset=args.dataset, train_split=args.train_split,
                    config_path=args.config.resolve() if args.config else None))
    except (ValueError, OSError, KeyError) as error:
        parser.exit(1, f'Training failed: {error}\n')


if __name__ == '__main__':
    main()
