"""HTTP-only policy boundary. No knowledge of provider files or algorithms."""
import json
import os

import httpx
from recarena_contracts.http import RecommendationRequest, RecommendationResponse
from recarena_contracts.models import PolicyDefinition
from recarena_contracts.text import normalize_query


class RankingFailure(Exception):
    pass


class RankingClient:
    def __init__(self, url=None, token=None):
        endpoints = json.loads(os.environ.get('RECARENA_RECOMMENDATION_SERVICES', '{}'))
        endpoints.setdefault('default', url or os.environ.get('RECARENA_RANKER_URL', 'http://127.0.0.1:8011'))
        headers = {'Authorization': 'Bearer ' + (token or os.environ.get('RECARENA_INTERNAL_TOKEN', ''))}
        # Retire idle client connections before the provider's usual five-
        # second close. Request timeouts and failure handling stay separate.
        limits = httpx.Limits(keepalive_expiry=1.0)
        self.clients = {key: httpx.Client(base_url=value, headers=headers, timeout=20, limits=limits)
                        for key, value in endpoints.items()}

    def _request(self, method, path, service_id='default', **kwargs):
        if service_id not in self.clients:
            raise RankingFailure('Unknown recommendation service')
        try:
            response = self.clients[service_id].request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise RankingFailure('Recommendation service unavailable or invalid response') from error

    def status(self):
        return {'ready': bool(self.policies())}

    def policies(self):
        result = []
        seen = set()
        try:
            for service_id in self.clients:
                values = self._request('GET', '/internal/v1/policies', service_id)
                if not isinstance(values, list):
                    raise ValueError('Expected policy list')
                for value in values:
                    definition = PolicyDefinition.model_validate(value)
                    # Service names are local routing aliases, never server-selected destinations.
                    definition = definition.model_copy(update={'policy': definition.policy.model_copy(update={'service_id': service_id})})
                    key = (service_id, definition.policy.policy_id, definition.policy.version)
                    if key in seen:
                        raise ValueError('Duplicate policy version')
                    seen.add(key)
                    result.append(definition.model_dump(mode='json'))
            return result
        except ValueError as error:
            raise RankingFailure('Invalid policy discovery response') from error

    def validate_policy(self, body):
        result = self._request('POST', '/internal/v1/policies/validate', body.policy.service_id,
                               json=body.model_dump(mode='json'))
        if not isinstance(result, dict) or result.get('ready') is not True or result.get('policy') != body.policy.model_dump(mode='json'):
            raise RankingFailure('Requested policy version is not ready')
        return result

    def recommend(self, request: RecommendationRequest):
        try:
            result = RecommendationResponse.model_validate(self._request('POST', '/internal/v1/recommend',
                request.policy.service_id, json=request.model_dump(mode='json')))
            candidates = result.candidates
            if result.policy != request.policy or result.ranking.policy_version_id != request.policy_version_id:
                raise ValueError('Policy version mismatch')
            if (candidates.catalog_snapshot_id != request.catalog_snapshot_id or
                candidates.candidate_scope != request.policy.candidate_scope or
                candidates.query_raw != request.query or candidates.query_normalized != normalize_query(request.query) or
                len(candidates.candidates) > request.policy.candidate_limit):
                raise ValueError('Candidate context mismatch')
            if request.candidates is not None and candidates != request.candidates:
                raise ValueError('A ranking source changed the shared candidate set')
            result.ranking.validate_candidates(candidates)
            return result
        except ValueError as error:
            raise RankingFailure('Invalid recommendation response') from error

    def close(self):
        for client in self.clients.values():
            client.close()
