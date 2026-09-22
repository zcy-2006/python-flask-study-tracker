import csv
import io
import json
import os
import re
import secrets
import sqlite3
from datetime import date, datetime, timedelta
from functools import wraps

from flask import (
    Flask,
    Response,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_wtf.csrf import CSRFProtect
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from werkzeug.security import check_password_hash, generate_password_hash

WEEKDAY_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
PER_PAGE = 10

csrf = CSRFProtect()

login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.login_message = "请先登录后再使用学习打卡。"
login_manager.login_message_category = "warning"


class User(UserMixin):
    def __init__(self, user_id, username, password_hash=None, is_admin=0, is_enabled=1):
        self.id = str(user_id)
        self.username = username
        self.password_hash = password_hash
        self.is_admin = bool(is_admin)
        self.is_enabled = bool(is_enabled)

    @property
    def is_active(self):
        return self.is_enabled


@login_manager.user_loader
def load_user(user_id):
    row = get_db().execute(
        """
        SELECT id, username, password_hash, is_admin, is_enabled
        FROM users
        WHERE id = ?
        """,
        (user_id,),
    ).fetchone()
    if row is None:
        return None
    return User(
        row["id"],
        row["username"],
        row["password_hash"],
        row["is_admin"],
        row["is_enabled"],
    )


def register_security_headers(app):
    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Referrer-Policy", "strict-origin-when-cross-origin"
        )
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        return response


def create_app(test_config=None):
    """Create and configure the Flask application."""
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-change-me"),
        DATABASE=os.path.join(app.instance_path, "study_tracker.sqlite"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "0") == "1",
        REMEMBER_COOKIE_HTTPONLY=True,
        REMEMBER_COOKIE_SAMESITE="Lax",
        REMEMBER_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "0") == "1",
    )

    if test_config is not None:
        app.config.update(test_config)

    os.makedirs(app.instance_path, exist_ok=True)

    csrf.init_app(app)
    login_manager.init_app(app)
    register_security_headers(app)
    register_database(app)
    register_routes(app)
    return app


def register_database(app):
    app.teardown_appcontext(close_db)

    with app.app_context():
        init_db()


def get_db():
    """Return one SQLite connection for the current request."""
    if "db" not in g:
        g.db = sqlite3.connect(
            current_app.config["DATABASE"],
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    with current_app.open_resource("schema.sql") as schema_file:
        db.executescript(schema_file.read().decode("utf-8"))
    migrate_db(db)


def migrate_db(db):
    columns = {
        row["name"]
        for row in db.execute("PRAGMA table_info(records)").fetchall()
    }

    if "user_id" not in columns:
        db.execute(
            "ALTER TABLE records ADD COLUMN user_id INTEGER REFERENCES users(id)"
        )

    if "tags" not in columns:
        db.execute(
            "ALTER TABLE records ADD COLUMN tags TEXT NOT NULL DEFAULT ''"
        )

    user_columns = {
        row["name"]
        for row in db.execute("PRAGMA table_info(users)").fetchall()
    }
    if "is_admin" not in user_columns:
        db.execute(
            "ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0"
        )
    if "is_enabled" not in user_columns:
        db.execute(
            "ALTER TABLE users ADD COLUMN is_enabled INTEGER NOT NULL DEFAULT 1"
        )

    db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_records_user_date
        ON records (user_id, study_date DESC)
        """
    )
    db.commit()


def blank_record():
    return {
        "title": "",
        "subject": "",
        "tags": "",
        "duration_minutes": 60,
        "study_date": date.today().isoformat(),
        "notes": "",
        "completed": 0,
    }


def normalize_tags(value):
    tags = []
    for part in re.split(r"[,，]", value or ""):
        tag = part.strip()
        if tag and tag not in tags:
            tags.append(tag)
    return ",".join(tags)


def read_record_form(form):
    raw_duration = form.get("duration_minutes", "").strip()
    try:
        duration = int(raw_duration)
    except ValueError:
        duration = raw_duration

    return {
        "title": form.get("title", "").strip(),
        "subject": form.get("subject", "").strip(),
        "tags": normalize_tags(form.get("tags", "")),
        "duration_minutes": duration,
        "study_date": form.get("study_date", "").strip(),
        "notes": form.get("notes", "").strip(),
        "completed": 1 if form.get("completed") == "1" else 0,
    }


def validate_record(record):
    if not record["title"]:
        return "请填写学习内容。"
    if len(record["title"]) > 100:
        return "学习内容不能超过 100 个字符。"
    if len(record["subject"]) > 50:
        return "学习科目不能超过 50 个字符。"
    if len(record["tags"]) > 200:
        return "标签总长度不能超过 200 个字符。"
    tag_list = [tag for tag in record["tags"].split(",") if tag]
    if len(tag_list) > 10:
        return "最多只能添加 10 个标签。"
    if any(len(tag) > 20 for tag in tag_list):
        return "每个标签不能超过 20 个字符。"
    if not isinstance(record["duration_minutes"], int):
        return "学习时长必须是整数。"
    if not 1 <= record["duration_minutes"] <= 1440:
        return "学习时长必须在 1 到 1440 分钟之间。"
    if not is_valid_date(record["study_date"]):
        return "请选择有效的学习日期。"
    if len(record["notes"]) > 500:
        return "学习笔记不能超过 500 个字符。"
    return None


def validate_registration(username, password, confirm_password):
    if not username:
        return "请填写用户名。"
    if len(username) < 3 or len(username) > 30:
        return "用户名长度必须在 3 到 30 个字符之间。"
    if not re.fullmatch(r"[A-Za-z0-9_\-\u4e00-\u9fff]{3,30}", username):
        return "用户名只能包含中文、字母、数字、下划线或连字符。"
    if len(password) < 8:
        return "密码至少需要 8 个字符。"
    if len(password) > 128:
        return "密码不能超过 128 个字符。"
    if password != confirm_password:
        return "两次输入的密码不一致。"
    return None


def create_user(username, password):
    db = get_db()
    is_first_user = db.execute("SELECT COUNT(*) AS count FROM users").fetchone()[
        "count"
    ] == 0

    cursor = db.execute(
        """
        INSERT INTO users (username, password_hash, is_admin)
        VALUES (?, ?, ?)
        """,
        (username, generate_password_hash(password), 1 if is_first_user else 0),
    )
    user_id = cursor.lastrowid

    daily_goal = 60
    weekly_goal = 300
    if is_first_user:
        legacy_table = db.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = 'settings'
            """
        ).fetchone()
        if legacy_table is not None:
            legacy_settings = db.execute(
                "SELECT * FROM settings WHERE id = 1"
            ).fetchone()
            if legacy_settings is not None:
                daily_goal = legacy_settings["daily_goal_minutes"]
                weekly_goal = legacy_settings["weekly_goal_minutes"]

        db.execute(
            "UPDATE records SET user_id = ? WHERE user_id IS NULL",
            (user_id,),
        )

    db.execute(
        """
        INSERT INTO user_settings
            (user_id, daily_goal_minutes, weekly_goal_minutes)
        VALUES (?, ?, ?)
        """,
        (user_id, daily_goal, weekly_goal),
    )
    db.commit()
    return load_user(user_id)


def is_valid_date(value):
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except (TypeError, ValueError):
        return False
    return True


def read_filters(args):
    selected_date = args.get("date", "").strip()
    query = args.get("q", "").strip()[:100]
    selected_subject = args.get("subject", "").strip()[:50]
    selected_tag = args.get("tag", "").strip()[:20]
    invalid_date = bool(selected_date and not is_valid_date(selected_date))

    if invalid_date:
        selected_date = ""

    filters = {
        "date": selected_date,
        "q": query,
        "subject": selected_subject,
        "tag": selected_tag,
    }
    return filters, invalid_date


def build_record_query(filters, user_id):
    conditions = ["user_id = ?"]
    params = [user_id]

    if filters["date"]:
        conditions.append("study_date = ?")
        params.append(filters["date"])

    if filters["q"]:
        search_value = filters["q"]
        conditions.append(
            """
            (
                instr(lower(title), lower(?)) > 0
                OR instr(lower(subject), lower(?)) > 0
                OR instr(lower(notes), lower(?)) > 0
                OR instr(lower(tags), lower(?)) > 0
            )
            """
        )
        params.extend([search_value, search_value, search_value, search_value])

    if filters["subject"]:
        conditions.append("subject = ?")
        params.append(filters["subject"])

    if filters["tag"]:
        conditions.append(
            "instr(',' || lower(tags) || ',', ',' || lower(?) || ',') > 0"
        )
        params.append(filters["tag"])

    return " WHERE " + " AND ".join(conditions), params


def read_page(args, total_records):
    try:
        page = int(args.get("page", "1"))
    except (TypeError, ValueError):
        page = 1

    total_pages = max(1, (total_records + PER_PAGE - 1) // PER_PAGE)
    page = max(1, min(page, total_pages))
    return page, total_pages


def get_user_tags(db, user_id):
    rows = db.execute(
        """
        SELECT tags
        FROM records
        WHERE user_id = ? AND tags <> ''
        """,
        (user_id,),
    ).fetchall()
    tags = set()
    for row in rows:
        tags.update(tag for tag in row["tags"].split(",") if tag)
    return sorted(tags, key=lambda value: value.casefold())


def insert_record(db, user_id, record):
    db.execute(
        """
        INSERT INTO records
            (user_id, title, subject, tags, duration_minutes,
             study_date, notes, completed)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            record["title"],
            record["subject"],
            record["tags"],
            record["duration_minutes"],
            record["study_date"],
            record["notes"],
            record["completed"],
        ),
    )


def filter_redirect_args(filters):
    return {
        key: value
        for key, value in filters.items()
        if value
    }


def get_record_or_404(record_id):
    record = get_db().execute(
        "SELECT * FROM records WHERE id = ? AND user_id = ?",
        (record_id, current_user.id),
    ).fetchone()
    if record is None:
        abort(404)
    return record


def get_settings(db, user_id):
    setting = db.execute(
        "SELECT * FROM user_settings WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if setting is None:
        db.execute(
            """
            INSERT INTO user_settings
                (user_id, daily_goal_minutes, weekly_goal_minutes)
            VALUES (?, 60, 300)
            """,
            (user_id,),
        )
        db.commit()
        setting = db.execute(
            "SELECT * FROM user_settings WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    return dict(setting)


def read_settings_form(form):
    raw_daily = form.get("daily_goal_minutes", "").strip()
    raw_weekly = form.get("weekly_goal_minutes", "").strip()

    try:
        daily_goal = int(raw_daily)
    except ValueError:
        daily_goal = raw_daily

    try:
        weekly_goal = int(raw_weekly)
    except ValueError:
        weekly_goal = raw_weekly

    return {
        "daily_goal_minutes": daily_goal,
        "weekly_goal_minutes": weekly_goal,
    }


def validate_settings(settings):
    if not isinstance(settings["daily_goal_minutes"], int):
        return "每日目标必须是整数。"
    if not isinstance(settings["weekly_goal_minutes"], int):
        return "每周目标必须是整数。"
    if not 1 <= settings["daily_goal_minutes"] <= 1440:
        return "每日目标必须在 1 到 1440 分钟之间。"
    if not 1 <= settings["weekly_goal_minutes"] <= 10080:
        return "每周目标必须在 1 到 10080 分钟之间。"
    if settings["weekly_goal_minutes"] < settings["daily_goal_minutes"]:
        return "每周目标不能小于每日目标。"
    return None


def build_trend(db, end_date, user_id, days=7):
    start_date = end_date - timedelta(days=days - 1)
    rows = db.execute(
        """
        SELECT study_date, COALESCE(SUM(duration_minutes), 0) AS total_minutes
        FROM records
        WHERE user_id = ? AND study_date BETWEEN ? AND ?
        GROUP BY study_date
        """,
        (user_id, start_date.isoformat(), end_date.isoformat()),
    ).fetchall()
    minutes_by_date = {
        row["study_date"]: row["total_minutes"]
        for row in rows
    }

    trend = []
    for offset in range(days):
        current_date = start_date + timedelta(days=offset)
        trend.append(
            {
                "date": current_date.isoformat(),
                "label": "今天"
                if current_date == end_date
                else WEEKDAY_LABELS[current_date.weekday()],
                "minutes": minutes_by_date.get(current_date.isoformat(), 0),
            }
        )

    max_minutes = max([point["minutes"] for point in trend] or [0])
    return trend, max(max_minutes, 1)


def build_progress(actual, goal):
    percent = round(actual * 100 / goal) if goal else 0
    return {
        "actual": actual,
        "goal": goal,
        "percent": percent,
        "bar_percent": min(percent, 100),
        "remaining": max(goal - actual, 0),
    }



def get_month_summary(db, end_date, user_id):
    month_start = end_date.replace(day=1)
    summary_row = db.execute(
        """
        SELECT
            COUNT(*) AS total_records,
            COALESCE(SUM(duration_minutes), 0) AS total_minutes,
            COUNT(DISTINCT study_date) AS active_days
        FROM records
        WHERE user_id = ? AND study_date BETWEEN ? AND ?
        """,
        (user_id, month_start.isoformat(), end_date.isoformat()),
    ).fetchone()
    summary = dict(summary_row)
    summary["average_minutes"] = (
        round(summary["total_minutes"] / summary["active_days"])
        if summary["active_days"]
        else 0
    )

    best_day = db.execute(
        """
        SELECT study_date, SUM(duration_minutes) AS total_minutes
        FROM records
        WHERE user_id = ? AND study_date BETWEEN ? AND ?
        GROUP BY study_date
        ORDER BY total_minutes DESC, study_date DESC
        LIMIT 1
        """,
        (user_id, month_start.isoformat(), end_date.isoformat()),
    ).fetchone()

    return summary, best_day


def build_heatmap(db, end_date, user_id, daily_goal, weeks=8):
    current_week_start = end_date - timedelta(days=end_date.weekday())
    start_date = current_week_start - timedelta(weeks=weeks - 1)
    rows = db.execute(
        """
        SELECT study_date, COALESCE(SUM(duration_minutes), 0) AS total_minutes
        FROM records
        WHERE user_id = ? AND study_date BETWEEN ? AND ?
        GROUP BY study_date
        """,
        (user_id, start_date.isoformat(), end_date.isoformat()),
    ).fetchall()
    minutes_by_date = {
        row["study_date"]: row["total_minutes"]
        for row in rows
    }

    heatmap_weeks = []
    for week_offset in range(weeks):
        week_start = start_date + timedelta(weeks=week_offset)
        week = []
        for day_offset in range(7):
            current_date = week_start + timedelta(days=day_offset)
            minutes = minutes_by_date.get(current_date.isoformat(), 0)

            if current_date > end_date or minutes == 0:
                level = 0
            elif minutes < daily_goal * 0.5:
                level = 1
            elif minutes < daily_goal:
                level = 2
            elif minutes < daily_goal * 1.5:
                level = 3
            else:
                level = 4

            week.append(
                {
                    "date": current_date.isoformat(),
                    "minutes": minutes,
                    "level": level,
                    "future": current_date > end_date,
                }
            )
        heatmap_weeks.append(week)

    return heatmap_weeks, start_date, end_date



def validate_password_change(current_password, new_password, confirm_password):
    if not current_password:
        return "请输入当前密码。"
    if len(new_password) < 8:
        return "新密码至少需要 8 个字符。"
    if len(new_password) > 128:
        return "新密码不能超过 128 个字符。"
    if new_password != confirm_password:
        return "两次输入的新密码不一致。"
    if current_password == new_password:
        return "新密码不能与当前密码相同。"
    return None


def calculate_streak(study_dates, today=None):
    today = today or date.today()
    valid_dates = set()

    for value in study_dates:
        try:
            valid_dates.add(datetime.strptime(value, "%Y-%m-%d").date())
        except (TypeError, ValueError):
            continue

    if not valid_dates:
        return 0

    cursor = today if today in valid_dates else today - timedelta(days=1)
    streak = 0
    while cursor in valid_dates:
        streak += 1
        cursor -= timedelta(days=1)
    return streak



def parse_backup_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError("备份文件格式不正确。")
    if payload.get("format") != "study-tracker-backup":
        raise ValueError("这不是学习打卡网站的备份文件。")
    if payload.get("version") != 1:
        raise ValueError("暂不支持这个备份版本。")

    settings_data = payload.get("settings")
    if not isinstance(settings_data, dict):
        raise ValueError("备份文件缺少学习目标。")
    settings_data = {
        "daily_goal_minutes": settings_data.get("daily_goal_minutes"),
        "weekly_goal_minutes": settings_data.get("weekly_goal_minutes"),
    }
    settings_error = validate_settings(settings_data)
    if settings_error:
        raise ValueError("学习目标无效：" + settings_error)

    raw_records = payload.get("records", [])
    if not isinstance(raw_records, list):
        raise ValueError("备份中的学习记录格式不正确。")
    if len(raw_records) > 5000:
        raise ValueError("一次最多导入 5000 条学习记录。")

    records = []
    for index, row in enumerate(raw_records, start=1):
        if not isinstance(row, dict):
            raise ValueError("第 %d 条学习记录格式不正确。" % index)

        record = {
            "title": str(row.get("title", "")).strip(),
            "subject": str(row.get("subject", "")).strip(),
            "tags": normalize_tags(str(row.get("tags", ""))),
            "duration_minutes": row.get("duration_minutes"),
            "study_date": str(row.get("study_date", "")).strip(),
            "notes": str(row.get("notes", "")).strip(),
            "completed": 1
            if row.get("completed") in (1, True, "1", "true", "True")
            else 0,
        }
        record_error = validate_record(record)
        if record_error:
            raise ValueError("第 %d 条学习记录无效：%s" % (index, record_error))
        records.append(record)

    return settings_data, records



def get_app_settings(db):
    setting = db.execute(
        "SELECT * FROM app_settings WHERE id = 1"
    ).fetchone()
    if setting is None:
        db.execute(
            """
            INSERT INTO app_settings
                (id, registration_enabled, registration_invite_code)
            VALUES (1, 1, '')
            """
        )
        db.commit()
        setting = db.execute(
            "SELECT * FROM app_settings WHERE id = 1"
        ).fetchone()
    return dict(setting)


def read_app_settings_form(form):
    invite_code = form.get("registration_invite_code", "").strip()
    return {
        "registration_enabled": 1
        if form.get("registration_enabled") == "1"
        else 0,
        "registration_invite_code": invite_code,
    }


def validate_app_settings(settings_data):
    if len(settings_data["registration_invite_code"]) > 50:
        return "邀请码不能超过 50 个字符。"
    return None


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)
        return view(*args, **kwargs)

    return wrapped



def get_client_ip():
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or ""


def log_event(db, event, detail="", user_id=None):
    if user_id is None and current_user.is_authenticated:
        user_id = current_user.id
    db.execute(
        """
        INSERT INTO audit_logs (user_id, event, detail, ip_address)
        VALUES (?, ?, ?, ?)
        """,
        (user_id, event, detail[:500], get_client_ip()),
    )
    db.commit()


def login_attempt_count(db, username):
    since = (datetime.utcnow() - timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S")
    row = db.execute(
        """
        SELECT COUNT(*) AS count
        FROM login_attempts
        WHERE username = ? AND ip_address = ? AND attempted_at >= ?
        """,
        (username, get_client_ip(), since),
    ).fetchone()
    return row["count"]


def record_login_failure(db, username):
    db.execute(
        """
        INSERT INTO login_attempts (username, ip_address)
        VALUES (?, ?)
        """,
        (username, get_client_ip()),
    )
    db.commit()


def clear_login_failures(db, username):
    db.execute(
        "DELETE FROM login_attempts WHERE username = ? AND ip_address = ?",
        (username, get_client_ip()),
    )
    db.commit()


def register_routes(app):
    @app.route("/register", methods=("GET", "POST"))
    def register():
        if current_user.is_authenticated:
            return redirect(url_for("index"))

        db = get_db()
        registration_settings = get_app_settings(db)
        user_count = db.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"]
        registration_closed = user_count > 0 and not registration_settings["registration_enabled"]
        invite_required = user_count > 0 and bool(registration_settings["registration_invite_code"])
        if registration_closed:
            return render_template("register.html", registration_closed=True, invite_required=invite_required)

        username = ""
        error = None
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            confirm_password = request.form.get("confirm_password", "")
            invite_code = request.form.get("invite_code", "").strip()
            error = validate_registration(username, password, confirm_password)
            if error is None and invite_required and not secrets.compare_digest(invite_code, registration_settings["registration_invite_code"]):
                error = "邀请码不正确。"
            if error is None:
                try:
                    user = create_user(username, password)
                    login_user(user)
                except sqlite3.IntegrityError:
                    error = "该用户名已经被注册。"
                if error is None:
                    log_event(
                        get_db(),
                        "user.registered",
                        "新用户注册：" + username,
                        user_id=user.id,
                    )
                    flash("注册成功，欢迎开始学习。", "success")
                    return redirect(url_for("index"))
            flash(error, "error")
        return render_template("register.html", username=username, registration_closed=False, invite_required=invite_required)

    @app.route("/login", methods=("GET", "POST"))
    def login():
        if current_user.is_authenticated:
            return redirect(url_for("index"))

        username = ""
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            db = get_db()
            if login_attempt_count(db, username) >= 5:
                flash("登录失败次数过多，请 15 分钟后再试。", "error")
                return render_template("login.html", username=username)

            row = db.execute(
                """
                SELECT id, username, password_hash, is_admin, is_enabled
                FROM users
                WHERE username = ?
                """,
                (username,),
            ).fetchone()

            if row is not None and not row["is_enabled"]:
                flash("该账号已被管理员停用。", "error")
                return render_template("login.html", username=username)

            if row is not None and check_password_hash(
                row["password_hash"], password
            ):
                clear_login_failures(db, username)
                login_user(
                    User(
                        row["id"],
                        row["username"],
                        row["password_hash"],
                        row["is_admin"],
                        row["is_enabled"],
                    ),
                    remember=request.form.get("remember") == "1",
                )
                log_event(db, "user.login", "用户登录：" + username, user_id=row["id"])
                flash("登录成功。", "success")
                return redirect(url_for("index"))

            record_login_failure(db, username)
            log_event(db, "user.login_failed", "登录失败：" + username)
            flash("用户名或密码不正确。", "error")

        return render_template("login.html", username=username)

    @app.post("/logout")
    @login_required
    def logout():
        log_event(get_db(), "user.logout", "用户退出登录")
        logout_user()
        flash("你已退出登录。", "success")
        return redirect(url_for("login"))

    @app.get("/")
    @login_required
    def index():
        filters, invalid_date = read_filters(request.args)
        if invalid_date:
            flash("筛选日期格式不正确，已忽略该条件。", "warning")

        user_id = current_user.id
        where_clause, params = build_record_query(filters, user_id)
        db = get_db()

        summary_row = db.execute(
            """
            SELECT
                COUNT(*) AS total_records,
                COALESCE(SUM(duration_minutes), 0) AS total_minutes,
                COALESCE(SUM(completed), 0) AS completed_records
            FROM records
            """
            + where_clause,
            params,
        ).fetchone()
        summary = dict(summary_row)
        if summary["total_records"]:
            summary["completion_rate"] = round(
                summary["completed_records"] * 100 / summary["total_records"]
            )
        else:
            summary["completion_rate"] = 0

        page, total_pages = read_page(
            request.args,
            summary["total_records"],
        )
        page_numbers = list(
            range(max(1, page - 2), min(total_pages, page + 2) + 1)
        )
        offset = (page - 1) * PER_PAGE
        records = db.execute(
            "SELECT * FROM records"
            + where_clause
            + " ORDER BY study_date DESC, id DESC LIMIT ? OFFSET ?",
            params + [PER_PAGE, offset],
        ).fetchall()

        today_date = date.today()
        week_start = today_date - timedelta(days=today_date.weekday())
        week_end = week_start + timedelta(days=6)
        week_summary = db.execute(
            """
            SELECT
                COUNT(*) AS total_records,
                COALESCE(SUM(duration_minutes), 0) AS total_minutes,
                COALESCE(SUM(completed), 0) AS completed_records
            FROM records
            WHERE user_id = ? AND study_date BETWEEN ? AND ?
            """,
            (user_id, week_start.isoformat(), week_end.isoformat()),
        ).fetchone()

        streak_dates = [
            row["study_date"]
            for row in db.execute(
                """
                SELECT DISTINCT study_date
                FROM records
                WHERE user_id = ?
                ORDER BY study_date DESC
                """,
                (user_id,),
            ).fetchall()
        ]
        streak = calculate_streak(streak_dates, today_date)

        subject_stats = db.execute(
            """
            SELECT
                subject,
                COUNT(*) AS total_records,
                COALESCE(SUM(duration_minutes), 0) AS total_minutes
            FROM records
            """
            + where_clause
            + """
            GROUP BY subject
            ORDER BY total_minutes DESC, subject ASC
            LIMIT 5
            """,
            params,
        ).fetchall()
        max_subject_minutes = (
            subject_stats[0]["total_minutes"] if subject_stats else 0
        )

        goals = get_settings(db, user_id)
        trend, max_trend_minutes = build_trend(db, today_date, user_id)
        heatmap_weeks, heatmap_start, heatmap_end = build_heatmap(
            db,
            today_date,
            user_id,
            goals["daily_goal_minutes"],
        )
        month_summary, best_day = get_month_summary(db, today_date, user_id)
        daily_progress = build_progress(
            trend[-1]["minutes"], goals["daily_goal_minutes"]
        )
        weekly_progress = build_progress(
            week_summary["total_minutes"], goals["weekly_goal_minutes"]
        )

        subjects = db.execute(
            """
            SELECT DISTINCT subject
            FROM records
            WHERE user_id = ? AND subject <> ''
            ORDER BY subject COLLATE NOCASE
            """,
            (user_id,),
        ).fetchall()
        all_tags = get_user_tags(db, user_id)

        return render_template(
            "index.html",
            records=records,
            summary=summary,
            week_summary=week_summary,
            week_start=week_start.isoformat(),
            week_end=week_end.isoformat(),
            streak=streak,
            subject_stats=subject_stats,
            max_subject_minutes=max_subject_minutes,
            goals=goals,
            trend=trend,
            max_trend_minutes=max_trend_minutes,
            heatmap_weeks=heatmap_weeks,
            heatmap_start=heatmap_start.isoformat(),
            heatmap_end=heatmap_end.isoformat(),
            month_summary=month_summary,
            best_day=best_day,
            daily_progress=daily_progress,
            weekly_progress=weekly_progress,
            subjects=subjects,
            all_tags=all_tags,
            filters=filters,
            page=page,
            total_pages=total_pages,
            page_numbers=page_numbers,
            has_filters=any(filters.values()),
            today=today_date.isoformat(),
        )

    @app.route("/records/new", methods=("GET", "POST"))
    @login_required
    def new_record():
        record = blank_record()

        if request.method == "POST":
            record = read_record_form(request.form)
            error = validate_record(record)

            if error is None:
                db = get_db()
                insert_record(db, current_user.id, record)
                db.commit()
                log_event(
                    db,
                    "record.created",
                    "新增学习记录：" + record["title"],
                )
                flash("学习记录已添加。", "success")
                return redirect(url_for("index"))

            flash(error, "error")

        return render_template(
            "form.html",
            record=record,
            page_title="新增学习记录",
            submit_label="保存记录",
        )

    @app.route("/records/<int:record_id>/edit", methods=("GET", "POST"))
    @login_required
    def edit_record(record_id):
        existing = get_record_or_404(record_id)
        record = dict(existing)

        if request.method == "POST":
            record = read_record_form(request.form)
            error = validate_record(record)

            if error is None:
                db = get_db()
                db.execute(
                    """
                    UPDATE records
                    SET title = ?, subject = ?, tags = ?, duration_minutes = ?,
                        study_date = ?, notes = ?, completed = ?
                    WHERE id = ? AND user_id = ?
                    """,
                    (
                        record["title"],
                        record["subject"],
                        record["tags"],
                        record["duration_minutes"],
                        record["study_date"],
                        record["notes"],
                        record["completed"],
                        record_id,
                        current_user.id,
                    ),
                )
                db.commit()
                log_event(
                    db,
                    "record.updated",
                    "更新学习记录：" + record["title"],
                )
                flash("学习记录已更新。", "success")
                return redirect(url_for("index"))

            flash(error, "error")

        return render_template(
            "form.html",
            record=record,
            page_title="编辑学习记录",
            submit_label="保存修改",
        )

    @app.post("/records/<int:record_id>/toggle")
    @login_required
    def toggle_record(record_id):
        record = get_record_or_404(record_id)
        completed = 0 if record["completed"] else 1
        db = get_db()
        db.execute(
            """
            UPDATE records
            SET completed = ?
            WHERE id = ? AND user_id = ?
            """,
            (completed, record_id, current_user.id),
        )
        db.commit()
        log_event(
            db,
            "record.toggled",
            "更新完成状态，记录 ID：%s" % record_id,
        )
        flash("完成状态已更新。", "success")

        filters, _ = read_filters(request.form)
        return redirect(url_for("index", **filter_redirect_args(filters)))

    @app.post("/records/<int:record_id>/delete")
    @login_required
    def delete_record(record_id):
        get_record_or_404(record_id)
        db = get_db()
        db.execute(
            "DELETE FROM records WHERE id = ? AND user_id = ?",
            (record_id, current_user.id),
        )
        db.commit()
        log_event(db, "record.deleted", "删除记录 ID：%s" % record_id)
        flash("学习记录已删除。", "success")

        filters, _ = read_filters(request.form)
        return redirect(url_for("index", **filter_redirect_args(filters)))

    @app.get("/export.csv")
    @login_required
    def export_records():
        filters, _ = read_filters(request.args)
        where_clause, params = build_record_query(filters, current_user.id)
        records = get_db().execute(
            "SELECT * FROM records"
            + where_clause
            + " ORDER BY study_date DESC, id DESC",
            params,
        ).fetchall()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "ID",
                "学习内容",
                "科目",
                "标签",
                "学习时长（分钟）",
                "学习日期",
                "状态",
                "学习笔记",
                "创建时间",
            ]
        )
        for record in records:
            writer.writerow(
                [
                    record["id"],
                    record["title"],
                    record["subject"],
                    record["tags"],
                    record["duration_minutes"],
                    record["study_date"],
                    "已完成" if record["completed"] else "进行中",
                    record["notes"],
                    record["created_at"],
                ]
            )

        csv_content = output.getvalue().encode("utf-8-sig")
        return Response(
            csv_content,
            content_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": "attachment; filename=study-records.csv"
            },
        )

    @app.route("/settings", methods=("GET", "POST"))
    @login_required
    def settings_page():
        db = get_db()
        settings_data = get_settings(db, current_user.id)

        if request.method == "POST":
            settings_data = read_settings_form(request.form)
            error = validate_settings(settings_data)

            if error is None:
                db.execute(
                    """
                    UPDATE user_settings
                    SET daily_goal_minutes = ?,
                        weekly_goal_minutes = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE user_id = ?
                    """,
                    (
                        settings_data["daily_goal_minutes"],
                        settings_data["weekly_goal_minutes"],
                        current_user.id,
                    ),
                )
                db.commit()
                log_event(db, "settings.updated", "更新每日和每周目标")
                flash("学习目标已更新。", "success")
                return redirect(url_for("settings_page"))

            flash(error, "error")

        return render_template("settings.html", settings=settings_data)

    @app.route("/account", methods=("GET", "POST"))
    @login_required
    def account_page():
        db = get_db()
        user_row = db.execute(
            """
            SELECT id, username, password_hash, created_at
            FROM users
            WHERE id = ?
            """,
            (current_user.id,),
        ).fetchone()

        account_stats = db.execute(
            """
            SELECT
                COUNT(*) AS total_records,
                COALESCE(SUM(duration_minutes), 0) AS total_minutes,
                COUNT(DISTINCT study_date) AS active_days
            FROM records
            WHERE user_id = ?
            """,
            (current_user.id,),
        ).fetchone()

        recent_activity = db.execute(
            """
            SELECT event, detail, ip_address, created_at
            FROM audit_logs
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT 10
            """,
            (current_user.id,),
        ).fetchall()

        if request.method == "POST":
            current_password = request.form.get("current_password", "")
            new_password = request.form.get("new_password", "")
            confirm_password = request.form.get("confirm_password", "")
            error = validate_password_change(
                current_password,
                new_password,
                confirm_password,
            )

            if error is None and not check_password_hash(
                user_row["password_hash"], current_password
            ):
                error = "当前密码不正确。"

            if error is None:
                db.execute(
                    "UPDATE users SET password_hash = ? WHERE id = ?",
                    (generate_password_hash(new_password), current_user.id),
                )
                db.commit()
                flash("密码已更新。", "success")
                return redirect(url_for("account_page"))

            flash(error, "error")

        return render_template(
            "account.html",
            account=dict(user_row),
            account_stats=account_stats,
            recent_activity=recent_activity,
        )

    @app.post("/account/delete")
    @login_required
    def delete_account():
        password = request.form.get("password", "")
        db = get_db()
        user_row = db.execute(
            "SELECT password_hash, is_admin FROM users WHERE id = ?",
            (current_user.id,),
        ).fetchone()
        if user_row is None or not check_password_hash(user_row["password_hash"], password):
            flash("密码不正确，无法注销账号。", "error")
            return redirect(url_for("account_page"))
        if user_row["is_admin"]:
            admin_count = db.execute(
                "SELECT COUNT(*) AS count FROM users WHERE is_admin = 1 AND is_enabled = 1"
            ).fetchone()["count"]
            if admin_count <= 1:
                flash("最后一名管理员不能注销账号。", "error")
                return redirect(url_for("account_page"))
        user_id = current_user.id
        username = current_user.username
        logout_user()
        log_event(
            db,
            "user.deleted",
            "用户注销账号：" + username,
            user_id=user_id,
        )
        db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        db.commit()
        flash("账号已注销。", "success")
        return redirect(url_for("login"))

    @app.get("/backup.json")
    @login_required
    def backup_json():
        db = get_db()
        records = db.execute(
            """
            SELECT title, subject, tags, duration_minutes,
                   study_date, notes, completed, created_at
            FROM records
            WHERE user_id = ?
            ORDER BY study_date, id
            """,
            (current_user.id,),
        ).fetchall()
        settings_data = get_settings(db, current_user.id)
        settings_data["updated_at"] = str(settings_data.get("updated_at", ""))
        backup_records = []
        for record in records:
            record_data = dict(record)
            record_data["created_at"] = str(record_data.get("created_at", ""))
            backup_records.append(record_data)

        payload = {
            "format": "study-tracker-backup",
            "version": 1,
            "exported_at": datetime.utcnow().isoformat() + "Z",
            "settings": settings_data,
            "records": backup_records,
        }
        return Response(
            json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
            content_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": "attachment; filename=study-tracker-backup.json"
            },
        )

    @app.post("/import")
    @login_required
    def import_backup():
        backup_file = request.files.get("backup_file")
        mode = request.form.get("mode", "merge")
        if mode not in ("merge", "replace"):
            mode = "merge"

        if backup_file is None or not backup_file.filename:
            flash("请选择备份文件。", "error")
            return redirect(url_for("account_page"))

        raw_data = backup_file.read(1000001)
        if len(raw_data) > 1000000:
            flash("备份文件不能超过 1 MB。", "error")
            return redirect(url_for("account_page"))

        try:
            payload = json.loads(raw_data.decode("utf-8-sig"))
            settings_data, imported_records = parse_backup_payload(payload)
        except (UnicodeDecodeError, json.JSONDecodeError):
            flash("备份文件不是有效的 JSON 文件。", "error")
            return redirect(url_for("account_page"))
        except ValueError as error:
            flash(str(error), "error")
            return redirect(url_for("account_page"))

        db = get_db()
        if mode == "replace":
            db.execute("DELETE FROM records WHERE user_id = ?", (current_user.id,))
            imported_count = len(imported_records)
            for record in imported_records:
                insert_record(db, current_user.id, record)
            skipped_count = 0
        else:
            imported_count = 0
            skipped_count = 0
            for record in imported_records:
                duplicate = db.execute(
                    """
                    SELECT 1
                    FROM records
                    WHERE user_id = ? AND title = ? AND subject = ?
                      AND tags = ? AND duration_minutes = ?
                      AND study_date = ? AND notes = ?
                    """,
                    (
                        current_user.id,
                        record["title"],
                        record["subject"],
                        record["tags"],
                        record["duration_minutes"],
                        record["study_date"],
                        record["notes"],
                    ),
                ).fetchone()
                if duplicate is not None:
                    skipped_count += 1
                    continue
                insert_record(db, current_user.id, record)
                imported_count += 1

        db.execute(
            """
            UPDATE user_settings
            SET daily_goal_minutes = ?,
                weekly_goal_minutes = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
            """,
            (
                settings_data["daily_goal_minutes"],
                settings_data["weekly_goal_minutes"],
                current_user.id,
            ),
        )
        db.commit()
        log_event(
            db,
            "backup.imported",
            "导入备份：新增 %d 条，跳过 %d 条" % (imported_count, skipped_count),
        )
        flash(
            "导入完成：新增 %d 条，跳过 %d 条。"
            % (imported_count, skipped_count),
            "success",
        )
        return redirect(url_for("account_page"))

    @app.route("/admin", methods=("GET", "POST"))
    @admin_required
    def admin_page():
        db = get_db()
        app_settings = get_app_settings(db)

        if request.method == "POST":
            action = request.form.get("action", "settings")

            if action == "settings":
                app_settings = read_app_settings_form(request.form)
                error = validate_app_settings(app_settings)
                if error is None:
                    db.execute(
                        """
                        UPDATE app_settings
                        SET registration_enabled = ?,
                            registration_invite_code = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = 1
                        """,
                        (
                            app_settings["registration_enabled"],
                            app_settings["registration_invite_code"],
                        ),
                    )
                    db.commit()
                    log_event(db, "admin.registration_updated", "更新注册设置")
                    flash("注册设置已更新。", "success")
                    return redirect(url_for("admin_page"))
                flash(error, "error")

            elif action == "toggle_enabled":
                try:
                    target_id = int(request.form.get("user_id", ""))
                except (TypeError, ValueError):
                    target_id = 0
                target = db.execute(
                    "SELECT id, username, is_enabled FROM users WHERE id = ?",
                    (target_id,),
                ).fetchone()
                if target is None:
                    flash("用户不存在。", "error")
                elif str(target["id"]) == str(current_user.id):
                    flash("不能停用自己的账号。", "error")
                else:
                    enabled = 0 if target["is_enabled"] else 1
                    db.execute(
                        "UPDATE users SET is_enabled = ? WHERE id = ?",
                        (enabled, target_id),
                    )
                    db.commit()
                    log_event(
                        db,
                        "admin.user_enabled" if enabled else "admin.user_disabled",
                        ("启用用户：" if enabled else "停用用户：") + target["username"],
                    )
                    flash("用户状态已更新。", "success")
                return redirect(url_for("admin_page"))

            elif action == "toggle_admin":
                try:
                    target_id = int(request.form.get("user_id", ""))
                except (TypeError, ValueError):
                    target_id = 0

                target = db.execute(
                    "SELECT id, username, is_admin FROM users WHERE id = ?",
                    (target_id,),
                ).fetchone()
                if target is None:
                    flash("用户不存在。", "error")
                elif str(target["id"]) == str(current_user.id):
                    flash("不能修改自己的管理员状态。", "error")
                else:
                    new_admin = 0 if target["is_admin"] else 1
                    if not new_admin:
                        admin_count = db.execute(
                            "SELECT COUNT(*) AS count FROM users WHERE is_admin = 1"
                        ).fetchone()["count"]
                        if admin_count <= 1:
                            flash("至少需要保留一名管理员。", "error")
                        else:
                            db.execute(
                                "UPDATE users SET is_admin = 0 WHERE id = ?",
                                (target_id,),
                            )
                            db.commit()
                            log_event(db, "admin.user_demoted", "取消管理员：" + target["username"])
                            flash("用户管理员权限已取消。", "success")
                    else:
                        db.execute(
                            "UPDATE users SET is_admin = 1 WHERE id = ?",
                            (target_id,),
                        )
                        db.commit()
                        log_event(db, "admin.user_promoted", "设为管理员：" + target["username"])
                        flash("用户已设为管理员。", "success")
                return redirect(url_for("admin_page"))

        users = db.execute(
            """
            SELECT
                users.id,
                users.username,
                users.is_admin,
                users.is_enabled,
                users.created_at,
                COUNT(records.id) AS total_records,
                COALESCE(SUM(records.duration_minutes), 0) AS total_minutes
            FROM users
            LEFT JOIN records ON records.user_id = users.id
            GROUP BY users.id
            ORDER BY users.id
            """
        ).fetchall()

        recent_events = db.execute(
            """
            SELECT audit_logs.event, audit_logs.detail,
                   audit_logs.ip_address, audit_logs.created_at,
                   COALESCE(users.username, '未登录用户') AS username
            FROM audit_logs
            LEFT JOIN users ON users.id = audit_logs.user_id
            ORDER BY audit_logs.id DESC
            LIMIT 20
            """
        ).fetchall()

        return render_template(
            "admin.html",
            app_settings=app_settings,
            users=users,
            recent_events=recent_events,
        )

    @app.get("/health")
    def health():
        return {"status": "ok"}


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)
