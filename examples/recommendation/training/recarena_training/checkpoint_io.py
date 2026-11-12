"""Offline checkpoint loading with a fixed class allowlist, including protocol 4.

PyTorch 2.5's weights-only unpickler cannot parse protocol-4 FRAME opcodes.
This loader retains a restricted global lookup instead of unrestricted pickle
loading. It is used only by the offline researcher-checkpoint importer.
"""
from collections import OrderedDict
import pickle
from types import SimpleNamespace

from recbole.config import Config
from recbole.model.general_recommender import BPR
from recbole.utils import EvaluatorType, InputType, ModelType
import torch
from yaml.loader import FullLoader


_ALLOWED = {f'{value.__module__}.{value.__name__}': value for value in (
    Config, BPR, ModelType, InputType, EvaluatorType, FullLoader,
    OrderedDict, torch.device, torch._utils._rebuild_tensor_v2,
)}


class CheckpointUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        key = f'{module}.{name}'
        if key not in _ALLOWED:
            raise pickle.UnpicklingError(f'Checkpoint global is not allowed: {key}')
        return _ALLOWED[key]


def load_checkpoint(path):
    restricted = SimpleNamespace(__name__='recarena_restricted_checkpoint',
                                 Unpickler=CheckpointUnpickler)
    # torch's zip reader handles only its own storage types and persistent IDs;
    # all remaining globals go through CheckpointUnpickler.find_class.
    return torch.load(path, map_location='cpu', weights_only=False,
                      pickle_module=restricted)
