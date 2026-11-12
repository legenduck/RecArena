"""Concrete CLI entry points; unsupported milestone commands are not advertised."""
import argparse
import json
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(prog='recarena')
    commands=parser.add_subparsers(dest='command',required=True)
    verification=commands.add_parser('verify-export',help='Verify an export file inventory, sizes and checksums offline')
    verification.add_argument('--export-directory',type=Path,required=True)
    exporting=commands.add_parser('export',help='Export saved shopping records for a comparison')
    exporting.add_argument('--experiment',required=True)
    from recarena_platform.prepared_cli import add_commands, execute
    add_commands(commands)
    args=parser.parse_args()
    if args.command in {'data','sources'}:
        from sqlalchemy.exc import SQLAlchemyError
        from psycopg import Error as PsycopgError
        try:
            result=execute(args)
        except (ValueError,OSError,KeyError,SQLAlchemyError,PsycopgError) as error:
            # Do not echo a supplied bundle, SQL connection, or validation input.
            raise SystemExit(f'Prepared-input operation failed ({type(error).__name__}); no success recorded') from None
    elif args.command=='verify-export':
        from recarena_platform.reporting.export_io import verify_export
        manifest=verify_export(args.export_directory)
        result={'export_id':manifest['export_id'],'schema_version':manifest['schema_version'],
                'verified_files':len(manifest['files'])}
    else:
        from recarena_platform.db import engine_from_env
        engine=engine_from_env()
        try:
            from recarena_platform.reporting.exports import ExportService
            outcome=ExportService(engine).create(args.experiment)
            if outcome.error: raise SystemExit(outcome.error)
            result=outcome.value
        finally:
            engine.dispose()
    print(json.dumps(result,sort_keys=True,allow_nan=False))


if __name__=='__main__': main()
