"""Researcher-controlled registration and immutable comparison configuration."""
from typing import Annotated, Literal

from pydantic import Field, JsonValue, model_validator

from .models import Contract, ID, Interaction, RunLimits


class CatalogImportRequest(Contract):
    bundle_path: Annotated[str, Field(min_length=1)]


class ExportCreate(Contract):
    experiment_id: ID | None = None
    run_ids: tuple[ID, ...] | None = None
    filters: dict[str, str] | None = None

    @model_validator(mode='after')
    def one_scope(self):
        if sum(v is not None for v in (self.experiment_id,self.run_ids,self.filters)) != 1:
            raise ValueError('Select one export scope')
        if self.run_ids is not None and not self.run_ids:
            raise ValueError('Select at least one rollout')
        if self.filters is not None and set(self.filters)-{'run_id','user_id','requested_policy','applied_policy','agent_label','external_task_id','client_run_id','state','run_kind','recording_method'}:
            raise ValueError('Unknown rollout filter')
        return self


class HistoryImportRequest(Contract):
    history_snapshot_id: ID
    catalog_snapshot_id: ID
    user_ids: Annotated[tuple[ID, ...], Field(min_length=1)]
    interactions: tuple[Interaction, ...]
    provenance: dict[str, JsonValue]

    @model_validator(mode='after')
    def fixed_history(self):
        if len(set(self.user_ids)) != len(self.user_ids):
            raise ValueError('Duplicate user IDs')
        seen = set()
        for row in self.interactions:
            key = (row.user_id,row.product_id)
            if row.history_snapshot_id != self.history_snapshot_id or row.user_id not in self.user_ids or key in seen:
                raise ValueError('Invalid or duplicate historical interaction')
            seen.add(key)
        return self


class AgentDeclaration(Contract):
    name: Annotated[str, Field(min_length=1)]
    version: str | None = None
    model: str | None = None
    settings: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode='after')
    def no_credentials(self):
        def visit(value):
            if isinstance(value,dict):
                for key,item in value.items():
                    if key.lower().replace('-','_') in {'api_key','apikey','access_token','authorization','cookie','password','secret','token'}:
                        raise ValueError('Credentials do not belong in recorded agent settings')
                    visit(item)
            elif isinstance(value,list):
                for item in value:
                    visit(item)
        visit(self.settings)
        return self


class ComparisonCondition(Contract):
    label: Annotated[str, Field(min_length=1, max_length=200)]
    environment_version_id: ID


class UserTaskPair(Contract):
    user_id: ID
    task_version_id: ID


class ExperimentCreate(Contract):
    name: Annotated[str, Field(min_length=1, max_length=200)]
    preset: Literal['policy_comparison', 'custom'] = 'policy_comparison'
    conditions: Annotated[tuple[ComparisonCondition, ...], Field(min_length=1)]
    pairs: Annotated[tuple[UserTaskPair, ...], Field(min_length=1)]
    agent: AgentDeclaration
    limits: RunLimits = Field(default_factory=RunLimits)
    repetitions: Annotated[int, Field(strict=True, ge=1)] = 1
    seeds: tuple[Annotated[int, Field(strict=True, ge=-(2**63), le=2**63-1)], ...] = (42,)

    @model_validator(mode='after')
    def comparison_keys(self):
        if len({c.label for c in self.conditions}) != len(self.conditions):
            raise ValueError('Duplicate condition label')
        if len({(p.user_id,p.task_version_id) for p in self.pairs}) != len(self.pairs):
            raise ValueError('Duplicate user-task pair')
        if len(self.seeds) != self.repetitions:
            raise ValueError('Provide one recorded seed per repetition')
        return self
