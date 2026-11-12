"""Initialize private settings and manage the platform's Compose stack."""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'contracts'))
from recarena_contracts.source_provenance import provenance

LOCAL=ROOT/'configs/local/docker'


def write_new(path,value):
    if path.exists(): return
    with path.open('x') as stream: stream.write(value)
    path.chmod(0o600)


def docker_command():
    installed=shutil.which('docker')
    if installed: return [installed]
    portable=ROOT/'.tools/docker/docker'
    if portable.is_file(): return [str(portable),'--config',str(ROOT/'.tools/docker')]
    raise RuntimeError('Docker CLI unavailable; install Docker Engine and Compose on the Docker host')


def compose(*args):
    return docker_command()+['compose','--env-file',str(LOCAL/'compose.env'),'-f',str(ROOT/'compose.yaml'),*args]


def initialize():
    LOCAL.mkdir(parents=True,exist_ok=True,mode=0o700)
    for relative in ('artifacts','outputs/exports','configs/local/jobs','data/raw'):
        (ROOT/relative).mkdir(parents=True,exist_ok=True)
    for name in ('db_password','admin_token','internal_token','session_api_key'):
        write_new(LOCAL/(name+'.secret'),secrets.token_hex(32)+'\n')
    write_new(LOCAL/'assets.json',json.dumps({'manifests':[]})+'\n')
    write_new(LOCAL/'settings.json',json.dumps({'RECARENA_UID':os.getuid(),'RECARENA_GID':os.getgid(),
        'RECARENA_IMAGE_TAG':'local','RECARENA_SHOP_PORT':5173,'RECARENA_ADMIN_PORT':5174,
        'RECARENA_SHOP_URL':'http://127.0.0.1:5173','RECARENA_ADMIN_URL':'http://127.0.0.1:5174',
        'RECARENA_RAW_DATA':'./data/raw'},indent=2)+'\n')
    return refresh_build_metadata()


def refresh_build_metadata():
    settings=json.loads((LOCAL/'settings.json').read_text())
    code=provenance()
    values={**settings,'RECARENA_CODE_COMMIT':code['code_commit'] or '',
        'RECARENA_SOURCE_TREE_SHA256':code['source_tree_sha256'] or '',
        'RECARENA_CODE_DIRTY':'' if code['code_dirty'] is None else str(code['code_dirty']).lower()}
    # Mutable deployment pointer only; secrets/artifacts/experiment outputs stay intact.
    (LOCAL/'compose.env').write_text(''.join(key+'='+json.dumps(str(value))+'\n' for key,value in values.items()))
    (LOCAL/'compose.env').chmod(0o600)
    return code


def execute(command,check=True):
    result=subprocess.run(command,cwd=ROOT)
    if check and result.returncode: raise SystemExit(result.returncode)
    return result.returncode


def build_images():
    code=refresh_build_metadata()
    directory=ROOT/'outputs/docker'/('build-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:8])
    directory.mkdir(parents=True)
    services=['platform-api','shop-web','admin-web']
    command=compose('build',*services)
    result=execute(command,check=False)
    evidence={'command':command,'exit_code':result,'status':'passed' if result==0 else 'failed','code':code,
        'scope':'image build only; not runtime/network verification'}
    if result==0:
        settings=json.loads((LOCAL/'settings.json').read_text())
        images={'platform-api':'platform','shop-web':'shop','admin-web':'admin'}
        tags=['recarena-'+images[service]+':'+settings['RECARENA_IMAGE_TAG'] for service in services]
        evidence['images']=[json.loads(subprocess.check_output(docker_command()+['image','inspect',tag,'--format',
            '{{json .Id}}'],text=True)) for tag in tags]
    (directory/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n')
    if result: raise SystemExit(result)


def main(argv=None):
    parser=argparse.ArgumentParser(prog='./recarena')
    parser.add_argument('command',choices=['init','doctor','config-check','build-images','up','down'])
    args=parser.parse_args(argv)
    if args.command=='init':
        code=initialize()
        print(json.dumps({'configuration':str(LOCAL),'code':code,'artifact_readiness':'not_checked',
            'next':'Register catalog data and connect a recommendation HTTP service; see README.md.'}))
        return
    if not (LOCAL/'settings.json').is_file(): raise SystemExit('Run ./recarena init first')
    if args.command=='doctor':
        checks={}
        for name,command in [('compose',docker_command()+['compose','version','--short']),
                             ('daemon',docker_command()+['info','--format','{{json .ServerVersion}}'])]:
            result=subprocess.run(command,capture_output=True,text=True,cwd=ROOT)
            checks[name]={'status':'passed' if result.returncode==0 else 'failed','exit_code':result.returncode}
            if result.returncode==0: checks[name]['version']=result.stdout.strip()
        print(json.dumps({'checks':checks},indent=2))
        if any(c['status']=='failed' for c in checks.values()): raise SystemExit(1)
    elif args.command=='config-check':
        refresh_build_metadata()
        execute(compose('--profile','prepare','config','--quiet'))
    elif args.command=='build-images': build_images()
    elif args.command=='up':
        build_images()
        execute(compose('up','-d','--wait','postgres'))
        execute(compose('--profile','prepare','run','--rm','prepare','alembic','-c','backend/alembic.ini','upgrade','head'))
        services=['platform-api','shop-web','admin-web']
        execute(compose('up','-d','--wait','--wait-timeout','120',*services))
    elif args.command=='down': execute(compose('down'))  # never remove database volumes


if __name__=='__main__':
    try: main()
    except (RuntimeError,FileNotFoundError) as error: raise SystemExit(str(error))
