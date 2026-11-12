"""Run-owned shopping queries; public responses are explicit allowlists."""
from contextlib import contextmanager
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from recarena_contracts.artifacts import canonical_hash
from recarena_contracts.http import (ProductCard, ProductDetail, PublicSelection, PublicVariant,
                                    RecommendationRequest, ReviewsResponse, SearchResponse)
from recarena_contracts.models import UserContext
from recarena_contracts.layout import from_environment
from recarena_contracts.text import normalize_query
from recarena_platform.db import catalog as catalog
from recarena_platform.db import runtime as db
from recarena_platform.ranking_client import RankingFailure
from recarena_platform.shopping.results import project
from recarena_platform.catalog.queries import CatalogRepository
from recarena_platform.outcomes import Outcome, rejected
from recarena_platform.runs import guard_running, finish
from recarena_platform.events import record_event
from recarena_platform.contexts import lock_context
from recarena_platform.sessions import SessionService
from recarena_platform.request_context import image_urls


class ShopService:
    def __init__(self, engine, ranking, request_id=None):
        self.engine, self.ranking = engine, ranking
        self.request_id = request_id or str(uuid4())

    def _event(self, session, run, name, payload, source='platform_server', *, request_id=None, schema_version='1.0'):
        record_event(session, run, name, payload, source=source, request_id=request_id or self.request_id,
            schema_version=schema_version)

    @contextmanager
    def _transaction(self, session=None):
        """Reuse the browser read operation's transaction, or own one for direct callers."""
        if session is not None:
            yield session
        else:
            with Session(self.engine) as session, session.begin():
                yield session

    def session_info(self, credential, *, present=None):
        return SessionService(self.engine).inspect(credential, present=present)

    def _prior_search(self, session, run, body, present=None):
        prior = session.scalar(select(db.ResultSnapshot).where(db.ResultSnapshot.context_id == run.id,
            db.ResultSnapshot.client_request_id == str(body.client_request_id)))
        if prior:
            if prior.document['query_raw'] != body.query:
                return rejected('IDEMPOTENCY_CONFLICT')
            return self._page(session, run, prior, 1, present=present)
        return None

    def search(self, credential, body, *, prepare=None, present=None):
        # Commit only the request identity/submission before waiting on the provider.
        # The context is immutable; no ORM object or checked-out connection crosses
        # the HTTP call. The existing receipt ledger deduplicates submissions even
        # if concurrent retries compute the same request before a snapshot exists.
        with Session(self.engine) as session, session.begin():
            if prepare:
                run, body, error = prepare(session)
            else:
                run, error = lock_context(session, credential, body.context_id)
            if error:
                return error
            request_key = str(body.client_request_id)
            request_hash = canonical_hash({'query': body.query})
            if error := guard_running(session, run):
                return error
            if not run.user_id:
                return rejected('USER_REQUIRED', 401)
            if prior := self._prior_search(session, run, body, present):
                return prior
            submitted = session.get(db.ShopActionReceipt, (run.id, 'search_submission', request_key))
            if submitted and submitted.request_hash != request_hash:
                return rejected('IDEMPOTENCY_CONFLICT')
            environment = session.get(db.EnvironmentVersion, run.environment_version_id)
            config = environment.config
            catalog_id, user_id, history_id = environment.dataset_snapshot_id, run.user_id, run.history_snapshot_id
            if submitted is None:
                if run.run:
                    run.run.search_count += 1
                self._event(session, run, 'search_submitted', {'query': body.query, 'client_request_id': request_key})
                submitted = db.ShopActionReceipt(context_id=run.id, action='search_submission',
                    request_key=request_key, request_hash=request_hash,
                    response={'value': {'request_id': self.request_id}, 'error': None, 'status': 200})
                session.add(submitted)
            submission_request_id = submitted.response['value']['request_id']

        failed = False
        try:
            presentation = from_environment(config)
            rankings = {}
            candidates = None
            for source_id, source in presentation.ranking_sources.items():
                result = self.ranking.recommend(RecommendationRequest(query=body.query,
                    catalog_snapshot_id=catalog_id, candidates=candidates,
                    user=UserContext(user_id=user_id, history_snapshot_id=history_id),
                    policy=source.policy, policy_version_id=source.policy_version_id))
                candidates = result.candidates
                rankings[source_id] = result.ranking
        except (RankingFailure, ValidationError, KeyError, ValueError):
            failed = True

        # Reacquire the original ownership/state locks before any result or failure
        # is committed. A late provider response cannot replace a terminal state or
        # attach to the login's newer context. The first completed retry wins.
        with Session(self.engine) as session, session.begin():
            run, error = lock_context(session, credential, body.context_id)
            if error:
                return error
            if error := guard_running(session, run):
                return error
            if prior := self._prior_search(session, run, body, present):
                return prior
            try:
                if failed:
                    raise RankingFailure('Recommendation request failed')
                identifiers = {item.product_id for item in candidates.candidates}
                available = set(session.scalars(select(catalog.Variant.product_id).where(
                    catalog.Variant.dataset_snapshot_id == catalog_id,
                    catalog.Variant.product_id.in_(identifiers), catalog.Variant.is_available,
                    catalog.Variant.is_purchasable).distinct()))
                if available != identifiers:
                    raise RankingFailure('Recommendation refers to an unavailable catalog product')
            except (RankingFailure, ValidationError, KeyError, ValueError):
                if run.run:
                    finish(session, run, 'ERROR', 'run_failed')
                else:
                    self._event(session, run, 'environment_error', {'code':'POLICY_EXECUTION_FAILED'})
                return rejected('POLICY_EXECUTION_FAILED', 503)
            if error := guard_running(session, run):
                return error
            candidate_record = db.CandidateSet(id=candidates.candidate_set_id, document=candidates.model_dump(mode='json'))
            session.add(candidate_record)
            session.flush()
            snapshot = db.ResultSnapshot(run_id=run.run_id, context_id=run.id, candidate_set_id=candidates.candidate_set_id,
                client_request_id=request_key, document={'query_raw': body.query,
                    'query': candidates.query_normalized, 'presentation': presentation.model_dump(mode='json'),
                    'rankings': {key:value.model_dump(mode='json') for key,value in rankings.items()}})
            session.add(snapshot)
            session.flush()
            self._event(session, run, 'candidate_set_used', {'candidate_set_id':candidates.candidate_set_id,
                'result_snapshot_id':snapshot.id}, 'ranking_server',request_id=submission_request_id,schema_version='2.0')
            for source_id in rankings:
                self._event(session, run, 'ranking_computed', {'result_snapshot_id':snapshot.id,
                    'source_id':source_id}, 'ranking_server',request_id=submission_request_id,schema_version='2.0')
            return self._page(session, run, snapshot, 1, present=present)

    def _page(self, session, run, snapshot, page, section_pages=None, only_block=None, filters=None, *, present=None):
        return project(session, run, snapshot, page, section_pages or {}, self.request_id, only_block, filters,
            present=present)

    def results(self, credential, snapshot_id, page, section_pages=None, only_block=None, filters=None,
                *, session=None, scope=None, present=None):
        with self._transaction(session) as session:
            snapshot = session.get(db.ResultSnapshot, snapshot_id)
            if snapshot is None:
                return rejected('RESULT_NOT_FOUND', 404)
            run, error = (scope, None) if scope is not None else lock_context(session, credential, snapshot.context_id)
            if error:
                return error
            if run.id != snapshot.context_id:
                return rejected('CROSS_SESSION_ACCESS_DENIED', 403)
            if error := guard_running(session, run):
                return error
            return self._page(session, run, snapshot, page, section_pages, only_block, filters, present=present)

    def detail(self, credential, product_id, origin=None, context_id=None, *, session=None, scope=None):
        with self._transaction(session) as session:
            run, error = (scope, None) if scope is not None else lock_context(session, credential, context_id)
            if error:
                return error
            if error := guard_running(session, run):
                return error
            if origin:
                placement = session.get(db.Placement, origin)
                if placement is None or placement.context_id != run.id or placement.product_id != product_id:
                    return rejected('CROSS_RUN_ACCESS_DENIED', 403)
            environment = session.get(db.EnvironmentVersion, run.environment_version_id)
            repo = CatalogRepository(session, environment.dataset_snapshot_id, environment.review_snapshot_id)
            try:
                product = repo.product(product_id)
            except KeyError:
                return rejected('RESULT_NOT_FOUND', 404)
            variants = repo.variants(product_id)
            state = session.get(db.ProductViewState, (run.id, product_id))
            selection = PublicSelection(variant_id=state.variant_id, quantity=state.quantity) if state else None
            self._event(session, run, 'product_detail_served', {'product_id': product_id, 'origin_placement_id': origin})
            return Outcome(ProductDetail(context_id=run.id, request_id=self.request_id, product_id=product_id, title=product.title,
                brand=product.brand, description=product.description, features=product.features, categories=product.categories,
                attributes=product.attributes, image_urls=image_urls(environment.dataset_snapshot_id,
                    remote=product.image_urls, local=product.image_asset_ids, placeholder=True),
                rating=product.display_rating, review_count=product.display_review_count,
                rating_distribution=repo.rating_distribution(product_id),
                variants=[PublicVariant(variant_id=v.variant_id, option_values=v.option_values,
                    attributes_override=v.attributes_override, unit_price_minor=v.unit_price_minor, currency=v.currency,
                    image_urls=image_urls(environment.dataset_snapshot_id, remote=v.image_urls, local=v.image_asset_ids),
                    is_available=v.is_available, is_purchasable=v.is_purchasable) for v in variants], selection=selection).model_dump(mode='json'))

    def reviews(self, credential, product_id, offset, limit=5, context_id=None, *, session=None, scope=None):
        if offset < 0 or not 1 <= limit <= 50:
            return rejected('INVALID_INPUT', 422)
        with self._transaction(session) as session:
            run, error = (scope, None) if scope is not None else lock_context(session, credential, context_id)
            if error:
                return error
            if error := guard_running(session, run):
                return error
            environment = session.get(db.EnvironmentVersion, run.environment_version_id)
            repo = CatalogRepository(session, environment.dataset_snapshot_id, environment.review_snapshot_id)
            try:
                repo.product(product_id)
            except KeyError:
                return rejected('RESULT_NOT_FOUND', 404)
            reviews = repo.reviews(product_id, offset, limit + 1)
            self._event(session, run, 'reviews_served', {'product_id': product_id, 'offset': offset,
                'review_ids': [r.review_id for r in reviews[:limit]]})
            return Outcome(ReviewsResponse(context_id=run.id, request_id=self.request_id, reviews=reviews[:limit], has_more=len(reviews) > limit).model_dump(mode='json'))
