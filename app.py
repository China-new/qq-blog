"""
简易博客系统 - Flask 应用（SQLite 版）
功能：用户注册/登录、发布图文/视频帖子、留言板、点赞、
      评论编辑/删除、文章分类与标签、白天/夜间模式

存储：SQLite（单文件 blog.db），图片/视频仍存 uploads/ 目录。
"""
import os
import json
import uuid
import hashlib
import sqlite3
from datetime import datetime
from functools import wraps
from flask import (Flask, render_template, request, redirect, url_for,
                   session, flash, send_from_directory, abort, g, jsonify,
                   request as flask_request)
import admin as admin_bp
import stats as stats_bp

app = Flask(__name__)
# 密钥：优先从环境变量读取（部署安全），本地回退到固定值（方便开发）。
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "simple_blog_secret_key_2026")
# 部署在反向代理（Render / Railway / Nginx）后，需信任 X-Forwarded-* 头，
# 否则 url_for 生成 http 链接、session 可能异常。
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 数据库路径：默认项目目录下的 blog.db（本地/下载后直接用）。
# 沙盒或云端持久卷可通过环境变量 BLOG_DB 覆盖，例如 /tmp/blog.db 或 /var/data/blog.db。
DB_PATH = os.environ.get("BLOG_DB", os.path.join(BASE_DIR, "blog.db"))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_IMAGE = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
ALLOWED_VIDEO = {".mp4", ".webm", ".ogg", ".mov", ".avi"}

# 预置分类（用户也可输入新分类）
CATEGORIES = ["随笔", "技术", "生活", "旅行", "学习", "其他"]

# 管理员用户名（多个可用逗号分隔，或改造成查库 role='admin'）
ADMIN_USERS = {"admin"}


def is_admin(username):
    return username in ADMIN_USERS


# ---------- 数据库初始化 ----------
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    username    TEXT PRIMARY KEY,
    password    TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    avatar      TEXT,          -- 自定义头像文件名（存 uploads/）
    avatar_grad TEXT DEFAULT '135,183,245'  -- 头像渐变结束色(R,G,B)
);
CREATE TABLE IF NOT EXISTS posts (
    id          TEXT PRIMARY KEY,
    author      TEXT NOT NULL,
    title       TEXT NOT NULL,
    content     TEXT NOT NULL DEFAULT '',
    category    TEXT NOT NULL DEFAULT '其他',
    tags        TEXT NOT NULL DEFAULT '[]',   -- JSON 数组
    media_path  TEXT,
    media_type  TEXT,
    likes       TEXT NOT NULL DEFAULT '[]',   -- JSON 数组(用户名)
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
CREATE INDEX IF NOT EXISTS idx_posts_created ON posts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_comments_post ON comments(post_id);
CREATE TABLE IF NOT EXISTS visits (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id     TEXT,
    ua          TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_visits_post ON visits(post_id);
"""


def get_db():
    """每个请求复用同一个数据库连接（sqlite3 线程内使用）。"""
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(error):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript(SCHEMA)
    db.commit()
    db.close()


# 应用启动时确保表存在
init_db()

app.register_blueprint(admin_bp.bp)
app.register_blueprint(stats_bp.bp)


def _migrate_db():
    """为旧库补齐字段（兼容已存在的 blog.db）。"""
    try:
        db = sqlite3.connect(DB_PATH)
        cols = {r[1] for r in db.execute("PRAGMA table_info(posts)").fetchall()}
        if "views" not in cols:
            db.execute("ALTER TABLE posts ADD COLUMN views INTEGER DEFAULT 0")
            db.commit()
        ucols = {r[1] for r in db.execute("PRAGMA table_info(users)").fetchall()}
        if "avatar" not in ucols:
            db.execute("ALTER TABLE users ADD COLUMN avatar TEXT")
        if "avatar_grad" not in ucols:
            db.execute("ALTER TABLE users ADD COLUMN avatar_grad TEXT DEFAULT '135,183,245'")
        if "banned" not in ucols:
            db.execute("ALTER TABLE users ADD COLUMN banned INTEGER DEFAULT 0")
        if "role" not in ucols:
            db.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'user'")
            db.commit()
        # visits 表（统计）
        db.execute("""CREATE TABLE IF NOT EXISTS visits (
            id INTEGER PRIMARY KEY AUTOINCREMENT, post_id TEXT, ua TEXT,
            created_at TEXT NOT NULL)""")
        db.execute("CREATE INDEX IF NOT EXISTS idx_visits_post ON visits(post_id)")
        db.commit()
        db.close()
    except sqlite3.OperationalError:
        pass


_migrate_db()


# ---------- 辅助：Row <-> dict 互转 ----------
def row_to_dict(row):
    return dict(row) if row else None


def rows_to_list(rows):
    return [dict(r) for r in rows]


# ---------- 工具函数 ----------
def hash_password(pwd):
    return hashlib.sha256(pwd.encode("utf-8")).hexdigest()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user" not in session:
            flash("请先登录", "warning")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def current_user():
    return session.get("user")


def parse_tags(raw):
    """将逗号分隔的标签字符串解析为标签列表。"""
    if not raw:
        return []
    tags = [t.strip() for t in raw.replace("，", ",").split(",")]
    return [t for t in tags if t][:8]


def _safe_remove(fname):
    if not fname:
        return
    target = os.path.normpath(os.path.join(UPLOAD_DIR, fname))
    if os.path.dirname(target) == UPLOAD_DIR and os.path.exists(target):
        try:
            os.remove(target)
        except OSError:
            pass


# ---------- 路由：认证 ----------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if not username or not password:
            flash("用户名和密码不能为空", "danger")
            return redirect(url_for("register"))
        db = get_db()
        if db.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
            flash("用户名已存在", "danger")
            return redirect(url_for("register"))
        db.execute("INSERT INTO users(username,password,created_at) VALUES(?,?,?)",
                   (username, hash_password(password), datetime.now().isoformat()))
        db.commit()
        flash("注册成功，请登录", "success")
        return redirect(url_for("login"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = get_db().execute("SELECT * FROM users WHERE username=?",
                                (username,)).fetchone()
        if user and user["password"] == hash_password(password):
            session["user"] = username
            flash("登录成功", "success")
            return redirect(url_for("index"))
        flash("用户名或密码错误", "danger")
        return redirect(url_for("login"))
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("user", None)
    flash("已退出登录", "info")
    return redirect(url_for("index"))


# ---------- 路由：首页 / 帖子 ----------
@app.route("/")
def index():
    db = get_db()
    cat = request.args.get("category", "").strip()
    tag = request.args.get("tag", "").strip()
    q = request.args.get("q", "").strip()
    rows = db.execute("SELECT * FROM posts ORDER BY created_at DESC").fetchall()
    posts = rows_to_list(rows)
    # 反序列化 JSON 字段 + 统计浏览量（views 列若不存在则默认 0）
    for p in posts:
        p["tags"] = _loads(p["tags"])
        p["likes"] = _loads(p["likes"])
        p["views"] = p.get("views") or 0
        p["comment_count"] = db.execute(
            "SELECT COUNT(*) FROM comments WHERE post_id=?", (p["id"],)).fetchone()[0]
    # 搜索：标题/正文/标签
    if q:
        ql = q.lower()
        posts = [p for p in posts if q.lower() in p["title"].lower()
                 or q.lower() in p["content"].lower()
                 or any(q.lower() in t.lower() for t in (p.get("tags") or []))]
    if cat:
        posts = [p for p in posts if p.get("category") == cat]
    if tag:
        posts = [p for p in posts if tag in (p.get("tags") or [])]
    all_categories = sorted(set(p.get("category") for p in posts if p.get("category")))
    all_tags = sorted(set(t for p in posts for t in (p.get("tags") or [])))
    # 热门文章（按浏览量 Top5）
    hot_posts = sorted(posts, key=lambda x: x["views"], reverse=True)[:5]
    return render_template("index.html", posts=posts, user=current_user(),
                           categories=CATEGORIES, all_categories=all_categories,
                           all_tags=all_tags, cur_cat=cat, cur_tag=tag, q=q,
                           hot_posts=hot_posts)


def _loads(s):
    try:
        return json.loads(s) if s else []
    except (ValueError, TypeError):
        return []


@app.route("/post/new", methods=["GET", "POST"])
@login_required
def post_new():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        category = request.form.get("category", "").strip()
        tags = parse_tags(request.form.get("tags", ""))
        if not title:
            flash("标题不能为空", "danger")
            return redirect(url_for("post_new"))
        file = request.files.get("media")
        media_path = None
        media_type = None
        if file and file.filename:
            ext = os.path.splitext(file.filename)[1].lower()
            if ext in ALLOWED_IMAGE:
                media_type = "image"
            elif ext in ALLOWED_VIDEO:
                media_type = "video"
            else:
                flash("仅支持图片(jpg/png/gif/webp)或视频(mp4/webm)", "danger")
                return redirect(url_for("post_new"))
            fname = f"{uuid.uuid4().hex}{ext}"
            file.save(os.path.join(UPLOAD_DIR, fname))
            media_path = fname
        pid = uuid.uuid4().hex
        db = get_db()
        db.execute("""INSERT INTO posts(id,author,title,content,category,tags,
                       media_path,media_type,likes,created_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?)""",
                   (pid, current_user(), title, content, category or "其他",
                    json.dumps(tags, ensure_ascii=False), media_path, media_type,
                    json.dumps([], ensure_ascii=False), datetime.now().isoformat()))
        db.commit()
        flash("发布成功", "success")
        return redirect(url_for("index"))
    return render_template("post_new.html", user=current_user(),
                           categories=CATEGORIES)


@app.route("/post/<pid>")
def post_detail(pid):
    db = get_db()
    row = db.execute("SELECT * FROM posts WHERE id=?", (pid,)).fetchone()
    if not row:
        abort(404)
    post = dict(row)
    post["tags"] = _loads(post["tags"])
    post["likes"] = _loads(post["likes"])
    # 记录访问（供统计页按日聚合）
    try:
        stats_bp.record_visit(pid, request.headers.get("User-Agent", ""))
    except Exception:
        pass
    # 会话级浏览量自增（同一会话不重复计）
    viewed = session.get("viewed", [])
    if pid not in viewed:
        try:
            db.execute("UPDATE posts SET views = COALESCE(views,0) + 1 WHERE id=?", (pid,))
            db.commit()
        except sqlite3.OperationalError:
            pass
        viewed = viewed + [pid]
        session["viewed"] = viewed
    rows = db.execute("SELECT * FROM comments WHERE post_id=? ORDER BY created_at",
                      (pid,)).fetchall()
    post_comments = rows_to_list(rows)
    return render_template("post_detail.html", post=post,
                           comments=post_comments, user=current_user())


@app.route("/post/<pid>/comment", methods=["POST"])
@login_required
def add_comment(pid):
    text = request.form.get("text", "").strip()
    if text:
        db = get_db()
        if not db.execute("SELECT 1 FROM posts WHERE id=?", (pid,)).fetchone():
            abort(404)
        db.execute("INSERT INTO comments(id,post_id,author,text,created_at) VALUES(?,?,?,?,?)",
                   (uuid.uuid4().hex, pid, current_user(), text, datetime.now().isoformat()))
        db.commit()
        flash("评论成功", "success")
    return redirect(url_for("post_detail", pid=pid))


@app.route("/comment/<cid>/edit", methods=["POST"])
@login_required
def comment_edit(cid):
    db = get_db()
    comment = db.execute("SELECT * FROM comments WHERE id=?", (cid,)).fetchone()
    if not comment:
        abort(404)
    if comment["author"] != current_user():
        flash("只有作者才能编辑该评论", "danger")
        return redirect(url_for("post_detail", pid=comment["post_id"]))
    text = request.form.get("text", "").strip()
    if text:
        db.execute("UPDATE comments SET text=?, updated_at=? WHERE id=?",
                   (text, datetime.now().isoformat(), cid))
        db.commit()
        flash("评论已更新", "success")
    return redirect(url_for("post_detail", pid=comment["post_id"]))


@app.route("/comment/<cid>/delete", methods=["POST"])
@login_required
def comment_delete(cid):
    db = get_db()
    comment = db.execute("SELECT * FROM comments WHERE id=?", (cid,)).fetchone()
    if not comment:
        abort(404)
    if comment["author"] != current_user():
        flash("只有作者才能删除该评论", "danger")
        return redirect(url_for("post_detail", pid=comment["post_id"]))
    db.execute("DELETE FROM comments WHERE id=?", (cid,))
    db.commit()
    flash("评论已删除", "success")
    return redirect(url_for("post_detail", pid=comment["post_id"]))


@app.route("/post/<pid>/like", methods=["POST"])
@login_required
def like_post(pid):
    user = current_user()
    db = get_db()
    row = db.execute("SELECT likes FROM posts WHERE id=?", (pid,)).fetchone()
    if not row:
        abort(404)
    likes = _loads(row["likes"])
    if user not in likes:
        likes.append(user)
    else:
        likes.remove(user)
    db.execute("UPDATE posts SET likes=? WHERE id=?",
               (json.dumps(likes, ensure_ascii=False), pid))
    db.commit()
    return redirect(url_for("post_detail", pid=pid))


@app.route("/post/<pid>/edit", methods=["GET", "POST"])
@login_required
def post_edit(pid):
    db = get_db()
    row = db.execute("SELECT * FROM posts WHERE id=?", (pid,)).fetchone()
    if not row:
        abort(404)
    post = dict(row)
    post["tags"] = _loads(post["tags"])
    post["likes"] = _loads(post["likes"])
    if post["author"] != current_user():
        flash("只有作者才能编辑该文章", "danger")
        return redirect(url_for("post_detail", pid=pid))
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        category = request.form.get("category", "").strip()
        tags = parse_tags(request.form.get("tags", ""))
        if not title:
            flash("标题不能为空", "danger")
            return redirect(url_for("post_edit", pid=pid))
        post["title"] = title
        post["content"] = content
        post["category"] = category or "其他"
        post["tags"] = tags
        file = request.files.get("media")
        remove_media = request.form.get("remove_media")
        if remove_media and post.get("media_path"):
            _safe_remove(post["media_path"])
            post["media_path"] = None
            post["media_type"] = None
        if file and file.filename:
            ext = os.path.splitext(file.filename)[1].lower()
            if ext in ALLOWED_IMAGE:
                media_type = "image"
            elif ext in ALLOWED_VIDEO:
                media_type = "video"
            else:
                flash("仅支持图片(jpg/png/gif/webp)或视频(mp4/webm)", "danger")
                return redirect(url_for("post_edit", pid=pid))
            if post.get("media_path"):
                _safe_remove(post["media_path"])
            fname = f"{uuid.uuid4().hex}{ext}"
            file.save(os.path.join(UPLOAD_DIR, fname))
            post["media_path"] = fname
            post["media_type"] = media_type
        db.execute("""UPDATE posts SET title=?,content=?,category=?,tags=?,
                       media_path=?,media_type=?,updated_at=? WHERE id=?""",
                   (post["title"], post["content"], post["category"],
                    json.dumps(post["tags"], ensure_ascii=False),
                    post["media_path"], post["media_type"],
                    datetime.now().isoformat(), pid))
        db.commit()
        flash("文章已更新", "success")
        return redirect(url_for("post_detail", pid=pid))
    return render_template("post_edit.html", post=post, user=current_user(),
                           categories=CATEGORIES)


@app.route("/post/<pid>/delete", methods=["POST"])
@login_required
def post_delete(pid):
    db = get_db()
    row = db.execute("SELECT * FROM posts WHERE id=?", (pid,)).fetchone()
    if not row:
        abort(404)
    post = dict(row)
    if post["author"] != current_user():
        flash("只有作者才能删除该文章", "danger")
        return redirect(url_for("post_detail", pid=pid))
    if post.get("media_path"):
        _safe_remove(post["media_path"])
    db.execute("DELETE FROM posts WHERE id=?", (pid,))
    db.execute("DELETE FROM comments WHERE post_id=?", (pid,))
    db.commit()
    flash("文章已删除", "success")
    return redirect(url_for("index"))


# ---------- 路由：用户主页 ----------
@app.route("/user/<username>")
def user_home(username):
    db = get_db()
    rows = db.execute("SELECT * FROM posts WHERE author=? ORDER BY created_at DESC",
                      (username,)).fetchall()
    posts = rows_to_list(rows)
    for p in posts:
        p["tags"] = _loads(p["tags"])
        p["likes"] = _loads(p["likes"])
        p["views"] = p.get("views") or 0
    total_views = sum(p["views"] for p in posts)
    total_likes = sum(len(p["likes"]) for p in posts)
    # 目标用户头像信息（用于头像展示 + 渐变背景）
    u = db.execute("SELECT avatar, avatar_grad FROM users WHERE username=?",
                   (username,)).fetchone()
    target_avatar = u["avatar"] if u else None
    target_grad = (u["avatar_grad"] if u else None) or "135,183,245"
    return render_template("user.html", target=username, posts=posts,
                           count=len(posts), total_views=total_views,
                           total_likes=total_likes, user=current_user(),
                           target_avatar=target_avatar, target_grad=target_grad,
                           grad_palette=GRAD_PALETTE)


# ---------- 路由：留言板 ----------
@app.route("/guestbook", methods=["GET", "POST"])
def guestbook():
    db = get_db()
    if request.method == "POST":
        text = request.form.get("text", "").strip()
        if text:
            db.execute("INSERT INTO messages(id,author,text,created_at) VALUES(?,?,?,?)",
                       (uuid.uuid4().hex, current_user() or "匿名访客", text,
                        datetime.now().isoformat()))
            db.commit()
            flash("留言成功", "success")
        return redirect(url_for("guestbook"))
    rows = db.execute("SELECT * FROM messages ORDER BY created_at DESC").fetchall()
    msgs = rows_to_list(rows)
    return render_template("guestbook.html", messages=msgs, user=current_user())


# ---------- 路由：上传文件服务 ----------
@app.route("/uploads/<path:fname>")
def uploaded_file(fname):
    return send_from_directory(UPLOAD_DIR, fname)


# ---------- 工具：模板上下文 ----------
@app.context_processor
def inject_globals():
    """向全部模板注入全局变量：当前用户、分类、留言板未读计数（红点）、用户头像信息、管理员标志、request。"""
    ctx = {"now_user": current_user(), "CATEGORIES": CATEGORIES, "gb_unread": 0,
            "is_admin": is_admin(current_user()) if current_user() else False,
            "request": flask_request}
    # 未读红点：登录用户可见的、自己会话内尚未查看的留言数
    if current_user():
        viewed = session.get("gb_viewed", 0)  # 上次查看时的留言总数
        try:
            db = get_db()
            total = db.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            ctx["gb_unread"] = max(0, total - int(viewed))
            # 当前用户头像信息
            u = db.execute("SELECT avatar, avatar_grad FROM users WHERE username=?",
                           (current_user(),)).fetchone()
            ctx["cur_avatar"] = u["avatar"] if u else None
            ctx["cur_grad"] = (u["avatar_grad"] if u else None) or "135,183,245"
        except sqlite3.OperationalError:
            ctx["gb_unread"] = 0
            ctx["cur_avatar"] = None
            ctx["cur_grad"] = "135,183,245"
    else:
        ctx["cur_avatar"] = None
        ctx["cur_grad"] = "135,183,245"
    return ctx


@app.route("/guestbook/seen", methods=["POST"])
def guestbook_seen():
    """标记留言板为已读（将当前留言总数写入会话）。"""
    try:
        db = get_db()
        total = db.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        session["gb_viewed"] = total
    except sqlite3.OperationalError:
        session["gb_viewed"] = 0
    return ("", 204)


# ---------- 路由：头像上传 ----------
ALLOWED_AVATAR = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
GRAD_PALETTE = [  # 可选渐变结束色（与品牌蓝 #12B7F5 搭配）
    "108,183,245",  # 天空蓝（默认）
    "120,220,180",  # 薄荷绿
    "255,160,130",  # 珊瑚橙
    "190,140,255",  # 紫罗兰
    "255,200,90",   # 暖阳黄
    "90,200,230",   # 冰蓝
]


@app.route("/user/<username>/avatar", methods=["POST"])
@login_required
def upload_avatar(username):
    """上传/更换头像（仅本人），并可选设置渐变结束色。"""
    if username != current_user():
        flash("只能修改自己的头像", "danger")
        return redirect(url_for("user_home", username=username))
    db = get_db()
    file = request.files.get("avatar")
    grad = request.form.get("grad", "").strip()
    if file and file.filename:
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in ALLOWED_AVATAR:
            flash("头像仅支持 jpg/png/gif/webp", "danger")
            return redirect(url_for("user_home", username=username))
        # 删除旧自定义头像文件（保留旧文件引用）
        old = db.execute("SELECT avatar FROM users WHERE username=?",
                         (username,)).fetchone()
        if old and old["avatar"]:
            _safe_remove(old["avatar"])
        fname = f"avatar_{uuid.uuid4().hex}{ext}"
        file.save(os.path.join(UPLOAD_DIR, fname))
        db.execute("UPDATE users SET avatar=? WHERE username=?",
                   (fname, username))
    if grad and grad in GRAD_PALETTE:
        db.execute("UPDATE users SET avatar_grad=? WHERE username=?",
                   (grad, username))
    db.commit()
    flash("头像已更新", "success")
    return redirect(url_for("user_home", username=username))


# ---------- 接口：未读留言数（供前端轮询实现实时 Toast）----------
@app.route("/api/unread")
def api_unread():
    """返回当前未读留言数；登录用户基于会话已读数，游客返回总数。"""
    try:
        db = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
        total = db.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    except sqlite3.OperationalError:
        return {"unread": 0}
    viewed = session.get("gb_viewed", 0) if current_user() else 0
    return {"unread": max(0, total - int(viewed))}


# ---------- PWA：可“添加到主屏幕”，离线时给友好提示 ----------
@app.route("/manifest.json")
def pwa_manifest():
    manifest = {
        "name": "QQ 频道博客",
        "short_name": "QBlog",
        "description": "QQ 频道风格的简易博客",
        "start_url": url_for("index", _external=True),
        "display": "standalone",
        "background_color": "#0f1419",
        "theme_color": "#12B7F5",
        "icons": [
            {"src": url_for("static_icon", _external=True) if False else "/static/icon-192.png",
             "sizes": "192x192", "type": "image/png"},
            {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"},
        ],
    }
    from flask import jsonify
    return jsonify(manifest)


@app.route("/static/<path:fname>")
def static_icon(fname):
    # 复用 uploads 目录承载 PWA 图标（避免新增 static 目录依赖）
    return send_from_directory(UPLOAD_DIR, fname)


@app.route("/offline")
def offline():
    return render_template("offline.html")

@app.route("/sw.js")
def service_worker():
    from flask import Response
    sw_path = os.path.join(BASE_DIR, "sw.js")
    if not os.path.exists(sw_path):
        return ("", 404)
    with open(sw_path, "r", encoding="utf-8") as f:
        body = f.read()
    return Response(body, mimetype="application/javascript")


if __name__ == "__main__":
    # 本地开发：python app.py
    # 端口优先读环境变量 PORT（Render/Railway 等平台注入），本地默认 5000。
    port = int(os.environ.get("PORT", 5000))
    # debug 仅在非生产环境开启，避免部署时意外开启调试器。
    debug = os.environ.get("FLASK_ENV", "development") != "production"
    app.run(host="0.0.0.0", port=port, debug=debug)
else:
    # 被 gunicorn / uWSGI 等 WSGI 服务器导入时走此分支（部署场景）。
    # gunicorn 启动命令：gunicorn -w 4 -b 0.0.0.0:$PORT app:app
    pass
