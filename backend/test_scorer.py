import unittest
from unittest.mock import AsyncMock, patch

from scorer import (
    aqi_category,
    build_live_report,
    calculate_scores,
    current_values,
    grade_from_score,
    generate_gemma_analysis,
    resolve_preferences,
)


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

    def test_children_and_elders_priorities_combine_and_shift_healthcare_mix(self):
        children = resolve_preferences(["children"])
        elders = resolve_preferences(["elders"])
        combined = resolve_preferences(["children", "elders"])

        self.assertEqual(combined["priority_ids"], ["children", "elders"])
        self.assertAlmostEqual(combined["school_share"], 0.44)
        self.assertAlmostEqual(combined["healthcare_share"], 0.56)
        self.assertAlmostEqual(sum(combined["pillar_weights"].values()), 1.0)

        locality = {"base_safety_score": 80, "base_water_score": 70, "power_outage_hrs_week": 2}
        air = {"values": {"us_aqi": None}}
        amenities = {"status": "live", "schools_count": 7, "hospitals_count": 1, "transit_count": 2}
        children_pillars, _ = calculate_scores(locality, air, amenities, priorities=["children"])
        elders_pillars, _ = calculate_scores(locality, air, amenities, priorities=["elders"])
        combined_pillars, _ = calculate_scores(locality, air, amenities, priorities=["children", "elders"])
        self.assertGreater(children_pillars["schools_and_healthcare"], combined_pillars["schools_and_healthcare"])
        self.assertGreater(combined_pillars["schools_and_healthcare"], elders_pillars["schools_and_healthcare"])


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
            report = await build_live_report(locality, "family", config, priorities=["children", "elders"])
        self.assertEqual(report["locality_id"], "test_locality")
        self.assertIn("gemma_audit", report)
        self.assertEqual(report["selected_priorities"], ["children", "elders"])
        self.assertAlmostEqual(report["priority_scoring"]["healthcare_share"], 0.56)
        self.assertEqual(report["data_quality"]["status"], "live")
        self.assertEqual(report["live_metrics"]["news_articles_analyzed"], 1)
        self.assertIn("air_and_environment", report["pillar_scores"])
        self.assertEqual(report["gemma_audit"]["model"], "rule_based")
        self.assertTrue(report["gemma_audit"]["priority_fit"])
        self.assertTrue(report["gemma_audit"]["check_before_deciding"])
        self.assertLessEqual(len(report["gemma_audit"]["priority_fit"].split()), 20)
        self.assertLessEqual(len(report["gemma_audit"]["check_before_deciding"].split()), 20)

    async def test_gemma_prompt_includes_selected_priorities(self):
        import json

        class MockResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {
                    "response": json.dumps({
                        "buyer_verdict": "Check both school and healthcare access.",
                        "executive_summary": "The analysis reflects the selected household priorities.",
                        "priority_fit": "Nearby maps show schools and healthcare sites for your household.",
                        "check_before_deciding": "Map counts do not show quality or travel time.",
                        "key_strengths": ["Priority-aware analysis"],
                        "red_flags": ["Confirm local facility details"],
                        "infrastructure_outlook": "The available data does not verify future projects.",
                    })
                }

        class MockClient:
            def __init__(self):
                self.request = None

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, url, json):
                self.request = {"url": url, "json": json}
                return MockResponse()

        locality = {"name": "Test Locality", "avg_price_sqft": 20000}
        news = {"articles": [{"title": "Local civic notice"}]}
        fallback = {
            "model": "rule_based",
            "buyer_verdict": "Fallback",
            "executive_summary": "Fallback summary",
            "priority_fit": "Fallback priority note.",
            "check_before_deciding": "Fallback verification note.",
            "key_strengths": ["Fallback strength"],
            "red_flags": ["Fallback flag"],
            "infrastructure_outlook": "Fallback outlook",
        }
        client = MockClient()
        preferences = resolve_preferences(["children", "elders"])
        with patch("scorer.httpx.AsyncClient", return_value=client):
            result = await generate_gemma_analysis(
                locality,
                None,
                75,
                {"schools_and_healthcare": 75},
                {"schools_count": 4, "hospitals_count": 2},
                news,
                fallback,
                {"ollama_model": "gemma4:12b", "ollama_url": "http://localhost:11434"},
                preferences,
            )

        prompt = client.request["json"]["prompt"]
        self.assertIn("Children at home", prompt)
        self.assertIn("Elders / regular medical needs", prompt)
        self.assertIn("do not recalculate", prompt.lower())
        self.assertIn("at most 20 words", prompt)
        self.assertEqual(result["priority_fit"], "Nearby maps show schools and healthcare sites for your household.")
        self.assertEqual(result["check_before_deciding"], "Map counts do not show quality or travel time.")
        self.assertEqual(result["model"], "ollama:gemma4:12b")


if __name__ == "__main__":
    unittest.main()
