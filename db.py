import sqlite3
from datetime import datetime, timedelta
import secrets
import string

DB_PATH = 'line_calendar.db'

class DBHelper:
    def __init__(self, db_path=DB_PATH):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._init_tables()

    def _init_tables(self):
        c = self.conn.cursor()
        # ユーザーごとのGoogle認証トークン保存
        c.execute('''
            CREATE TABLE IF NOT EXISTS users (
                line_user_id TEXT PRIMARY KEY,
                google_token BLOB,
                created_at TEXT,
                updated_at TEXT
            )
        ''')
        # ワンタイムコード管理
        c.execute('''
            CREATE TABLE IF NOT EXISTS onetimes (
                code TEXT PRIMARY KEY,
                line_user_id TEXT,
                expires_at TEXT,
                used INTEGER DEFAULT 0,
                created_at TEXT
            )
        ''')
        # 予定追加の一時保存テーブル
        c.execute('''
            CREATE TABLE IF NOT EXISTS pending_events (
                line_user_id TEXT PRIMARY KEY,
                event_json TEXT,
                created_at TEXT
            )
        ''')
        self.conn.commit()

    # --- users ---
    def save_google_token(self, line_user_id, google_token_bytes):
        now = datetime.utcnow().isoformat()
        print(f"[DEBUG] save_google_token: line_user_id={line_user_id}, token_length={len(google_token_bytes) if google_token_bytes else 0}, time={now}")
        c = self.conn.cursor()
        c.execute('''
            INSERT INTO users (line_user_id, google_token, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(line_user_id) DO UPDATE SET google_token=excluded.google_token, updated_at=excluded.updated_at
        ''', (line_user_id, google_token_bytes, now, now))
        self.conn.commit()

    def get_google_token(self, line_user_id):
        c = self.conn.cursor()
        c.execute('SELECT google_token FROM users WHERE line_user_id=?', (line_user_id,))
        row = c.fetchone()
        print(f"[DEBUG] get_google_token: line_user_id={line_user_id}, token_found={row is not None}, token_length={len(row[0]) if row and row[0] else 0}")
        return row[0] if row else None

    # --- onetimes ---
    def create_onetime_code(self, line_user_id, code, expires_minutes=10):
        now = datetime.utcnow()
        expires_at = (now + timedelta(minutes=expires_minutes)).isoformat()
        c = self.conn.cursor()
        c.execute('''
            INSERT INTO onetimes (code, line_user_id, expires_at, used, created_at)
            VALUES (?, ?, ?, 0, ?)
        ''', (code, line_user_id, expires_at, now.isoformat()))
        self.conn.commit()

    def get_onetime_code(self, code):
        c = self.conn.cursor()
        c.execute('SELECT code, line_user_id, expires_at, used FROM onetimes WHERE code=?', (code,))
        row = c.fetchone()
        if row:
            return {
                'code': row[0],
                'line_user_id': row[1],
                'expires_at': row[2],
                'used': bool(row[3])
            }
        return None

    def mark_onetime_code_used(self, code):
        c = self.conn.cursor()
        c.execute('UPDATE onetimes SET used=1 WHERE code=?', (code,))
        self.conn.commit()

    def generate_onetime_code(self, line_user_id, expires_minutes=10):
        """ワンタイムコードを生成してDBに保存"""
        # 8文字のランダムコードを生成
        code = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
        expires_at = (datetime.now() + timedelta(minutes=expires_minutes)).isoformat()
        created_at = datetime.now().isoformat()
        
        c = self.conn.cursor()
        c.execute('''
            INSERT INTO onetimes (code, line_user_id, expires_at, created_at)
            VALUES (?, ?, ?, ?)
        ''', (code, line_user_id, expires_at, created_at))
        self.conn.commit()
        
        return code

    def verify_onetime_code(self, code):
        """ワンタイムコードを検証（有効期限・使用済みチェック）"""
        c = self.conn.cursor()
        c.execute('''
            SELECT line_user_id, expires_at, used 
            FROM onetimes 
            WHERE code = ?
        ''', (code,))
        result = c.fetchone()
        
        if not result:
            return None  # コードが存在しない
        
        line_user_id, expires_at, used = result
        
        if used:
            return None  # 既に使用済み
        
        # 有効期限チェック
        expires_datetime = datetime.fromisoformat(expires_at)
        if datetime.now() > expires_datetime:
            return None  # 期限切れ
        
        return line_user_id

    def mark_onetime_used(self, code):
        """ワンタイムコードを使用済みにマーク"""
        c = self.conn.cursor()
        c.execute('UPDATE onetimes SET used = 1 WHERE code = ?', (code,))
        self.conn.commit()

    def cleanup_expired_onetimes(self):
        """期限切れのワンタイムコードを削除"""
        c = self.conn.cursor()
        now = datetime.now().isoformat()
        c.execute('DELETE FROM onetimes WHERE expires_at < ?', (now,))
        self.conn.commit()

    def user_exists(self, line_user_id):
        """ユーザーが認証済みかどうかを判定"""
        c = self.conn.cursor()
        c.execute('SELECT 1 FROM users WHERE line_user_id = ?', (line_user_id,))
        return c.fetchone() is not None

    def get_all_user_ids(self):
        """認証済みユーザーのLINEユーザーID一覧を返す"""
        c = self.conn.cursor()
        c.execute('SELECT line_user_id FROM users WHERE google_token IS NOT NULL')
        rows = c.fetchall()
        return [row[0] for row in rows]

    def close(self):
        self.conn.close()

    def save_oauth_state(self, state, line_user_id):
        """OAuth stateとLINEユーザーIDを紐付けて保存"""
        c = self.conn.cursor()
        now = datetime.now().isoformat()
        c.execute('''
            CREATE TABLE IF NOT EXISTS oauth_states (
                state TEXT PRIMARY KEY,
                line_user_id TEXT,
                created_at TEXT
            )
        ''')
        c.execute('''
            INSERT OR REPLACE INTO oauth_states (state, line_user_id, created_at)
            VALUES (?, ?, ?)
        ''', (state, line_user_id, now))
        self.conn.commit()

    def get_line_user_id_by_state(self, state):
        """stateからLINEユーザーIDを取得"""
        c = self.conn.cursor()
        c.execute('SELECT line_user_id FROM oauth_states WHERE state = ?', (state,))
        result = c.fetchone()
        return result[0] if result else None

    def save_pending_event(self, line_user_id, event_json):
        now = datetime.utcnow().isoformat()
        c = self.conn.cursor()
        c.execute('''
            INSERT INTO pending_events (line_user_id, event_json, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(line_user_id) DO UPDATE SET event_json=excluded.event_json, created_at=excluded.created_at
        ''', (line_user_id, event_json, now))
        self.conn.commit()

    def get_pending_event(self, line_user_id):
        c = self.conn.cursor()
        c.execute('SELECT event_json FROM pending_events WHERE line_user_id=?', (line_user_id,))
        row = c.fetchone()
        return row[0] if row else None

    def delete_pending_event(self, line_user_id):
        c = self.conn.cursor()
        c.execute('DELETE FROM pending_events WHERE line_user_id=?', (line_user_id,))
        self.conn.commit() 