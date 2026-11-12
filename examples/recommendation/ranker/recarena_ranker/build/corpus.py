"""BM25 input projection owned by the optional example ranker."""
import argparse
from pathlib import Path

from recarena_contracts.models import Contract, ID, Product, Variant
from recarena_contracts.catalog import CatalogProducts
from recarena_contracts.artifacts import write_json

class SearchDocument(Contract):
    id: ID
    contents: str


class SearchCorpus(Contract):
    catalog_snapshot_id: ID
    documents: tuple[SearchDocument, ...]

PROJECTION_VERSION = 'title_features_description_categories_attributes'


def searchable_text(product: Product, variants: list[Variant]):
    parts = [product.title, *product.features, product.description, *product.categories]
    for key, value in sorted(product.attributes.items()):
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            parts.append(f'{key} {value}')
    return '\n'.join(dict.fromkeys(p.strip() for p in parts if p.strip()))


def search_document(product: Product, variants: list[Variant]):
    if product.product_status != 'active' or not any(v.is_purchasable and v.is_available for v in variants):
        return None
    return SearchDocument(id=product.product_id, contents=searchable_text(product, variants))


def project_catalog(products: CatalogProducts) -> SearchCorpus:
    variants = {}
    for variant in products.variants:
        variants.setdefault(variant.product_id, []).append(variant)
    documents = [document for product in products.products
                 if (document := search_document(product, variants.get(product.product_id, []))) is not None]
    return SearchCorpus(catalog_snapshot_id=products.catalog_snapshot_id, documents=documents)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--products', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    corpus = project_catalog(CatalogProducts.model_validate_json(args.products.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise SystemExit('Output exists; choose a new path')
    write_json(args.output, corpus.model_dump(mode='json'))
