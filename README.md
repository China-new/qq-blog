# QQ 频道风格博客（Flask）

## 功能
- 用户登录 / 注册、管理员后台（封禁用户 / 删除任意文章评论留言）
- 发文章（图文 / 视频）、分类 / 标签、评论编辑删除、点赞、浏览量统计
- 搜索、夜间模式、QQ 频道 UI（左侧频道栏 + 移动端底部 Tab）
- 留言板（消息列表式 + 未读红点 + 实时 Toast 提醒）
- 个人头像上传 + 渐变背景、访问统计页（按日/热门/设备）
- PWA 支持（可“添加到主屏幕”，离线提示）

## 本地运行
```bash
git clone 仓库地址
cd blog
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py
# 访问 http://127.0.0.1:5000
```

## 默认管理员
首次使用请先注册用户 `admin`（见 `app.py` 中 `ADMIN_USERS = {"admin"}`），该用户登录后侧边栏出现「管理后台 / 访问统计」入口。

## 部署（Render 一键）
1. Push 本仓库到 GitHub
2. 打开 https://render.com → New → Blueprint → 连 GitHub 仓库 → Apply
3. 等待部署，获得 `https://xxx.onrender.com`（自带 HTTPS，手机任意网络可访问）

> Render 默认使用 SQLite + 持久磁盘（`/var/data/blog.db`，见 `render.yaml`），重启不丢数据。

## PostgreSQL（生产推荐）
设置环境变量 `USE_PG=1` 并 `DATABASE_URL=postgres://user:pass@host:5432/dbname`，启动时会自动建表（依赖 `psycopg2-binary`，已加入 requirements）。Render 提供托管 Postgres 插件，绑定后注入 `DATABASE_URL` 即可。

## 环境变量
| 变量 | 说明 | 默认 |
|---|---|---|
| `FLASK_ENV` | `production` 关闭 Debug | development |
| `FLASK_SECRET_KEY` | Session 密钥（部署务必设置） | 内置默认值 |
| `BLOG_DB` | SQLite 数据库路径 | `./blog.db` |
| `PORT` | 服务端口（平台注入） | 5000 |
| `USE_PG` | `1` 启用 PostgreSQL | 0 |
| `DATABASE_URL` | PostgreSQL 连接串 | — |

## PWA
浏览器访问后可通过「添加到主屏幕」安装为类 App 体验；离线时自动跳转 `/offline` 提示页。
