"""
迁移脚本：将旧版 JSON 数据（data/*.json）导入 SQLite 数据库（blog.db）。
- 已存在同名用户/文章/评论/留言（按 id）会跳过，可重复执行。
- 执行前会自动备份现有 blog.db（若存在）为 blog.db.bak。
"""
import os, json, sqlite3, shutil
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.environ.get("BLOG_DB", os.path.join("/tmp", "blog.db"))

# 备份现有数据库
if os.path.exists(DB_PATH):
    shutil.copy2(DB_PATH, DB_PATH + ".bak")
    print(f"[备份] 已备份原数据库为 blog.db.bak")

db = sqlite3.connect(DB_PATH)
db.execute("PRAGMA foreign_keys = ON")

# 确保表存在（建表语句与 app.py 保持一致）
db.executescript("""
CREATE TABLE IF NOT EXISTS users (
    username    TEXT PRIMARY KEY,
    password    TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS posts (
    id          TEXT PRIMARY KEY,
    author      TEXT NOT NULL,
    title       TEXT NOT NULL,
    content     TEXT NOT NULL DEFAULT '',
    category    TEXT NOT NULL DEFAULT '其他',
    tags        TEXT NOT NULL DEFAULT '[]',
    media_path  TEXT,
    media_type  TEXT,
    likes       TEXT NOT NULL DEFAULT '[]',
    created_at  TEXT NOT NULL,
    updated_at  TEXT
);
CREATE TABLE IF NOT EXISTS comments (
    id          TEXT PRIMARY KEY,
    post_id     TEXT NOT NULL,
    author      TEXT NOT NULL,
    text        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT
);
CREATE TABLE IF NOT EXISTS messages (
    id          TEXT PRIMARY KEY,
    author      TEXT NOT NULL,
    text        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
""")

def load_json(name):
    p = os.path.join(DATA_DIR, name)
    if not os.path.exists(p):
        return None
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)

def norm_tags(tags):
    if isinstance(tags, list):
        return json.dumps(tags, ensure_ascii=False)
    return tags if tags else "[]"

def norm_likes(likes):
    if isinstance(likes, list):
        return json.dumps(likes, ensure_ascii=False)
    return likes if likes else "[]"

# 迁移 users（dict 结构）
users = load_json("users.json")
if isinstance(users, dict):
    n = 0
    for username, u in users.items():
        pw = u.get("password", "") if isinstance(u, dict) else ""
        created = u.get("created_at", datetime.now().isoformat()) if isinstance(u, dict) else datetime.now().isoformat()
        if not db.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
            db.execute("INSERT INTO users(username,password,created_at) VALUES(?,?,?)",
                       (username, pw, created))
            n += 1
    print(f"[用户] 导入 {n} 条（共 {len(users)} 条）")
elif users is not None:
    print("[用户] users.json 结构非预期，已跳过")

# 迁移 posts（list 结构）
posts = load_json("posts.json")
if isinstance(posts, list):
    n = 0
    for p in posts:
        pid = p.get("id")
        if not pid: continue
        if not db.execute("SELECT 1 FROM posts WHERE id=?", (pid,)).fetchone():
            db.execute("""INSERT INTO posts(id,author,title,content,category,tags,
                media_path,media_type,likes,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (pid, p.get("author",""), p.get("title",""), p.get("content",""),
                 p.get("category","其他"), norm_tags(p.get("tags")),
                 p.get("media_path"), p.get("media_type"),
                 norm_likes(p.get("likes")), p.get("created_at", datetime.now().isoformat()),
                 p.get("updated_at")))
            n += 1
    print(f"[文章] 导入 {n} 条（共 {len(posts)} 条）")
elif posts is not None:
    print("[文章] posts.json 结构非预期，已跳过")

# 迁移 comments（list 结构）
comments = load_json("comments.json")
if isinstance(comments, list):
    n = 0
    for c in comments:
        cid = c.get("id")
        if not cid: continue
        if not db.execute("SELECT 1 FROM comments WHERE id=?", (cid,)).fetchone():
            db.execute("INSERT INTO comments(id,post_id,author,text,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                (cid, c.get("post_id",""), c.get("author",""), c.get("text",""),
                 c.get("created_at", datetime.now().isoformat()), c.get("updated_at")))
            n += 1
    print(f"[评论] 导入 {n} 条（共 {len(comments)} 条）")
elif comments is not None:
    print("[评论] comments.json 结构非预期，已跳过")

# 迁移 messages（list 结构）
messages = load_json("messages.json")
if isinstance(messages, list):
    n = 0
    for m in messages:
        mid = m.get("id")
        if not mid: continue
        if not db.execute("SELECT 1 FROM messages WHERE id=?", (mid,)).fetchone():
            db.execute("INSERT INTO messages(id,author,text,created_at) VALUES(?,?,?,?)",
                (mid, m.get("author","匿名访客"), m.get("text",""),
                 m.get("created_at", datetime.now().isoformat())))
            n += 1
    print(f"[留言] 导入 {n} 条（共 {len(messages)} 条）")
elif messages is not None:
    print("[留言] messages.json 结构非预期，已跳过")

db.commit()

# 汇总统计
print("---- 迁移完成，数据库现状 ----")
for table in ("users","posts","comments","messages"):
    cnt = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    print(f"  {table}: {cnt} 条")
db.close()
print("✅ 迁移成功（blog.db 已生成）")
