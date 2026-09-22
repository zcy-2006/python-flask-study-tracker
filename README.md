# 学习打卡网站

一个适合 Python 初学者练手的 Flask 网站。它可以把每天的学习内容保存到 SQLite，并通过搜索、筛选、统计和 CSV 导出追踪学习进度。

## 功能

- 用户注册、登录和退出
- 第一个用户自动成为管理员
- 管理员后台可关闭注册、设置邀请码和管理用户权限
- 查看账户信息并修改密码
- CSRF 防护和安全响应头
- 每个用户拥有独立的学习记录和目标
- 查看全部学习记录
- 按日期、科目筛选记录
- 搜索学习内容、科目、标签和笔记
- 添加标签并按标签筛选
- 学习记录分页浏览
- 新增、编辑和删除记录
- 标记完成或取消完成
- 显示记录数、总学习时长和完成率
- 显示本周学习统计
- 计算连续记录天数
- 设置每日和每周学习目标
- 显示近 7 天学习时长趋势
- 显示最近 8 周学习热力图
- 显示本月学习、活跃天数、日均时长和最佳一天
- 展示科目学习时长分布
- 导出 CSV 文件
- 下载和导入 JSON 完整备份
- 备份支持合并导入和替换恢复
- 使用 SQLite 持久化数据
- 使用 Bootstrap 适配手机页面

## 技术栈

- Python 3.8+
- Flask 3.0
- Flask-Login
- Flask-WTF
- SQLite
- Jinja2
- Bootstrap 5

## 本地运行

在项目目录打开 PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m flask --app app run --debug
```

然后打开：

```text
http://127.0.0.1:5000
```

第一次启动时会自动创建 `instance/study_tracker.sqlite`，并自动迁移新增字段。第一个注册的用户会自动接管升级前没有归属的本地记录。

正式部署前请设置安全的 `SECRET_KEY` 环境变量；启用 HTTPS 后同时设置 `SESSION_COOKIE_SECURE=1`。

## 运行测试

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## 页面和路由

| 地址 | 说明 |
| --- | --- |
| `/register` | 注册账号，可启用邀请码 |
| `/account` | 查看账户信息、修改密码 |
| `/admin` | 管理员后台 |
| `/login` | 登录 |
| `/logout` | 退出登录，仅支持 POST |
| `/` | 学习记录列表和统计面板 |
| `/?q=Flask` | 搜索学习内容、科目和笔记 |
| `/?date=2026-09-22` | 按日期筛选 |
| `/?subject=Python%20Web` | 按科目筛选 |
| `/export.csv` | 导出当前筛选结果为 CSV |
| `/backup.json` | 下载当前账号的完整 JSON 备份 |
| `/import` | 导入 JSON 备份，仅支持 POST |
| `/settings` | 设置每日和每周目标 |
| `/records/new` | 新增记录 |
| `/records/<id>/edit` | 编辑记录 |
| `/health` | 健康检查 |

## 项目结构

```text
python-flask-study-tracker/
├── app.py
├── schema.sql
├── requirements.txt
├── templates/
│   ├── base.html
│   ├── account.html
│   ├── admin.html
│   ├── form.html
│   ├── index.html
│   ├── login.html
│   ├── register.html
│   └── settings.html
├── static/
│   └── style.css
├── tests/
│   └── test_app.py
├── .gitignore
└── README.md
```

## Git 工作流

```powershell
git status
git add .
git commit -m "feat: improve dashboard and filters"
git push
```

## 后续方向

- 用户注册和登录
- 月度学习趋势图
- 标签管理
- 学习目标与提醒
- 部署到 PythonAnywhere、Render 或其他云平台


## 生产部署

项目已经提供以下生产部署文件：

- `wsgi.py`：PythonAnywhere、Gunicorn 等 WSGI 服务入口
- `requirements-prod.txt`：Gunicorn 和 Waitress 生产服务器
- `Procfile`：Render、Railway 等平台启动命令
- `.env.example`：生产环境变量示例

部署时务必设置安全的环境变量：

```text
SECRET_KEY=一段足够长的随机字符串
SESSION_COOKIE_SECURE=1
```

SQLite 必须放在持久化磁盘中，否则重新部署可能造成数据丢失。
