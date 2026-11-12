"""Export the exact inference factors of BPR or LightGCN; no online training dependency."""
import numpy as np
import torch
from recbole.data.interaction import Interaction
from recbole.model.general_recommender import BPR, LightGCN
from recarena_contracts.artifacts import write_json


def export_model(model, dataset, splits, directory):
    directory.mkdir()
    users = list(map(str, dataset.field2id_token['user_id'][1:]))
    items = list(map(str, dataset.field2id_token['item_id'][1:]))
    model.eval()
    with torch.no_grad():
        if isinstance(model, LightGCN):
            user_tensor, item_tensor = model.forward()
            model_name, representation = 'LightGCN', 'graph_propagated'
        elif isinstance(model, BPR):
            user_tensor, item_tensor = model.user_embedding.weight, model.item_embedding.weight
            model_name, representation = 'BPR', 'learned_embeddings'
        else:
            raise ValueError('Only BPR and LightGCN exports are supported')
        user_factors = user_tensor.detach().cpu().numpy()[1:].astype(np.float32)
        item_factors = item_tensor.detach().cpu().numpy()[1:].astype(np.float32)
    if not users or not items:
        raise ValueError('Cannot export an empty vocabulary')
    write_json(directory / 'model.json', {'format': 'recarena-cf-factors-v1', 'model': model_name,
        'representation': representation, 'score': 'dot_product'})
    if not np.isfinite(user_factors).all() or not np.isfinite(item_factors).all():
        raise ValueError('Non-finite embedding values')
    np.save(directory / 'user_factors.npy', user_factors, allow_pickle=False)
    np.save(directory / 'item_factors.npy', item_factors, allow_pickle=False)
    write_json(directory / 'user_id_to_row.json', {u: i for i, u in enumerate(users)})
    write_json(directory / 'item_id_to_row.json', {p: i for i, p in enumerate(items)})
    for kind, field in [('user', 'user_id'), ('item', 'product_id')]:
        write_json(directory / f'trained_{kind}_ids.json', sorted({r[field] for r in splits['train']}))
    # Read the actual exported arrays to validate both serialization and row mappings.
    uf = np.load(directory / 'user_factors.npy', allow_pickle=False)
    itf = np.load(directory / 'item_factors.npy', allow_pickle=False)
    pair_count = len(users) * len(items)
    pairs = np.random.default_rng(42).choice(pair_count, min(1000, pair_count), replace=False)
    urows, irows = pairs // len(items), pairs % len(items)
    model.eval()
    with torch.no_grad():
        original = model.predict(Interaction({
            'user_id': torch.tensor(urows + 1, device=model.device),
            'item_id': torch.tensor(irows + 1, device=model.device),
        })).cpu().numpy()
    # Serving performs float64 arithmetic on float32 artifacts.
    exported = np.einsum('ij,ij->i', uf[urows].astype(np.float64), itf[irows].astype(np.float64))
    ok = bool(np.allclose(original, exported, atol=1e-5, rtol=1e-4))
    report = {'passed': ok, 'sample_count': len(pairs), 'seed': 42, 'atol': 1e-5, 'rtol': 1e-4,
              'max_absolute_error': float(np.max(np.abs(original - exported))),
              'includes_padding': False}
    write_json(directory / 'export_equivalence_report.json', report)
    if not ok:
        raise ValueError('RecBole/export prediction equivalence failed')
    return report, users, items
