from typing import Annotated, Literal
from pydantic import Field, field_validator, model_serializer, model_validator
from enum import Enum
from recarena_contracts.models import Contract
from .timestamps import DEFAULT_TAU, normalize_tau


class PolicyFamily(str, Enum):
    relevance = 'relevance'
    popularity = 'popularity'
    personalization = 'personalization'
    diversity = 'diversity'


IMPLEMENTATIONS = {
    PolicyFamily.relevance: 'lucene_bm25_v1',
    PolicyFamily.popularity: 'pop',
    PolicyFamily.personalization: 'bm25_bpr_v1',
    PolicyFamily.diversity: 'bm25_bpr_mmr_v1',
}
PROFILE_IMPLEMENTATION = 'bm25_profile_tfidf_v1'
CF_IMPLEMENTATION = 'bm25_cf_v1'


class PolicyConfig(Contract):
    family: PolicyFamily
    implementation_id: str
    delta_t: Annotated[int, Field(strict=True, ge=1)] | None = Field(
        default=30, description='Review window in days; null counts all supplied reviews before tau')
    tau: str = Field(default=DEFAULT_TAU, validate_default=True)
    weight: Annotated[float, Field(ge=0, le=1)] = .3  # BPR blend only; pop uses review counts directly
    combination: Literal['minmax', 'log_rank', 'bpr', 'cf'] = 'minmax'
    mmr_relevance_weight: Annotated[float, Field(ge=0, le=1)] = .7
    base_policy: Literal['personalization', 'relevance'] = 'relevance'
    allow_unknown_user_fallback: bool = False

    @field_validator('tau', mode='before')
    @classmethod
    def valid_tau(cls, value):
        return normalize_tau(value)

    @model_validator(mode='after')
    def implementation_matches_family(self):
        if self.implementation_id == CF_IMPLEMENTATION:
            if self.family != PolicyFamily.personalization or self.combination != 'cf':
                raise ValueError('CF reranking requires personalization with combination=cf')
            if self.model_fields_set & {'weight', 'mmr_relevance_weight', 'base_policy', 'delta_t', 'tau'}:
                raise ValueError('CF reranking uses model scores without a blend weight')
            return self
        if self.combination == 'cf':
            raise ValueError('combination=cf requires the CF implementation')
        if self.implementation_id == PROFILE_IMPLEMENTATION:
            if self.family != PolicyFamily.personalization:
                raise ValueError('Profile reranking requires the personalization family')
            if self.model_fields_set & {'weight', 'combination', 'mmr_relevance_weight',
                                        'base_policy', 'allow_unknown_user_fallback', 'delta_t', 'tau'}:
                raise ValueError('Profile reranking uses stored cosine scores without blending or fallback')
            return self
        if self.implementation_id != IMPLEMENTATIONS[self.family]:
            raise ValueError('Implementation does not match policy family')
        if self.combination != 'minmax' and self.family != PolicyFamily.personalization:
            raise ValueError('Non-default combination is only supported by personalization')
        if self.combination == 'bpr' and 'weight' in self.model_fields_set:
            raise ValueError('BPR-only ranking does not accept a blend weight')
        if self.family == PolicyFamily.popularity and self.model_fields_set & {
            'weight', 'mmr_relevance_weight', 'base_policy', 'allow_unknown_user_fallback', 'combination'
        }:
            raise ValueError('pop accepts delta_t and tau; it does not blend model scores')
        return self

    @model_serializer(mode='wrap')
    def active_settings(self, handler):
        value = handler(self)
        if self.implementation_id == CF_IMPLEMENTATION:
            return {key: value[key] for key in ('family', 'implementation_id', 'combination', 'allow_unknown_user_fallback')}
        if self.implementation_id == PROFILE_IMPLEMENTATION:
            return {key: value[key] for key in ('family', 'implementation_id')}
        if self.family == PolicyFamily.popularity:
            return {key: value[key] for key in ('family', 'implementation_id', 'delta_t', 'tau')}
        value.pop('delta_t', None)
        value.pop('tau', None)
        if self.combination == 'minmax':
            # Preserve the serialized configuration and identity of existing profiles.
            value.pop('combination', None)
        if self.combination == 'bpr':
            value.pop('weight', None)
        return value
