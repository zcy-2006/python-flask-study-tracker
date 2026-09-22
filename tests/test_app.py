import os
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta

from app import calculate_streak, create_app


class StudyTrackerTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = os.path.join(self.temp_dir.name, "test.sqlite")
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-secret",
                "WTF_CSRF_ENABLED": False,
                "DATABASE": self.database_path,
            }
        )
        self.client = self.app.test_client()
        response = self.register_user()
        self.assertEqual(response.status_code, 302)

    def tearDown(self):
        self.temp_dir.cleanup()

    def register_user(
        self,
        username="tester",
        password="test-password",
        follow_redirects=False,
    ):
        return self.client.post(
            "/register",
            data={
                "username": username,
                "password": password,
                "confirm_password": password,
            },
            follow_redirects=follow_redirects,
        )

    def create_record(self, **overrides):
        data = {
            "title": "学习 Flask 路由",
            "subject": "Python Web",
            "duration_minutes": "60",
            "study_date": date.today().isoformat(),
            "notes": "完成第一个页面",
            "completed": "1",
        }
        data.update(overrides)
        return self.client.post("/records/new", data=data)

    def get_record(self, record_id=1):
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        record = connection.execute(
            "SELECT * FROM records WHERE id = ?", (record_id,)
        ).fetchone()
        connection.close()
        return record

    def test_empty_home_page(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("还没有学习记录", response.get_data(as_text=True))

    def test_create_record(self):
        response = self.create_record()
        self.assertEqual(response.status_code, 302)

        page = self.client.get("/").get_data(as_text=True)
        self.assertIn("学习 Flask 路由", page)
        self.assertIn("60 分钟", page)
        self.assertIn("100%", page)

        record = self.get_record()
        self.assertEqual(record["completed"], 1)
        self.assertEqual(record["user_id"], 1)

    def test_create_record_requires_title(self):
        response = self.client.post(
            "/records/new",
            data={
                "title": "",
                "subject": "",
                "duration_minutes": "30",
                "study_date": date.today().isoformat(),
                "notes": "",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("请填写学习内容", response.get_data(as_text=True))

    def test_edit_record(self):
        self.create_record()
        response = self.client.post(
            "/records/1/edit",
            data={
                "title": "学习 Flask 模板",
                "subject": "Python Web",
                "duration_minutes": "90",
                "study_date": "2026-09-23",
                "notes": "更新后的笔记",
                "completed": "1",
            },
        )
        self.assertEqual(response.status_code, 302)

        record = self.get_record()
        self.assertEqual(record["title"], "学习 Flask 模板")
        self.assertEqual(record["duration_minutes"], 90)
        self.assertEqual(record["study_date"], "2026-09-23")

    def test_toggle_record(self):
        self.create_record()
        response = self.client.post("/records/1/toggle")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.get_record()["completed"], 0)

    def test_delete_record(self):
        self.create_record()
        response = self.client.post("/records/1/delete")
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(self.get_record())

    def test_search_and_subject_filter(self):
        self.create_record(title="学习 Flask 路由", subject="Python Web")
        self.create_record(title="学习 SQL 查询", subject="Database")

        search_page = self.client.get(
            "/", query_string={"q": "Flask"}
        ).get_data(as_text=True)
        self.assertIn("学习 Flask 路由", search_page)
        self.assertNotIn("学习 SQL 查询", search_page)

        subject_page = self.client.get(
            "/", query_string={"subject": "Database"}
        ).get_data(as_text=True)
        self.assertIn("学习 SQL 查询", subject_page)
        self.assertNotIn("学习 Flask 路由", subject_page)

    def test_export_csv(self):
        self.create_record(title="导出测试记录")
        response = self.client.get("/export.csv")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data.startswith(b"\xef\xbb\xbf"))
        self.assertIn("text/csv", response.content_type)
        self.assertIn(
            "导出测试记录",
            response.data.decode("utf-8-sig"),
        )

    def test_calculate_streak(self):
        today = date(2026, 9, 22)
        study_dates = [
            today.isoformat(),
            (today - timedelta(days=1)).isoformat(),
            (today - timedelta(days=2)).isoformat(),
            (today - timedelta(days=4)).isoformat(),
        ]
        self.assertEqual(calculate_streak(study_dates, today), 3)

    def test_settings_page_defaults(self):
        response = self.client.get("/settings")
        page = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("每日学习目标", page)
        self.assertIn('value="60"', page)
        self.assertIn('value="300"', page)

    def test_update_settings(self):
        response = self.client.post(
            "/settings",
            data={
                "daily_goal_minutes": "90",
                "weekly_goal_minutes": "450",
            },
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("学习目标已更新", response.get_data(as_text=True))

    def test_invalid_settings(self):
        response = self.client.post(
            "/settings",
            data={
                "daily_goal_minutes": "0",
                "weekly_goal_minutes": "100",
            },
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("每日目标必须在 1 到 1440 分钟之间", response.get_data(as_text=True))

    def test_dashboard_shows_goals_and_trend(self):
        self.create_record()
        page = self.client.get("/").get_data(as_text=True)

        self.assertIn("今日目标", page)
        self.assertIn("本周目标", page)
        self.assertIn("近 7 天趋势", page)

    def test_anonymous_user_is_redirected_to_login(self):
        self.client.post("/logout")
        response = self.client.get("/")

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_login_and_logout(self):
        self.client.post("/logout")
        response = self.client.post(
            "/login",
            data={"username": "tester", "password": "test-password"},
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("登录成功", response.get_data(as_text=True))

        response = self.client.post("/logout", follow_redirects=True)
        self.assertIn("你已退出登录", response.get_data(as_text=True))

    def test_user_data_is_isolated(self):
        self.create_record(title="第一个用户的记录")
        self.client.post("/logout")
        self.register_user(username="second-user")

        page = self.client.get("/").get_data(as_text=True)
        self.assertNotIn("第一个用户的记录", page)
        self.assertIn("还没有学习记录", page)

    def test_duplicate_username_is_rejected(self):
        self.client.post("/logout")
        response = self.register_user(follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("该用户名已经被注册", response.get_data(as_text=True))

    def test_heatmap_and_month_summary(self):
        self.create_record(duration_minutes="120")
        page = self.client.get("/").get_data(as_text=True)

        self.assertIn("学习热力图", page)
        self.assertIn("本月学习", page)
        self.assertIn("活跃天数", page)
        self.assertIn("日均时长", page)
        self.assertIn("最佳一天", page)
        self.assertEqual(page.count('class="heatmap-week"'), 8)
        self.assertIn("level-4", page)

    def test_account_page(self):
        response = self.client.get("/account")
        page = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("账户管理", page)
        self.assertIn("tester", page)

    def test_change_password(self):
        response = self.client.post(
            "/account",
            data={
                "current_password": "test-password",
                "new_password": "new-test-password",
                "confirm_password": "new-test-password",
            },
            follow_redirects=True,
        )
        self.assertIn("密码已更新", response.get_data(as_text=True))

        self.client.post("/logout")
        old_login = self.client.post(
            "/login",
            data={"username": "tester", "password": "test-password"},
            follow_redirects=True,
        )
        self.assertIn("用户名或密码不正确", old_login.get_data(as_text=True))

        new_login = self.client.post(
            "/login",
            data={"username": "tester", "password": "new-test-password"},
            follow_redirects=True,
        )
        self.assertIn("登录成功", new_login.get_data(as_text=True))

    def test_change_password_rejects_wrong_current_password(self):
        response = self.client.post(
            "/account",
            data={
                "current_password": "wrong-password",
                "new_password": "new-test-password",
                "confirm_password": "new-test-password",
            },
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("当前密码不正确", response.get_data(as_text=True))

    def test_security_headers(self):
        response = self.client.get("/health")

        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertIn("strict-origin", response.headers["Referrer-Policy"])

    def test_health(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "ok"})


if __name__ == "__main__":
    unittest.main()
