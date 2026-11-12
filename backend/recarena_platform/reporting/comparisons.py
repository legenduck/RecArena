"""Immutable paired conditions and atomic, idempotent generation of real Runs."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from recarena_contracts.admin import ExperimentCreate
from recarena_contracts.artifacts import canonical_hash
from recarena_contracts.layout import from_environment
from recarena_platform.db import catalog as catalog
from recarena_platform.db import runtime as db
from recarena_platform.environments import ensure_ready
from recarena_platform.ranking_client import RankingFailure
from recarena_platform.outcomes import Outcome, rejected
from recarena_platform.runs import create_run_in_session


def audit(session, action, target_id, document=None):
    session.add(db.OperatorAuditEvent(action=action,target_id=target_id,document=document or {}))


def comparison_context(environment):
    config = environment.config
    presentation = from_environment(config)
    return {'catalog':environment.dataset_snapshot_id, 'reviews':environment.review_snapshot_id,
        'history':environment.history_snapshot_id, 'history_fingerprint':config.get('history_fingerprint'),
        'candidate_scope': next(iter(presentation.ranking_sources.values())).policy.candidate_scope,
        'layout':presentation.layout.model_dump(mode='json'),
        'card_contract':'public-card-v1'}


def describe(session, experiment):
    conditions = session.scalars(select(db.ExperimentCondition).where(db.ExperimentCondition.experiment_id == experiment.id).order_by(db.ExperimentCondition.label))
    pairs = session.scalars(select(db.ExperimentPair).where(db.ExperimentPair.experiment_id == experiment.id).order_by(db.ExperimentPair.user_id, db.ExperimentPair.task_version_id))
    return {'id':experiment.id,'name':experiment.name,'config':experiment.config,'config_hash':experiment.config_hash,
        'warnings':experiment.warnings,
        'conditions':[{k:getattr(c,k) for k in ('id','label','environment_version_id')} for c in conditions],
        'pairs':[{k:getattr(p,k) for k in ('id','user_id','task_version_id')} for p in pairs]}


def validate_comparison(session, ranking, body):
    reference = None
    warnings = []
    for condition in body.conditions:
        environment = session.get(db.EnvironmentVersion, condition.environment_version_id)
        if environment is None or environment.state != 'PUBLISHED':
            raise ValueError('Condition requires a published environment')
        for pair in body.pairs:
            task = session.get(catalog.TaskVersion,pair.task_version_id)
            if task is None or task.dataset_snapshot_id != environment.dataset_snapshot_id or task.document['validation_status'] != 'VALIDATED':
                raise ValueError('Task is not validated for this catalog')
            ensure_ready(session,ranking,environment,pair.user_id)
        context = comparison_context(environment)
        if reference is None:
            reference = context
        else:
            for key in reference:
                if reference[key] != context[key]:
                    warnings.append({'condition':condition.label,'field':key,'message':'Non-policy comparison setting differs'})
        if body.preset == 'policy_comparison' and len(from_environment(environment.config).ranking_sources) != 1:
            warnings.append({'condition':condition.label,'field':'ranking_sources','message':'Basic comparison preset expects one ranking source'})
    return warnings


class ExperimentService:
    def __init__(self, engine, ranking):
        self.engine,self.ranking = engine,ranking

    def create(self, body):
        with Session(self.engine) as session, session.begin():
            try:
                warnings = validate_comparison(session,self.ranking,body)
            except (ValueError,KeyError,RankingFailure):
                return rejected('ARTIFACT_NOT_READY',422)
            config = body.model_dump(mode='json')
            experiment = db.Experiment(name=body.name,config=config,config_hash=canonical_hash(config),warnings=warnings)
            session.add(experiment)
            session.flush()
            for c in body.conditions:
                session.add(db.ExperimentCondition(experiment_id=experiment.id,label=c.label,environment_version_id=c.environment_version_id))
            for pair in body.pairs:
                session.add(db.ExperimentPair(experiment_id=experiment.id,user_id=pair.user_id,task_version_id=pair.task_version_id))
            audit(session,'experiment_created',experiment.id,{'config_hash':experiment.config_hash,'warnings':warnings})
            session.flush()
            return Outcome(describe(session,experiment))

    def generate(self, experiment_id):
        with Session(self.engine) as session, session.begin():
            experiment = session.scalar(select(db.Experiment).where(db.Experiment.id == experiment_id).with_for_update())
            if experiment is None:
                return rejected('RESULT_NOT_FOUND',404)
            if experiment.config_hash != canonical_hash(experiment.config):
                return rejected('ARTIFACT_MISMATCH',422)
            body = ExperimentCreate.model_validate(experiment.config)
            try:
                validate_comparison(session,self.ranking,body)
            except (ValueError,KeyError,RankingFailure):
                return rejected('ARTIFACT_NOT_READY',422)
            description = describe(session,experiment)
            results = []
            for condition in description['conditions']:
                for pair in description['pairs']:
                    for repetition,seed in enumerate(body.seeds,1):
                        comparison = {'experiment_id':experiment.id,'condition_id':condition['id'],
                            'pair_id':pair['id'],'repetition':repetition,'seed':seed}
                        existing = session.scalar(select(db.Run).where(db.Run.experiment_id == experiment.id,
                            db.Run.condition_id == condition['id'],db.Run.pair_id == pair['id'],db.Run.repetition == repetition))
                        if existing:
                            results.append({'run_id':existing.id,'state':existing.state,'already_created':True,**comparison})
                            continue
                        result = create_run_in_session(session,condition['environment_version_id'],pair['user_id'],
                            task_id=pair['task_version_id'],limits=body.limits.model_dump(),run_kind='research',
                            comparison=comparison,agent=body.agent.model_dump(mode='json'))
                        if result.error:
                            # No partial generation: every pair is checked before writes;
                            # an unexpected storage invariant failure rolls back the transaction.
                            raise RuntimeError('Validated comparison failed during Run creation')
                        results.append({**result.value,'already_created':False})
            audit(session,'experiment_runs_generated',experiment.id,{'created':sum(not r['already_created'] for r in results)})
            return Outcome({'experiment_id':experiment.id,'runs':results})
