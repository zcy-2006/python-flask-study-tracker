import csv
import io
import os
import sqlite3
from datetime import date, datetime, timedelta

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



WEEKDAY_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def create_app(test_config=None):
    """Create and configure the Flask application."""
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-change-me"),
        DATABASE=os.path.join(app.instance_path, "study_tracker.sqlite"),
    )

    if test_config is not None:
        app.config.update(test_config)

    os.makedirs(app.instance_path, exist_ok=True)

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
    return g.db


def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    with current_app.open_resource("schema.sql") as schema_file:
        db.executescript(schema_file.read().decode("utf-8"))


def blank_record():
    return {
        "title": "",
        "subject": "",
        "duration_minutes": 60,
        "study_date": date.today().isoformat(),
        "notes": "",
        "completed": 0,
    }


def read_record_form(form):
    raw_duration = form.get("duration_minutes", "").strip()
    try:
        duration = int(raw_duration)
    except ValueError:
        duration = raw_duration

    return {
        "title": form.get("title", "").strip(),
        "subject": form.get("subject", "").strip(),
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
    if not isinstance(record["duration_minutes"], int):
        return "学习时长必须是整数。"
    if not 1 <= record["duration_minutes"] <= 1440:
        return "学习时长必须在 1 到 1440 分钟之间。"
    if not is_valid_date(record["study_date"]):
        return "请选择有效的学习日期。"
    if len(record["notes"]) > 500:
        return "学习笔记不能超过 500 个字符。"
    return None


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
    invalid_date = bool(selected_date and not is_valid_date(selected_date))

    if invalid_date:
        selected_date = ""

    filters = {
        "date": selected_date,
        "q": query,
        "subject": selected_subject,
    }
    return filters, invalid_date


def build_record_query(filters):
    conditions = []
    params = []

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
            )
            """
        )
        params.extend([search_value, search_value, search_value])

    if filters["subject"]:
        conditions.append("subject = ?")
        params.append(filters["subject"])

    where_clause = ""
    if conditions:
        where_clause = " WHERE " + " AND ".join(conditions)

    return where_clause, params


def filter_redirect_args(filters):
    return {
        key: value
        for key, value in filters.items()
        if value
    }


def get_record_or_404(record_id):
    record = get_db().execute(
        "SELECT * FROM records WHERE id = ?", (record_id,)
    ).fetchone()
    if record is None:
        abort(404)
    return record


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



def get_settings(db):
    setting = db.execute(
        "SELECT * FROM settings WHERE id = 1"
    ).fetchone()
    if setting is None:
        db.execute(
            """
            INSERT INTO settings
                (id, daily_goal_minutes, weekly_goal_minutes)
            VALUES (1, 60, 300)
            """
        )
        db.commit()
        setting = db.execute(
            "SELECT * FROM settings WHERE id = 1"
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


def build_trend(db, end_date, days=7):
    start_date = end_date - timedelta(days=days - 1)
    rows = db.execute(
        """
        SELECT study_date, COALESCE(SUM(duration_minutes), 0) AS total_minutes
        FROM records
        WHERE study_date BETWEEN ? AND ?
        GROUP BY study_date
        """,
        (start_date.isoformat(), end_date.isoformat()),
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
                "label": "今天" if current_date == end_date else WEEKDAY_LABELS[current_date.weekday()],
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


def register_routes(app):
    @app.get("/")
    def index():
        filters, invalid_date = read_filters(request.args)
        if invalid_date:
            flash("筛选日期格式不正确，已忽略该条件。", "warning")

        where_clause, params = build_record_query(filters)
        db = get_db()

        records = db.execute(
            "SELECT * FROM records"
            + where_clause
            + " ORDER BY study_date DESC, id DESC",
            params,
        ).fetchall()

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
            WHERE study_date BETWEEN ? AND ?
            """,
            (week_start.isoformat(), week_end.isoformat()),
        ).fetchone()

        streak_dates = [
            row["study_date"]
            for row in db.execute(
                "SELECT DISTINCT study_date FROM records ORDER BY study_date DESC"
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

        goals = get_settings(db)
        trend, max_trend_minutes = build_trend(db, today_date)
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
            WHERE subject <> ''
            ORDER BY subject COLLATE NOCASE
            """
        ).fetchall()

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
            daily_progress=daily_progress,
            weekly_progress=weekly_progress,
            subjects=subjects,
            filters=filters,
            has_filters=any(filters.values()),
            today=today_date.isoformat(),
        )

    @app.route("/records/new", methods=("GET", "POST"))
    def new_record():
        record = blank_record()

        if request.method == "POST":
            record = read_record_form(request.form)
            error = validate_record(record)

            if error is None:
                db = get_db()
                db.execute(
                    """
                    INSERT INTO records
                        (title, subject, duration_minutes, study_date, notes, completed)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record["title"],
                        record["subject"],
                        record["duration_minutes"],
                        record["study_date"],
                        record["notes"],
                        record["completed"],
                    ),
                )
                db.commit()
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
                    SET title = ?, subject = ?, duration_minutes = ?,
                        study_date = ?, notes = ?, completed = ?
                    WHERE id = ?
                    """,
                    (
                        record["title"],
                        record["subject"],
                        record["duration_minutes"],
                        record["study_date"],
                        record["notes"],
                        record["completed"],
                        record_id,
                    ),
                )
                db.commit()
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
    def toggle_record(record_id):
        record = get_record_or_404(record_id)
        completed = 0 if record["completed"] else 1
        db = get_db()
        db.execute(
            "UPDATE records SET completed = ? WHERE id = ?",
            (completed, record_id),
        )
        db.commit()
        flash("完成状态已更新。", "success")

        filters, _ = read_filters(request.form)
        return redirect(url_for("index", **filter_redirect_args(filters)))

    @app.post("/records/<int:record_id>/delete")
    def delete_record(record_id):
        get_record_or_404(record_id)
        db = get_db()
        db.execute("DELETE FROM records WHERE id = ?", (record_id,))
        db.commit()
        flash("学习记录已删除。", "success")

        filters, _ = read_filters(request.form)
        return redirect(url_for("index", **filter_redirect_args(filters)))

    @app.get("/export.csv")
    def export_records():
        filters, _ = read_filters(request.args)
        where_clause, params = build_record_query(filters)
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
    def settings_page():
        db = get_db()
        settings_data = get_settings(db)

        if request.method == "POST":
            settings_data = read_settings_form(request.form)
            error = validate_settings(settings_data)

            if error is None:
                db.execute(
                    """
                    UPDATE settings
                    SET daily_goal_minutes = ?,
                        weekly_goal_minutes = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = 1
                    """,
                    (
                        settings_data["daily_goal_minutes"],
                        settings_data["weekly_goal_minutes"],
                    ),
                )
                db.commit()
                flash("学习目标已更新。", "success")
                return redirect(url_for("settings_page"))

            flash(error, "error")

        return render_template("settings.html", settings=settings_data)

    @app.get("/health")
    def health():
        return {"status": "ok"}


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)
