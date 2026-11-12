"""Create/end one research session through HTTP; never give the API key to the agent."""
import argparse
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api-base-url', default=os.environ.get('RECARENA_PLATFORM_URL', 'http://127.0.0.1:8010'))
    parser.add_argument('--base-url', help='Optional browser-facing shopping base URL override')
    parser.add_argument('--user-id')
    parser.add_argument('--policy')
    parser.add_argument('--agent')
    parser.add_argument('--task-id')
    parser.add_argument('--client-run-id')
    parser.add_argument('--request-id', help='Reuse this ID for a retry of the same issuance, not a new trial')
    parser.add_argument('--end-session', help='End this previously issued session instead of creating one')
    parser.add_argument('--reason', default='researcher_end', choices=['researcher_end','agent_stop','budget_exhausted','runner_error','administrator_cancel'])
    parser.add_argument('--json', action='store_true', help='Print the response including the rollout ID')
    args = parser.parse_args()
    key = os.environ.get('RECARENA_SESSION_API_KEY')
    if not key:
        parser.error('Set RECARENA_SESSION_API_KEY in the script environment (not in the URL).')
    for name, value in [('api-base-url', args.api_base_url), ('base-url', args.base_url)]:
        if value is None: continue
        parsed = urlsplit(value)
        if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            parser.error(f'{name} must be an HTTP(S) base URL without credentials, query or fragment')
    headers = {'Content-Type':'application/json', 'Authorization':'Bearer ' + key,
               'User-Agent':'RecArena-Session-Client/1.0'}
    if args.end_session:
        if args.user_id or args.policy:
            parser.error('--end-session cannot be combined with user/policy settings')
        path = '/api/sessions/' + quote(args.end_session, safe='') + '/end'
        body = {'reason':args.reason}
    else:
        if not args.user_id or not args.policy:
            parser.error('--user-id and --policy are required to issue a session')
        path = '/api/sessions'
        body = {name:getattr(args, name) for name in ('user_id','policy','agent','task_id','client_run_id')}
        headers['Idempotency-Key'] = args.request_id or str(uuid4())
    request = Request(args.api_base_url.rstrip('/') + path,
        data=json.dumps(body, ensure_ascii=False).encode(), headers=headers, method='POST')
    try:
        with urlopen(request, timeout=120) as response:
            result=json.load(response)
    except HTTPError as error:
        try: code=json.load(error).get('error', {}).get('code', 'REQUEST_FAILED')
        except (ValueError, AttributeError): code='REQUEST_FAILED'
        print(f'Session API failed: HTTP {error.code} ({code})', file=sys.stderr)
        return 1
    except (URLError, TimeoutError):
        print('Session API could not be reached.', file=sys.stderr)
        return 1
    if not args.end_session and args.base_url:
        result['entry_url']=args.base_url.rstrip('/')+'/s/'+quote(result['session_id'], safe='')+'/'
    print(json.dumps(result, ensure_ascii=False) if args.json or args.end_session else result['entry_url'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
