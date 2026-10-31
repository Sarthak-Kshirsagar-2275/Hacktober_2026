import sqlite3
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import main


class ReportFreshnessTests(unittest.TestCase):
    def test_each_report_request_generates_a_fresh_result(self):
        first_report = {"generated_at": "first", "standardized_quality_score": 70}
        second_report = {"generated_at": "second", "standardized_quality_score": 75}
        with patch(
            "main.build_live_report",
            new_callable=AsyncMock,
            side_effect=[first_report, second_report],
        ) as report_builder:
            with TestClient(main.app) as client:
                first = client.get("/api/report?locality_id=dlf_phase_4&persona=family")
                second = client.get("/api/report?locality_id=dlf_phase_4&persona=family")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["generated_at"], "first")
        self.assertEqual(second.json()["generated_at"], "second")
        self.assertEqual(first.json()["cache"], {"enabled": False, "hit": False})
        self.assertEqual(second.json()["cache"], {"enabled": False, "hit": False})
        self.assertEqual(report_builder.await_count, 2)
        with sqlite3.connect(main.DB_PATH) as conn:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertNotIn("report_cache", tables)


if __name__ == "__main__":
    unittest.main()
