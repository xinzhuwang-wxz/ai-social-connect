#!/usr/bin/env bash
# 起服务之前先把库弄成可用状态。
#
# 迁移**每次都跑**：alembic 自己会判断有没有要做的，重复执行是空操作。
# 播种只在库是空的时候跑——不然每次重启都会把演示中途产生的数据抹掉，
# 而那正是最让人恼火的一种"帮倒忙"。
set -euo pipefail

echo "等数据库…"
until python -c "
import sys, psycopg
from cofield.config import settings
try:
    psycopg.connect(settings.database_url.replace('postgresql+psycopg://', 'postgresql://')).close()
except Exception:
    sys.exit(1)
" 2>/dev/null; do sleep 1; done

echo "跑迁移…"
alembic upgrade head

if [ "$(python -c "
import sqlalchemy as sa
from cofield.adapters.persistence.engine import build_engine
from cofield.config import settings
with build_engine(settings.database_url).connect() as c:
    print(c.execute(sa.text('SELECT count(*) FROM principals')).scalar_one())
")" = "0" ]; then
  echo "库是空的，播一次种…"
  python -m cofield.cli seed --size "${COFIELD_SEED_SIZE:-20000}"
else
  echo "库里已经有人，跳过播种"
fi

exec uvicorn cofield.http.app:app --host 0.0.0.0 --port 8000
