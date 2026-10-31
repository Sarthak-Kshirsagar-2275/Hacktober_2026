import unittest
from unittest.mock import AsyncMock, patch

from scorer import (
    aqi_category,
    build_counterfactual_fallback,
    build_locality_comparison,
    build_rule_based_audit,
    build_live_report,
    calculate_scores,
    current_values,
    fetch_air_quality,
    fetch_amenities,
    fetch_news,
    grade_from_score,
    generate_gemma_analysis,
    resolve_preferences,
    _clean_user_text,
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

    def test_comparison_ranks_priority_fit_and_value_separately(self):
        localities = [
            {"id": "dwarka", "name": "Dwarka Expressway (Sector 104)", "avg_price_sqft": 13800, "base_safety_score": 74, "base_water_score": 65, "power_outage_hrs_week": 4.5},
            {"id": "palam", "name": "Palam Vihar (Sector 23)", "avg_price_sqft": 15200, "base_safety_score": 80, "base_water_score": 75, "power_outage_hrs_week": 2.5},
        ]
        unavailable = {
            "air": {"status": "unavailable", "values": {"us_aqi": None}},
            "amenities": {"status": "unavailable", "schools_count": None, "hospitals_count": None, "transit_count": None},
        }
        preferences = resolve_preferences(["elders", "remote_work"])
        comparison = build_locality_comparison(
            localities, "dwarka", {item["id"]: unavailable for item in localities}, preferences
        )

        self.assertEqual(comparison["selected_rank"], 2)
        self.assertEqual(comparison["best_match"]["locality_id"], "palam")
        self.assertEqual(comparison["best_value"]["locality_id"], "dwarka")
        self.assertEqual(comparison["tradeoff"]["price_delta_sqft"], 1400)
        self.assertEqual(comparison["tradeoff"]["power_hours_delta_week"], -2.0)
        self.assertEqual(comparison["tradeoff"]["pillar_deltas"]["water_and_drainage"], 10)
        fallback = build_counterfactual_fallback(comparison, preferences)
        self.assertIn("stronger power reliability", fallback)
        without_official_names = fallback.replace("Palam Vihar (Sector 23)", "").replace(
            "Dwarka Expressway (Sector 104)", ""
        )
        self.assertNotRegex(without_official_names, r"\d")


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
        self.assertFalse(report["gemma_audit"]["used_gemma"])
        for prefix in ("overall", "telemetry", "pillar"):
            numbers = report["gemma_audit"][f"{prefix}_numbers"]
            insight = report["gemma_audit"][f"{prefix}_insight"]
            self.assertLessEqual(len(numbers.split()) + len(insight.split()), 50)

    async def test_comparison_fetches_each_area_and_news_once(self):
        locality = {"id": "dwarka", "name": "Dwarka Expressway", "lat": 28.4789, "lon": 76.9932, "avg_price_sqft": 13800, "base_safety_score": 74, "base_water_score": 65, "power_outage_hrs_week": 4.5}
        palam = {"id": "palam", "name": "Palam Vihar", "lat": 28.5085, "lon": 77.0322, "avg_price_sqft": 15200, "base_safety_score": 80, "base_water_score": 75, "power_outage_hrs_week": 2.5}
        air = {"status": "unavailable", "values": {"us_aqi": None, "pm2_5": None, "pm10": None}}
        amenities = {"status": "unavailable", "schools_count": None, "hospitals_count": None, "transit_count": None}
        news = {"status": "unavailable", "articles": [], "articles_count": 0}
        with patch("scorer.fetch_air_quality", new_callable=AsyncMock, return_value=air) as air_fetch, patch(
            "scorer.fetch_amenities", new_callable=AsyncMock, return_value=amenities
        ) as places_fetch, patch("scorer.fetch_news", new_callable=AsyncMock, return_value=news) as news_fetch:
            report = await build_live_report(
                locality,
                None,
                {"request_timeout_seconds": "1", "ollama_model": ""},
                priorities=["elders", "remote_work"],
                comparison_localities=[locality, palam],
            )

        self.assertEqual(air_fetch.await_count, 2)
        self.assertEqual(places_fetch.await_count, 2)
        self.assertEqual(news_fetch.await_count, 1)
        self.assertEqual(report["comparison"]["best_match"]["locality_id"], "palam")
        self.assertIn("counterfactual_insight", report["gemma_audit"])

    def test_unconfirmed_nearby_counts_use_plain_language(self):
        locality = {
            "name": "Test Locality, Gurugram",
            "avg_price_sqft": 20000,
            "base_safety_score": 80,
            "base_water_score": 75,
            "power_outage_hrs_week": 2,
        }
        air = {"status": "unavailable", "values": {"us_aqi": None, "pm2_5": None, "pm10": None}}
        amenities = {
            "status": "unavailable",
            "schools_count": None,
            "hospitals_count": None,
            "transit_count": None,
        }
        news = {"status": "unavailable", "articles": [], "articles_count": 0}
        preferences = resolve_preferences(["children"])
        pillars, score = calculate_scores(locality, air, amenities, preferences=preferences)
        audit = build_rule_based_audit(locality, None, score, air, amenities, news, pillars, preferences)
        all_text = " ".join(
            [audit["executive_summary"], audit["telemetry_numbers"], *audit["red_flags"]]
        )
        self.assertNotIn("None", all_text)
        self.assertNotIn("OpenStreetMap", all_text)
        self.assertNotIn("could not gather", all_text.lower())
        self.assertIn("not confirmed right now", audit["executive_summary"])

    def test_gemma_language_sanitizer_uses_safe_fallback(self):
        fallback = "Nearby details are not confirmed right now."
        unsafe = "The API failed to gather None school counts."
        self.assertEqual(_clean_user_text(unsafe, fallback, max_words=25), fallback)
        self.assertEqual(
            _clean_user_text("There are three nearby schools.", fallback, max_words=25, reject_numbers=True),
            fallback,
        )
        self.assertEqual(_clean_user_text("The service is unavailable.", fallback, max_words=25), fallback)

    async def test_live_source_errors_are_generic(self):
        class BrokenClient:
            async def get(self, *args, **kwargs):
                raise RuntimeError("SECRET provider endpoint traceback")

            async def post(self, *args, **kwargs):
                raise RuntimeError("SECRET provider endpoint traceback")

        client = BrokenClient()
        locality = {"lat": 28.45, "lon": 77.05}
        config = {
            "air_quality_api_url": "https://example.test/air",
            "overpass_api_url": "https://example.test/places",
            "news_rss_url": "https://example.test/news",
        }
        results = [
            await fetch_air_quality(client, locality, config),
            await fetch_amenities(client, locality, config),
            await fetch_news(client, config),
        ]
        expected_messages = [
            "A current air reading is not available right now.",
            "Nearby place information is not available right now.",
            "Recent local news is not available right now.",
        ]
        for result, message in zip(results, expected_messages):
            self.assertEqual(result["error"], message)
            self.assertNotIn("SECRET", str(result))

    async def test_gemma_prompt_includes_selected_priorities(self):
        import json

        class MockResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {
                    "response": json.dumps({
                        "overall_numbers": "The area scored 75/100; the average listed price is ₹20,000 per sq.ft.",
                        "overall_insight": "Compare the listed average with your budget and the needs you selected.",
                        "counterfactual_insight": "Palam Vihar offers stronger power reliability and water ratings; check local conditions before switching.",
                        "telemetry_numbers": "AQI 80 (Moderate); PM2.5 20; PM10 30; estimated power interruptions are 2 hours weekly.",
                        "telemetry_insight": "Air readings can change, so check current conditions before deciding.",
                        "pillar_numbers": "Schools and healthcare 75; safety 80; power 70; transit 65; water 75; air 72.",
                        "pillar_insight": "Your selected needs give schools and healthcare more influence on the total.",
                        "buyer_verdict": "Check both school and healthcare access.",
                        "executive_summary": "The analysis reflects the selected household priorities.",
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
            "model": "Report insight",
            "used_gemma": False,
            "buyer_verdict": "Fallback",
            "executive_summary": "Fallback summary",
            "overall_numbers": "Fallback numbers.",
            "overall_insight": "Fallback insight.",
            "telemetry_numbers": "Fallback reading.",
            "telemetry_insight": "Fallback reading insight.",
            "pillar_numbers": "Fallback ratings.",
            "pillar_insight": "Fallback rating insight.",
            "key_strengths": ["Fallback strength"],
            "red_flags": ["Fallback flag"],
            "infrastructure_outlook": "Fallback outlook",
            "counterfactual_insight": "Fallback comparison insight.",
        }
        client = MockClient()
        preferences = resolve_preferences(["children", "elders"])
        comparison_localities = [
            {"id": "dwarka", "name": "Dwarka Expressway (Sector 104)", "avg_price_sqft": 13800, "base_safety_score": 74, "base_water_score": 65, "power_outage_hrs_week": 4.5},
            {"id": "palam", "name": "Palam Vihar (Sector 23)", "avg_price_sqft": 15200, "base_safety_score": 80, "base_water_score": 75, "power_outage_hrs_week": 2.5},
        ]
        comparison_evidence = {
            item["id"]: {
                "air": {"status": "unavailable", "values": {"us_aqi": None}},
                "amenities": {"status": "unavailable", "schools_count": None, "hospitals_count": None, "transit_count": None},
            }
            for item in comparison_localities
        }
        comparison = build_locality_comparison(
            comparison_localities, "dwarka", comparison_evidence, preferences
        )
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
                comparison,
            )

        prompt = client.request["json"]["prompt"]
        self.assertIn("Children at home", prompt)
        self.assertIn("Elders / regular medical needs", prompt)
        self.assertIn("do not repeat or change them", prompt.lower())
        self.assertIn("25 words", prompt)
        self.assertIn("comparison_matrix", prompt)
        self.assertIn("Palam Vihar (Sector 23)", prompt)
        self.assertTrue(result["used_gemma"])
        self.assertEqual(result["model"], "Gemma")
        self.assertEqual(result["overall_numbers"], fallback["overall_numbers"])
        self.assertIn("Palam Vihar", result["counterfactual_insight"])
        self.assertFalse(any(character.isdigit() for character in result["counterfactual_insight"]))
        for prefix in ("overall", "telemetry", "pillar"):
            self.assertLessEqual(
                len(result[f"{prefix}_numbers"].split()) + len(result[f"{prefix}_insight"].split()),
                50,
            )
            self.assertFalse(any(character.isdigit() for character in result[f"{prefix}_insight"]))


if __name__ == "__main__":
    unittest.main()
