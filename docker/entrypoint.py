"""Read only each service's explicitly mounted secrets, then execute its command."""
import os
from pathlib import Path
import sys
from urllib.parse import quote

for key in ('RECARENA_ADMIN_TOKEN','RECARENA_INTERNAL_TOKEN','RECARENA_SESSION_API_KEY'):
    if path:=os.environ.get(key+'_FILE'):
        os.environ[key]=Path(path).read_text().strip()
if path:=os.environ.get('RECARENA_DB_PASSWORD_FILE'):
    password=Path(path).read_text().strip()
    user=quote(os.environ.get('RECARENA_DB_USER','recarena'),safe='')
    database=quote(os.environ.get('RECARENA_DB_NAME','recarena'),safe='')
    os.environ['RECARENA_DATABASE_URL']='postgresql+psycopg://'+user+':'+quote(password,safe='')+'@postgres:5432/'+database
os.execvp(sys.argv[1],sys.argv[1:])
