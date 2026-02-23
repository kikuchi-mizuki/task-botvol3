"""
Gunicorn設定ファイル
Railwayでの本番環境用設定
"""

import os
import multiprocessing

# サーバーソケット
bind = f"0.0.0.0:{os.environ.get('PORT', '5000')}"
backlog = 2048

# ワーカープロセス
workers = int(os.environ.get('GUNICORN_WORKERS', '2'))
worker_class = 'gthread'
threads = int(os.environ.get('GUNICORN_THREADS', '4'))
worker_connections = 1000
max_requests = 1000
max_requests_jitter = 50

# タイムアウト設定（秒）
timeout = 120
graceful_timeout = 30
keepalive = 5

# ロギング
accesslog = '-'
errorlog = '-'
loglevel = 'info'
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# プロセス命名
proc_name = 'line_calendar_bot'

# セキュリティ
limit_request_line = 4094
limit_request_fields = 100
limit_request_field_size = 8190

# リロード（開発時のみ）
reload = os.environ.get('ENV', 'production') == 'development'

# デーモン化しない
daemon = False

# プリロード
preload_app = False

# ワーカーの再起動
max_requests_jitter = 50
