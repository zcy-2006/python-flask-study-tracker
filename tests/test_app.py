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
                "DATABASE": self.database_path,
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

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

    def test_health(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "ok"})


if __name__ == "__main__":
    unittest.main()
