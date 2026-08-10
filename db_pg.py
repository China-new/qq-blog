"""
数据库抽象层：SQLite（默认）/ PostgreSQL（设置 USE_PG=1 启用）。
提供 get_db() / init_db() / close_db，使业务代码无需区分数据库。
表结构与 app.py 中 SCHEMA 保持一致；PostgreSQL 启动时自动建表。
"""
import os, sqlite3

USE_PG = os.environ.get("USE_PG", "0") == "1"
DB_PATH = os.environ.get("BLOG_DB", os.path.join(os.path.dirname(__file__), "blog.db"))

def get_db():
    if USE_PG:
        import psycopg2, psycopg2.extras
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        conn.autocommit = False
        return conn
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def close_db(db):
    try: db.close()
    except Exception: pass

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT NOT NULL,
    created_at TEXT NOT NULL, avatar TEXT, avatar_grad TEXT DEFAULT '135,183,245');
CREATE TABLE IF NOT EXISTS posts (id TEXT PRIMARY KEY, author TEXT NOT NULL, title TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '', category TEXT NOT NULL DEFAULT '其他', tags TEXT NOT NULL DEFAULT '[]',
    media_path TEXT, media_type TEXT, likes TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL, updated_at TEXT);
CREATE TABLE IF NOT EXISTS comments (id TEXT PRIMARY KEY, post_id TEXT NOT NULL,
    author TEXT NOT NULL, text TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT);
CREATE TABLE IF NOT EXISTS messages (id TEXT PRIMARY KEY, author TEXT NOT NULL,
    text TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS visits (id SERIAL PRIMARY KEY, post_id TEXT, ua TEXT, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_posts_created ON posts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_comments_post ON comments(post_id);
CREATE INDEX IF NOT EXISTS idx_visits_post ON visits(post_id);
"""

PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT NOT NULL,
    created_at TEXT NOT NULL, avatar TEXT, avatar_grad TEXT DEFAULT '135,183,245');
CREATE TABLE IF NOT EXISTS posts (id TEXT PRIMARY KEY, author TEXT NOT NULL, title TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '', category TEXT NOT NULL DEFAULT '其他', tags TEXT NOT NULL DEFAULT '[]',
    media_path TEXT, media_type TEXT, likes TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL, updated_at TEXT);
CREATE TABLE IF NOT EXISTS comments (id TEXT PRIMARY KEY, post_id TEXT NOT NULL,
    author TEXT NOT NULL, text TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT);
CREATE TABLE IF NOT EXISTS messages (id TEXT PRIMARY KEY, author TEXT NOT NULL,
    text TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS visits (id SERIAL PRIMARY KEY, post_id TEXT, ua TEXT, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_posts_created ON posts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_comments_post ON comments(post_id);
CREATE INDEX IF NOT EXISTS idx_visits_post ON visits(post_id);
"""

def init_db():
    if USE_PG:
        import psycopg2
        conn = psycopg2.connect(os.environ["DATABASE_URL"]); conn.autocommit=True
        cur = conn.cursor()
        cur.execute(PG_SCHEMA); conn.close()
    else:
        conn = sqlite3.connect(DB_PATH); conn.executescript(SQLITE_SCHEMA); conn.commit(); conn.close()
