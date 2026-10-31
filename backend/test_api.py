import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import main


class ReportPriorityCacheTests(unittest.TestCase):
    def test_priority_combinations_are_cached_separately(self):
        first_report = {"generated_at": "children-and-elders", "standardized_quality_score": 74}
        second_report = {"generated_at": "children-only", "standardized_quality_score": 70}
        with tempfile.TemporaryDirectory() as temp_dir:
            test_db = Path(temp_dir) / "localeiq_test.db"
            with patch.object(main, "DB_PATH", test_db), patch(
                "main.build_live_report",
                new_callable=AsyncMock,
                side_effect=[first_report, second_report],
            ) as report_builder:
                with TestClient(main.app) as client:
                    invalid = client.get(
                        "/api/report?locality_id=dlf_phase_4&priorities=not-a-priority"
                    )
                    self.assertEqual(invalid.status_code, 400)
                    self.assertEqual(report_builder.await_count, 0)

                    both = client.get(
                        "/api/report?locality_id=dlf_phase_4&priorities=children&priorities=elders"
                    )
                    same_both_again = client.get(
                        "/api/report?locality_id=dlf_phase_4&priorities=elders&priorities=children"
                    )
                    children_only = client.get(
                        "/api/report?locality_id=dlf_phase_4&priorities=children"
                    )

            self.assertEqual(both.status_code, 200)
            self.assertEqual(same_both_again.status_code, 200)
            self.assertEqual(children_only.status_code, 200)
            self.assertEqual(both.json()["generated_at"], "children-and-elders")
            self.assertEqual(same_both_again.json()["generated_at"], "children-and-elders")
            self.assertEqual(children_only.json()["generated_at"], "children-only")
            self.assertEqual(report_builder.await_count, 2)
            self.assertEqual(report_builder.await_args_list[0].kwargs["priorities"], ["children", "elders"])
            self.assertEqual(report_builder.await_args_list[1].kwargs["priorities"], ["children"])

            with sqlite3.connect(test_db) as conn:
                cache_count = conn.execute("SELECT COUNT(*) FROM report_cache").fetchone()[0]
            self.assertEqual(cache_count, 2)


if __name__ == "__main__":
    unittest.main()
