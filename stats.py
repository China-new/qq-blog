"""
访问统计模块（蓝图）。
记录每次文章详情页访问（按日聚合），提供管理员统计页。
"""
from collections import Counter
from flask import Blueprint, render_template, session

bp = Blueprint("stats", __name__, url_prefix="/stats")

def _db():
    from app import get_db; return get_db()
def _is_admin(u):
    from app import is_admin; return is_admin(u)

def record_visit(post_id, ua):
    from datetime import datetime
    db = _db()
    db.execute("INSERT INTO visits(post_id,ua,created_at) VALUES(?,?,?)",
               (post_id, ua or "", datetime.now().isoformat()))
    db.commit()

@bp.route("/")
def dashboard():
    db = _db()
    rows = db.execute("SELECT substr(created_at,1,10) as d, COUNT(*) as c FROM visits GROUP BY d ORDER BY d DESC LIMIT 30").fetchall()
    daily = [{"date": r["d"], "count": r["c"]} for r in rows]
    total = db.execute("SELECT COUNT(*) as c FROM visits").fetchone()["c"]
    hot = db.execute("SELECT p.id,p.title,p.author,COUNT(v.id) as vc FROM posts p LEFT JOIN visits v ON v.post_id=p.id GROUP BY p.id ORDER BY vc DESC LIMIT 10").fetchall()
    uas = [r["ua"] for r in db.execute("SELECT ua FROM visits").fetchall()]
    def cls(u):
        u=u.lower()
        if "mobile" in u or "android" in u or "iphone" in u: return "移动端"
        if "windows" in u: return "Windows"
        if "mac" in u: return "macOS"
        return "其他/未知"
    dev = Counter(cls(u) for u in uas)
    devices = [{"name":k,"count":v} for k,v in dev.most_common()]
    return render_template("stats.html", daily=daily, total=total, hot=hot, devices=devices, admin=bool(session.get("user") and _is_admin(session["user"])))
