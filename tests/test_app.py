import os
import sqlite3
import tempfile
import unittest

from app import create_app


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

    def create_record(self, title="学习 Flask 路由"):
        return self.client.post(
            "/records/new",
            data={
                "title": title,
                "subject": "Python Web",
                "duration_minutes": "60",
                "study_date": "2026-09-22",
                "notes": "完成第一个页面",
                "completed": "1",
            },
        )

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

        record = self.get_record()
        self.assertEqual(record["completed"], 1)

    def test_create_record_requires_title(self):
        response = self.client.post(
            "/records/new",
            data={
                "title": "",
                "subject": "",
                "duration_minutes": "30",
                "study_date": "2026-09-22",
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


if __name__ == "__main__":
    unittest.main()
