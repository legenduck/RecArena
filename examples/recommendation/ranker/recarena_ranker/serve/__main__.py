"""Start the bundled recommendation service with optional policy settings."""
import argparse
import os
from ..timestamps import DEFAULT_TAU, normalize_tau


def positive(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError('must be a positive integer')
    return number


def unit_interval(value):
    number = float(value)
    if not 0 <= number <= 1:
        raise argparse.ArgumentTypeError('must be a finite number between 0 and 1')
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default=os.environ.get('RECARENA_RANKER_CONFIG'))
    parser.add_argument('--k', type=positive, help='BM25 candidate count for all policies; default 200 in policy settings')
    parser.add_argument('--delta-t', '--delta_t', dest='delta_t', type=positive,
                        help='pop review window in days before tau; default 30 in policy settings')
    parser.add_argument('--tau', type=normalize_tau,
                        help=f'pop reference time, ISO timestamp with timezone; default {DEFAULT_TAU}')
    parser.add_argument('--personal-lambda', '--personal-lamda', type=unit_interval,
                        help='BM25 query weight in personal and the personal base of div; default 0.7')
    parser.add_argument('--div-lambda', '--div-lamda', type=unit_interval,
                        help='base-score weight in div MMR; default 0.8')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=int(os.environ.get('RECARENA_RANKER_PORT', '8011')))
    parser.add_argument('--workers', type=positive, default=os.environ.get('RECARENA_RANKER_WORKERS', '1'),
                        help='Independent serving workers on the same port; default 1')
    parser.add_argument('--no-access-log', action='store_true')
    args = parser.parse_args()
    if not args.config:
        parser.error('--config or RECARENA_RANKER_CONFIG is required')
    os.environ['RECARENA_RANKER_CONFIG'] = args.config
    if args.k is not None:
        os.environ['RECARENA_BM25_K'] = str(args.k)
    if args.delta_t is not None:
        os.environ['RECARENA_POP_DELTA_T'] = str(args.delta_t)
    if args.tau is not None:
        os.environ['RECARENA_POP_TAU'] = args.tau
    if args.personal_lambda is not None:
        os.environ['RECARENA_PERSONAL_LAMBDA'] = str(args.personal_lambda)
    if args.div_lambda is not None:
        os.environ['RECARENA_DIV_LAMBDA'] = str(args.div_lambda)
    import uvicorn
    uvicorn.run('recarena_ranker.serve.app:app', host=args.host, port=args.port,
                workers=args.workers, access_log=not args.no_access_log)


if __name__ == '__main__':
    main()
