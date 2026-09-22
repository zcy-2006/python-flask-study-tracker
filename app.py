import os
import sqlite3
from datetime import date, datetime

from flask import (
    Flask,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)


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


def get_record_or_404(record_id):
    record = get_db().execute(
        "SELECT * FROM records WHERE id = ?", (record_id,)
    ).fetchone()
    if record is None:
        abort(404)
    return record


def register_routes(app):
    @app.get("/")
    def index():
        selected_date = request.args.get("date", "").strip()
        if selected_date and not is_valid_date(selected_date):
            selected_date = ""
            flash("筛选日期格式不正确，已显示全部记录。", "warning")

        where_clause = ""
        params = []
        if selected_date:
            where_clause = " WHERE study_date = ?"
            params.append(selected_date)

        db = get_db()
        records = db.execute(
            "SELECT * FROM records"
            + where_clause
            + " ORDER BY study_date DESC, id DESC",
            params,
        ).fetchall()

        summary = db.execute(
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

        return render_template(
            "index.html",
            records=records,
            summary=summary,
            selected_date=selected_date,
            today=date.today().isoformat(),
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
        return redirect(url_for("index"))

    @app.post("/records/<int:record_id>/delete")
    def delete_record(record_id):
        get_record_or_404(record_id)
        db = get_db()
        db.execute("DELETE FROM records WHERE id = ?", (record_id,))
        db.commit()
        flash("学习记录已删除。", "success")
        return redirect(url_for("index"))

    @app.get("/health")
    def health():
        return {"status": "ok"}


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)
