from sqlalchemy import select

from recarena_platform.db import catalog as db


def validate_task_utility(session,task):
    spec=task.optional_utility_spec
    if spec is None:
        return
    variants=list(session.scalars(select(db.Variant).where(db.Variant.dataset_snapshot_id==task.catalog_snapshot_id,
        db.Variant.is_purchasable.is_(True),db.Variant.is_available.is_(True))))
    choices={(v.product_id,v.variant_id,q) for v in variants for q in spec.quantity_domain}
    specified={(e.product_id,e.variant_id,e.quantity) for e in spec.entries}
    if not specified.issubset(choices):
        raise ValueError('Utility references an invalid/unavailable selection')
    if spec.reference_scope=='entire_catalog' and specified!=choices:
        raise ValueError('Entire-catalog utility must cover every purchasable variant in its declared quantity domain')
