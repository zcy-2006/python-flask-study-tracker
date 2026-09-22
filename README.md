# 学习打卡网站

一个适合 Python 初学者练手的 Flask 网站。它可以把每天的学习内容保存到 SQLite，并支持新增、编辑、删除、完成状态和日期筛选。

## 功能

- 查看全部学习记录
- 按日期筛选记录
- 新增、编辑和删除记录
- 标记完成或取消完成
- 显示记录数、总学习时长和完成数
- 使用 SQLite 持久化数据
- 使用 Bootstrap 适配手机页面

## 技术栈

- Python 3.8+
- Flask 3.0
- SQLite
- Jinja2
- Bootstrap 5

## 本地运行

在项目目录打开 PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m flask --app app run --debug
```

然后打开：

```text
http://127.0.0.1:5000
```

第一次启动时会自动创建 `instance/study_tracker.sqlite`。

## 运行测试

```powershell
python -m unittest discover -s tests -v
```

## 页面和路由

| 地址 | 说明 |
| --- | --- |
| `/` | 学习记录列表 |
| `/?date=2026-09-22` | 按日期筛选 |
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
│   ├── form.html
│   └── index.html
├── static/
│   └── style.css
├── tests/
│   └── test_app.py
├── .gitignore
└── README.md
```

## 提交到 GitHub

```powershell
git add .
git commit -m "feat: build study tracker website"
git push -u origin main
```

## 下一阶段可以增加

- 用户注册和登录
- 每周学习时长图表
- 标签和科目分类
- 数据导出
- 部署到 PythonAnywhere 或其他云平台
