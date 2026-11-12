"""Run platform data and record-export commands; research analysis stays external."""
import os
from pathlib import Path
import subprocess
import sys

from compose import ROOT, compose


def container_paths(arguments):
    result = list(arguments)
    for index, value in enumerate(arguments[:-1]):
        if value not in {'--bundle', '--output', '--export-directory'}:
            continue
        path = Path(arguments[index + 1]).resolve()
        for directory in ('artifacts', 'outputs'):
            source = ROOT / directory
            if path.is_relative_to(source):
                result[index + 1] = str(Path('/app') / directory / path.relative_to(source))
                break
        else:
            raise ValueError('Container input/output paths must be under artifacts/ or outputs/')
    return result


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    docker = bool(arguments and arguments[0] == '--docker')
    if docker:
        arguments.pop(0)
    if not arguments or arguments == ['--help']:
        print('Usage: ./recarena [--docker] data|sources|export|verify-export ...\n'
              'Deployment: init, doctor, config-check, build-images, up, down\n'
              'Recommendation preparation: see examples/recommendation/ranker/README.md')
        return 0
    if arguments[0] not in {'data', 'sources', 'export', 'verify-export'}:
        raise ValueError('Unknown platform command; use --help. Model/index commands belong to examples/recommendation/.')
    command = (compose('--profile', 'prepare', 'run', '--rm', 'prepare', 'python', '-m',
                       'recarena_platform.cli', *container_paths(arguments)) if docker else
               ['uv', 'run', '--frozen', '--project', str(ROOT / 'backend'), 'python', '-m',
                'recarena_platform.cli', *arguments])
    return subprocess.call(command, cwd=ROOT, env=os.environ)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError, RuntimeError) as error:
        raise SystemExit(str(error)) from None
