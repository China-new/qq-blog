"""
管理员后台模块（蓝图）。
功能：管理员可封禁/解禁用户、删除任意文章/评论/留言、查看全站统计。
"""
from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from functools import wraps

bp = Blueprint("admin", __name__, url_prefix="/admin")

def _db():
    from app import get_db; return get_db()
def _is_admin(u):
    from app import is_admin; return is_admin(u)

def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user" not in session:
            flash("请先登录", "warning"); return redirect(url_for("login"))
        if not _is_admin(session["user"]):
            flash("需要管理员权限", "danger"); return redirect(url_for("index"))
        return view(*args, **kwargs)
    return wrapped

@bp.route("/")
@admin_required
def dashboard():
    from app import ADMIN_USERS
    db = _db()
    users = db.execute("SELECT username,banned,created_at FROM users ORDER BY username").fetchall()
    users = [dict(u) for u in users]
    for u in users: u["role"] = "admin" if u["username"] in ADMIN_USERS else "user"
    posts = db.execute("SELECT id,title,author,created_at FROM posts ORDER BY id DESC").fetchall()
    return render_template("admin.html", users=users, posts=posts)

@bp.route("/user/<username>/ban", methods=["POST"])
@admin_required
def ban_user(username):
    db = _db(); db.execute("UPDATE users SET banned=1 WHERE username=?", (username,)); db.commit()
    flash("已封禁用户", "success"); return redirect(url_for("admin.dashboard"))

@bp.route("/user/<username>/unban", methods=["POST"])
@admin_required
def unban_user(username):
    db = _db(); db.execute("UPDATE users SET banned=0 WHERE username=?", (username,)); db.commit()
    flash("已解禁用户", "success"); return redirect(url_for("admin.dashboard"))

@bp.route("/post/<pid>/delete", methods=["POST"])
@admin_required
def delete_post(pid):
    db = _db(); db.execute("DELETE FROM posts WHERE id=?", (pid,)); db.commit()
    flash("已删除文章", "success"); return redirect(url_for("admin.dashboard"))

@bp.route("/comment/<cid>/delete", methods=["POST"])
@admin_required
def delete_comment(cid):
    db = _db(); db.execute("DELETE FROM comments WHERE id=?", (cid,)); db.commit()
    flash("已删除评论", "success"); return redirect(request.referrer or url_for("index"))

@bp.route("/guestbook/<gid>/delete", methods=["POST"])
@admin_required
def delete_guestbook(gid):
    db = _db(); db.execute("DELETE FROM messages WHERE id=?", (gid,)); db.commit()
    flash("已删除留言", "success"); return redirect(url_for("admin.dashboard"))
