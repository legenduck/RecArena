from contextlib import asynccontextmanager, contextmanager
import fcntl
import json
import os
from pathlib import Path
import secrets
from threading import RLock
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response

from recarena_contracts.artifacts import canonical_hash, digest, verify_manifest
from pydantic import BaseModel, Field
from ..config import PolicyConfig, PROFILE_IMPLEMENTATION

class ArtifactRegisterRequest(BaseModel):
    manifest_path: str = Field(min_length=1)
from recarena_contracts.http import RecommendationRequest, RecommendationResponse, PolicyValidationRequest
from ..profiles import PolicyProfile, apply_startup_settings
from ..internal import CandidateSet as InternalCandidates
from .policies import REGISTRY, PolicyFailure, rank as rank_policy, validate_config, required_artifacts
from .artifact_registry import ScoringArtifacts
from .retrieval import Retriever, normalize_query


class IndexRegistry:
    def __init__(self, config_path):
        self.indices = {}
        self.lock = RLock()
        self.scoring = ScoringArtifacts({})
        self.registration_file = Path(os.environ.get('RECARENA_RANKER_REGISTRATIONS', 'configs/local/ranker-registrations.json'))
        config = json.loads(Path(config_path).read_text())
        for key in ('indices','bpr','cf','review_timestamps','tfidf','profile_scores'):
            for filename in config.get(key,[]):
                self.load_one(Path(filename))
        self.profiles = {}
        for value in config.get('policies', []):
            profile = apply_startup_settings(PolicyProfile.model_validate(value),
                k=int(os.environ['RECARENA_BM25_K']) if os.environ.get('RECARENA_BM25_K') else None,
                delta_t=int(os.environ['RECARENA_POP_DELTA_T']) if os.environ.get('RECARENA_POP_DELTA_T') else None,
                tau=os.environ.get('RECARENA_POP_TAU') or None,
                personal_lambda=float(os.environ['RECARENA_PERSONAL_LAMBDA']) if os.environ.get('RECARENA_PERSONAL_LAMBDA') else None,
                div_lambda=float(os.environ['RECARENA_DIV_LAMBDA']) if os.environ.get('RECARENA_DIV_LAMBDA') else None)
            key = (profile.policy_id, profile.version)
            if key in self.profiles and self.profiles[key] != profile:
                raise ValueError('Duplicate policy version with different configuration')
            self.profiles[key] = profile
        self.registrations = []
        self._registration_revision = None
        self.refresh_registrations()
        if not self.indices:
            raise ValueError('No verified index registered')

    @staticmethod
    def _revision(stat):
        return stat.st_dev, stat.st_ino, stat.st_mtime_ns, stat.st_size

    def refresh_registrations(self):
        """Observe atomic registrations made by other workers before serving a request."""
        try:
            revision = self._revision(self.registration_file.stat())
        except (FileNotFoundError, NotADirectoryError):
            if self.registrations:
                raise ValueError('Removing runtime registrations requires a restart')
            return
        if revision == self._registration_revision:
            return
        with self.lock:
            # fstat identifies the version actually read even if another writer replaces the path.
            with self.registration_file.open() as stream:
                revision = self._revision(os.fstat(stream.fileno()))
                if revision == self._registration_revision:
                    return
                records = json.load(stream)
            if not isinstance(records, list):
                raise ValueError('Invalid runtime registrations')
            identifiers = [record['artifact_id'] for record in records]
            if len(identifiers) != len(set(identifiers)):
                raise ValueError('Duplicate runtime registration')
            if not {r['artifact_id'] for r in self.registrations}.issubset(identifiers):
                raise ValueError('Removing runtime registrations requires a restart')
            previous_indices, previous_scoring = set(self.indices), set(self.scoring.items)
            try:
                for record in records:
                    if record in self.registrations:
                        continue
                    path = Path(record['manifest_path'])
                    if digest(path) != record['sha256'] or self.load_one(path)['artifact_id'] != record['artifact_id']:
                        raise ValueError('Persisted registration no longer matches immutable artifact')
            except (ValueError, OSError, KeyError, TypeError):
                for identifier in set(self.indices) - previous_indices:
                    self.indices.pop(identifier)[1].close()
                for identifier in set(self.scoring.items) - previous_scoring:
                    self.scoring.items.pop(identifier)
                raise
            self.registrations = records
            self._registration_revision = revision

    @contextmanager
    def registration_writer(self):
        # Native and container workers share this directory. Do not lose another
        # process's registration when replacing the JSON snapshot.
        self.registration_file.parent.mkdir(parents=True, exist_ok=True)
        lock = self.registration_file.with_name(self.registration_file.name + '.lock')
        fd = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def load_one(self, path):
        manifest = verify_manifest(path)
        identifier,kind = manifest['artifact_id'],manifest['artifact_type']
        existing = self.indices[identifier][0] if identifier in self.indices else (
            self.scoring.items[identifier].manifest if identifier in self.scoring.items else None)
        if existing:
            if existing != manifest:
                raise ValueError('Artifact ID is immutable')
            return manifest
        if kind == 'lucene_index':
            if len(manifest['parent_artifact_ids']) != 1:
                raise ValueError('Invalid index lineage')
            self.indices[identifier] = (manifest,Retriever(path.parent/'index'))
        elif kind in ('bpr_serving','cf_serving','review_timestamps','tfidf','profile_scores'):
            key = {'bpr_serving': 'bpr', 'cf_serving': 'cf'}.get(kind, kind)
            loaded = ScoringArtifacts({key:[str(path)]})
            self.scoring.items.update(loaded.items)
        else:
            raise ValueError('Artifact is not a runtime ranking type')
        return manifest

    def register(self,path):
        path = path.resolve()
        root = Path(os.environ.get('RECARENA_ARTIFACT_ROOT','artifacts')).resolve()
        if not path.is_relative_to(root):
            raise ValueError('Manifest outside prepared artifact root')
        with self.lock, self.registration_writer():
            self.refresh_registrations()
            identifier = verify_manifest(path)['artifact_id']
            previously_loaded = identifier in self.indices or identifier in self.scoring.items
            manifest = self.load_one(path)
            record = {'manifest_path':str(path),'artifact_id':manifest['artifact_id'],'sha256':digest(path)}
            registrations = [r for r in self.registrations if r['artifact_id'] != record['artifact_id']] + [record]
            temporary = self.registration_file.with_name(self.registration_file.name+'.'+uuid4().hex+'.tmp')
            try:
                self.registration_file.parent.mkdir(parents=True,exist_ok=True)
                with temporary.open('x') as stream:
                    json.dump(registrations,stream,sort_keys=True,indent=2,allow_nan=False)
                    stream.flush()
                    os.fsync(stream.fileno())
                temporary.replace(self.registration_file)
            except OSError:
                if not previously_loaded:
                    self.scoring.items.pop(identifier,None)
                    if identifier in self.indices:
                        self.indices.pop(identifier)[1].close()
                raise
            finally:
                if temporary.is_file():
                    temporary.unlink()
            self.registrations = registrations
            self._registration_revision = None
            return manifest

    def check(self, index_id, catalog_id):
        if index_id not in self.indices:
            raise HTTPException(503, 'ARTIFACT_NOT_READY')
        manifest, searcher = self.indices[index_id]
        if manifest['parent_artifact_ids'] != [catalog_id]:
            raise HTTPException(409, 'ARTIFACT_MISMATCH')
        return manifest, searcher

    def close(self):
        for _, searcher in self.indices.values():
            searcher.close()


@asynccontextmanager
async def lifespan(app):
    if not os.environ.get('RECARENA_INTERNAL_TOKEN'):
        raise RuntimeError('RECARENA_INTERNAL_TOKEN is required')
    app.state.registry = IndexRegistry(os.environ['RECARENA_RANKER_CONFIG'])
    yield
    app.state.registry.close()


app = FastAPI(title='RecArena Internal Ranking', lifespan=lifespan)


@app.middleware('http')
async def request_identity(request: Request, call_next):
    request.state.request_id = str(uuid4())
    response = await call_next(request)
    response.headers['X-Request-ID'] = request.state.request_id
    return response


@app.exception_handler(HTTPException)
async def http_error(request, error):
    return JSONResponse(status_code=error.status_code, content={'error': {'code': str(error.detail),
        'message': str(error.detail), 'request_id': request.state.request_id, 'retryable': error.status_code >= 500}})


@app.exception_handler(RequestValidationError)
async def invalid_request(request, error):
    return await http_error(request, HTTPException(422, 'INVALID_INPUT'))


def authorize(authorization: str | None = Header(default=None)):
    expected = os.environ.get('RECARENA_INTERNAL_TOKEN', '')
    if not expected or not secrets.compare_digest(authorization or '', 'Bearer ' + expected):
        raise HTTPException(401, 'INVALID_SESSION')
    try:
        app.state.registry.refresh_registrations()
    except (ValueError, OSError, KeyError, TypeError):
        raise HTTPException(503, 'ARTIFACT_NOT_READY') from None


@app.get('/health/ready')
def ready():
    try:
        app.state.registry.refresh_registrations()
    except (ValueError, OSError, KeyError, TypeError):
        raise HTTPException(503, 'ARTIFACT_NOT_READY') from None
    return {'ready': bool(app.state.registry.indices)}


@app.get('/internal/v1/artifacts/status', dependencies=[Depends(authorize)])
def status():
    with app.state.registry.lock:
        return {'ready': True, 'indices': [m for m, _ in app.state.registry.indices.values()],
                'supported_policies': [family.value for family in REGISTRY],
                'scoring_artifacts': [item.manifest for item in app.state.registry.scoring.items.values()],
                'model_reports': {identifier:item.quality_report for identifier,item in app.state.registry.scoring.items.items() if hasattr(item,'quality_report')},
                'training_manifests':[item.training_manifest for item in app.state.registry.scoring.items.values() if getattr(item,'training_manifest',None)]}


@app.post('/internal/v1/artifacts/register', dependencies=[Depends(authorize)])
def register_artifact(body: ArtifactRegisterRequest):
    try:
        manifest = app.state.registry.register(Path(body.manifest_path))
    except (ValueError,OSError,KeyError):
        raise HTTPException(422,'ARTIFACT_NOT_READY')
    return {'ready':True,'manifest':manifest}


@app.get('/internal/v1/policies', dependencies=[Depends(authorize)])
def policies():
    return [profile.definition() for profile in app.state.registry.profiles.values()]


def resolve(body):
    profile = app.state.registry.profiles.get((body.policy.policy_id, body.policy.version))
    if profile is None:
        raise HTTPException(422, 'UNKNOWN_POLICY_VERSION')
    if profile.definition(body.policy.service_id).policy != body.policy or profile.catalog_snapshot_id != body.catalog_snapshot_id:
        raise HTTPException(409, 'POLICY_CONTEXT_MISMATCH')
    app.state.registry.check(profile.index_artifact_id, body.catalog_snapshot_id)
    return profile


@app.post('/internal/v1/policies/validate', dependencies=[Depends(authorize)])
def validate(body: PolicyValidationRequest):
    profile = resolve(body)
    try:
        policy = profile.configuration
        if body.strict_user:
            policy = policy.model_copy(update={'allow_unknown_user_fallback': False})
        REGISTRY[policy.family].validate_config(policy, body.user, body.catalog_snapshot_id,
            app.state.registry.scoring.select(profile.artifact_ids))
    except (PolicyFailure, ValueError) as error:
        raise HTTPException(422, str(error))
    return {'ready': True, 'policy': body.policy}


@app.post('/internal/v1/recommend', response_model=RecommendationResponse, dependencies=[Depends(authorize)])
def recommend(body: RecommendationRequest):
    profile = resolve(body)
    query = normalize_query(body.query)
    registry = app.state.registry
    try:
        if body.candidates is None:
            _, searcher = registry.check(profile.index_artifact_id, body.catalog_snapshot_id)
            with registry.lock:
                searcher.searcher.set_bm25(profile.retrieval.k1, profile.retrieval.b)
                rows = searcher.retrieve(query, profile.retrieval.candidate_k)
            candidate_id = str(uuid4())
            internal_rows = rows
            candidates = {'candidate_set_id': candidate_id, 'catalog_snapshot_id': body.catalog_snapshot_id,
                'candidate_scope': profile.candidate_scope, 'query_raw': body.query, 'query_normalized': query,
                'candidates': [{'product_id': row['product_id'], 'retrieval_rank': row['retrieval_rank'],
                    'metadata': {'bm25_score': row['bm25_score']}} for row in rows]}
        else:
            candidates = body.candidates
            if (candidates.catalog_snapshot_id != body.catalog_snapshot_id or
                candidates.candidate_scope != profile.candidate_scope or candidates.query_raw != body.query or
                candidates.query_normalized != query or len(candidates.candidates) > profile.retrieval.candidate_k):
                raise ValueError('Candidate context mismatch')
            candidate_id = candidates.candidate_set_id
            internal_rows = [{'product_id': row.product_id, 'retrieval_rank': row.retrieval_rank,
                'bm25_score': row.metadata['bm25_score']} for row in candidates.candidates]
        internal = InternalCandidates(candidate_set_id=candidate_id,
            catalog_snapshot_id=body.catalog_snapshot_id, index_artifact_id=profile.index_artifact_id,
            query_raw=body.query, query_normalized=query,
            retrieval_config_hash=canonical_hash(profile.retrieval.model_dump(mode='json')),
            candidates=internal_rows)
        ranked = REGISTRY[profile.configuration.family].rank(internal, body.user, profile.configuration,
            body.policy_version_id, registry.scoring.select(profile.artifact_ids))
        value = ranked.model_dump(mode='json')
        if profile.configuration.implementation_id == PROFILE_IMPLEMENTATION:
            value['diagnostics']['policy_name'] = profile.policy_id
        value['provenance'] = {'model_artifact_ids': value.pop('model_artifact_ids'),
            'index_artifact_id': profile.index_artifact_id, 'configuration': profile.configuration.model_dump(mode='json')}
        # Validate the complete public contract here, inside the existing error
        # boundary. Returning its encoded JSON avoids FastAPI validating and
        # rebuilding the same nested objects a second time.
        response = RecommendationResponse(policy=body.policy, candidates=candidates, ranking=value)
        return Response(content=response.model_dump_json(), media_type='application/json')
    except (KeyError, ValueError) as error:
        raise HTTPException(503, 'POLICY_EXECUTION_FAILED') from error
