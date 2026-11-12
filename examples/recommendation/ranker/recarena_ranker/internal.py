"""Internal baseline retrieval/scoring types; not a platform HTTP contract."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints, model_validator
from recarena_contracts.models import Contract, ID, Score

class RetrievalConfig(Contract):
    implementation: Literal['pyserini_lucene'] = 'pyserini_lucene'
    candidate_k: Annotated[int, Field(strict=True, ge=1)] = 200
    k1: Annotated[float, Field(gt=0)] = 1.2
    b: Annotated[float, Field(ge=0, le=1)] = .75
    language: Literal['en'] = 'en'
    query_expansion: Literal[False] = False


class RankingRecord(BaseModel):
    """Typed internal values; the HTTP boundary owns full JSON serialization.

    All numeric fields, including nested JsonValue floats, still reject NaN/Inf.
    Avoid serializing every internal item just to validate its typed fields.
    """
    model_config = ConfigDict(extra='forbid', frozen=True, allow_inf_nan=False)


class Candidate(RankingRecord):
    product_id: ID
    retrieval_rank: Annotated[int, Field(strict=True, ge=1)]
    bm25_score: Score


class CandidateSet(RankingRecord):
    candidate_set_id: ID
    catalog_snapshot_id: ID
    index_artifact_id: ID
    query_raw: str
    query_normalized: Annotated[str, Field(min_length=1, max_length=512)]
    retrieval_config_hash: Annotated[str, StringConstraints(pattern=r'^[0-9a-f]{64}$')]
    candidates: tuple[Candidate, ...]

    @model_validator(mode='after')
    def unique_candidates(self):
        if len({i.product_id for i in self.candidates}) != len(self.candidates):
            raise ValueError('Duplicate candidate IDs')
        if [i.retrieval_rank for i in self.candidates] != list(range(1, len(self.candidates) + 1)):
            raise ValueError('Candidate retrieval ranks must be consecutive and ordered')
        return self


class RankedItem(RankingRecord):
    product_id: ID
    retrieval_rank: Annotated[int, Field(strict=True, ge=1)]
    final_rank: Annotated[int, Field(strict=True, ge=1)]
    final_score: Score | None = None
    score_components: dict[str, Score | None]
    signal_missing_flags: dict[str, bool] = Field(default_factory=dict)


class RankedResult(RankingRecord):
    candidate_set_id: ID
    policy_version_id: ID
    model_artifact_ids: tuple[ID, ...] = ()
    ranked_items: tuple[RankedItem, ...]
    diagnostics: dict[str, JsonValue] = Field(default_factory=dict)

    def validate_candidates(self, candidates: CandidateSet):
        expected = {i.product_id: i.retrieval_rank for i in candidates.candidates}
        if self.candidate_set_id != candidates.candidate_set_id:
            raise ValueError('Candidate set mismatch')
        if len(self.ranked_items) != len(expected) or {i.product_id for i in self.ranked_items} != set(expected):
            raise ValueError('Ranking must preserve every candidate exactly once')
        if [i.final_rank for i in self.ranked_items] != list(range(1, len(expected) + 1)):
            raise ValueError('Invalid final ranks')
        if any(i.retrieval_rank != expected[i.product_id] for i in self.ranked_items):
            raise ValueError('Changed retrieval rank')
        return self
