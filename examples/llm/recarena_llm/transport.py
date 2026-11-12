"""Responses API transport; records every attempt before semantic consumers read it."""
import asyncio
import copy
import json
from pathlib import Path
import time
import uuid

from jsonschema import Draft202012Validator

from .jsonio import digest, now, write_json


class ResponseFailure(RuntimeError):
    pass


def output_text(response: dict) -> str:
    if response.get('status') != 'completed':
        raise ResponseFailure(f'Response status: {response.get("status")}; details: {response.get("incomplete_details")}')
    texts = []
    for item in response.get('output', []):
        if item.get('type') != 'message':
            continue
        for part in item.get('content', []):
            if part.get('type') == 'refusal':
                raise ResponseFailure(f'Model refused: {part.get("refusal")}')
            if part.get('type') == 'output_text':
                texts.append(part['text'])
    if not texts:
        raise ResponseFailure('Completed response contains no output_text')
    return ''.join(texts)


def body(config: dict, system: str, payload: dict, schema: dict, name: str) -> dict:
    result = {'model': config['model'], 'input': [{'role': 'system', 'content': system},
              {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False, indent=2)}],
              'text': {'format': {'type': 'json_schema', 'name': name, 'strict': True, 'schema': schema}},
              'max_output_tokens': config['max_output_tokens'], 'store': False, 'truncation': 'disabled'}
    if config['reasoning'] != 'omit':
        result['reasoning'] = {'effort': config['reasoning']}
    return result


class Responses:
    def __init__(self, client, records: Path, config: dict):
        self.client, self.records, self.config = client, records, config

    async def call(self, key: str, stage: str, request: dict) -> dict:
        # SDK retries are disabled at construction: there is one visible retry policy here.
        for attempt in range(self.config['network_retries'] + 1):
            identifier = uuid.uuid4().hex
            path = self.records / 'responses' / key / stage / f'{identifier}.json'
            record = {'started_at': now(), 'request_sha256': digest(request), 'request': request,
                      'attempt': attempt + 1, 'response_id': None, 'status': 'started', 'usage': None}
            write_json(path, record)
            stream = None
            start = time.monotonic()
            try:
                stream = await self.client.responses.create(**request, stream=True)
                response = None
                while True:
                    try:
                        event = await asyncio.wait_for(stream.__anext__(), self.config['timeout_seconds'])
                    except StopAsyncIteration:
                        break
                    if event.type == 'response.created':
                        record['response_id'] = event.response.id
                    elif event.type in ('response.completed', 'response.incomplete', 'response.failed'):
                        response = event.response.model_dump(mode='json')
                        break
                    elif event.type == 'error':
                        raise ResponseFailure(f'Stream error: {getattr(event, "code", None)}')
                if response is None:
                    raise ConnectionError('Stream ended without a final response; completion is unknown')
                record.update(status=response.get('status'), response_id=response.get('id'),
                              usage=response.get('usage'), response=response)
                return response
            except BaseException as error:
                record['status'] = 'cancelled' if isinstance(error, asyncio.CancelledError) else 'failed'
                # Do not save HTTP headers/credentials or arbitrary SDK request representations.
                record['error'] = {'type': type(error).__name__, 'status_code': getattr(error, 'status_code', None)}
                record['completion_unknown'] = True
                status = getattr(error, 'status_code', None)
                retryable = (isinstance(error, (TimeoutError, ConnectionError)) or
                             type(error).__name__ in ('APIConnectionError', 'APITimeoutError') or
                             status in (408, 409, 429) or (isinstance(status, int) and status >= 500))
                if not retryable or attempt >= self.config['network_retries']:
                    raise
            finally:
                record['seconds'] = time.monotonic() - start
                record['finished_at'] = now()
                try:
                    write_json(path, record)
                finally:
                    if stream is not None:
                        await stream.close()
            await asyncio.sleep(min(2 ** attempt, 30))
        raise AssertionError('Unreachable')


async def checked_json(transport: Responses, key: str, stage: str, request: dict, validate,
                       repairs: int) -> dict:
    """Semantic re-asks are distinct from network retries and include the failed checks."""
    request = copy.deepcopy(request)
    schema = Draft202012Validator(request['text']['format']['schema'])

    def reject_constant(value):
        raise ValueError(f'Non-finite JSON value: {value}')

    for attempt in range(repairs + 1):
        response = await transport.call(key, stage, request)
        text = output_text(response)
        try:
            value = json.loads(text, parse_constant=reject_constant)
            problems = [e.message for e in schema.iter_errors(value)]
            if not problems:
                problems = validate(value)
        except (json.JSONDecodeError, ValueError) as error:
            problems = [f'Invalid JSON: {error}']
        if not problems:
            return value
        if attempt == repairs:
            raise ValueError(f'{stage} failed its output checks: {problems}')
        request['input'] += [{'role': 'assistant', 'content': text}, {'role': 'user',
            'content': 'Your previous JSON failed these checks:\n' + '\n'.join(problems)
                       + '\nReturn one corrected JSON object.'}]
