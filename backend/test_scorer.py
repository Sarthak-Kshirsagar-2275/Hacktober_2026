import unittest
from unittest.mock import AsyncMock, patch

from scorer import aqi_category, build_live_report, calculate_scores, current_values, grade_from_score


class ScorerTests(unittest.TestCase):
    def test_aqi_categories(self):
        self.assertEqual(aqi_category(25), "Good")
        self.assertEqual(aqi_category(75), "Moderate")
        self.assertEqual(aqi_category(125), "Unhealthy for Sensitive Groups")
        self.assertEqual(aqi_category(175), "Unhealthy")
        self.assertEqual(aqi_category(None), "Unavailable")

    def test_grade_boundaries(self):
        self.assertEqual(grade_from_score(90), "A+")
        self.assertEqual(grade_from_score(84.9), "A-")
        self.assertEqual(grade_from_score(74.9), "B")
        self.assertEqual(grade_from_score(54), "D")

    def test_current_values_prefers_current_conditions(self):
        payload = {
            "current": {"us_aqi": 82, "pm2_5": 11.2, "pm10": 19.8},
            "hourly": {"time": ["2026-10-31T10:00"], "us_aqi": [30]},
        }
        self.assertEqual(current_values(payload), {"us_aqi": 82.0, "pm2_5": 11.2, "pm10": 19.8})

    def test_current_values_falls_back_to_latest_hour(self):
        payload = {
            "hourly": {
                "time": ["2026-10-31T10:00", "2026-10-31T11:00"],
                "us_aqi": [60, 80],
                "pm2_5": [12.0, 13.0],
                "pm10": [20.0, 21.0],
            }
        }
        self.assertEqual(current_values(payload), {"us_aqi": 80.0, "pm2_5": 13.0, "pm10": 21.0})

    def test_unavailable_sources_use_neutral_pillars(self):
        locality = {
            "base_safety_score": 80,
            "base_water_score": 70,
            "power_outage_hrs_week": 2,
        }
        air = {"status": "unavailable", "values": {"us_aqi": None}}
        amenities = {
            "status": "unavailable",
            "schools_count": None,
            "hospitals_count": None,
            "transit_count": None,
        }
        pillars, score = calculate_scores(locality, air, amenities, "family")
        self.assertEqual(pillars["schools_and_healthcare"], 50)
        self.assertEqual(pillars["future_infrastructure"], 50)
        self.assertEqual(pillars["air_and_environment"], 50)
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)


class ReportTests(unittest.IsolatedAsyncioTestCase):
    async def test_report_contract_with_mocked_free_sources(self):
        locality = {
            "id": "test_locality",
            "name": "Test Locality, Gurugram",
            "lat": 28.45,
            "lon": 77.05,
            "avg_price_sqft": 20000,
            "base_safety_score": 80,
            "base_water_score": 75,
            "power_outage_hrs_week": 2,
        }
        air = {
            "status": "live",
            "provider": "Open-Meteo Air Quality",
            "retrieved_at": "2026-10-31T00:00:00Z",
            "values": {"us_aqi": 80.0, "pm2_5": 20.0, "pm10": 30.0},
        }
        amenities = {
            "status": "live",
            "provider": "OpenStreetMap Overpass",
            "retrieved_at": "2026-10-31T00:00:00Z",
            "schools_count": 3,
            "hospitals_count": 2,
            "transit_count": 4,
        }
        news = {
            "status": "live",
            "provider": "Google News RSS",
            "retrieved_at": "2026-10-31T00:00:00Z",
            "articles": [{"title": "Gurugram civic update", "url": "https://example.test", "published_at": ""}],
            "articles_count": 1,
        }
        config = {"request_timeout_seconds": "1", "ollama_model": ""}
        with patch("scorer.fetch_air_quality", new_callable=AsyncMock, return_value=air), patch(
            "scorer.fetch_amenities", new_callable=AsyncMock, return_value=amenities
        ), patch("scorer.fetch_news", new_callable=AsyncMock, return_value=news):
            report = await build_live_report(locality, "family", config)
        self.assertEqual(report["locality_id"], "test_locality")
        self.assertIn("gemma_audit", report)
        self.assertEqual(report["data_quality"]["status"], "live")
        self.assertEqual(report["live_metrics"]["news_articles_analyzed"], 1)
        self.assertIn("air_and_environment", report["pillar_scores"])
        self.assertEqual(report["gemma_audit"]["model"], "rule_based")


if __name__ == "__main__":
    unittest.main()
