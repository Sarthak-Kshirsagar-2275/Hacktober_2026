import asyncio
import json
import math
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx

PERSONA_WEIGHTS = {
    "family": {
        "schools_and_healthcare": 0.24,
        "safety_and_security": 0.20,
        "power_reliability": 0.13,
        "future_infrastructure": 0.11,
        "water_and_drainage": 0.17,
        "air_and_environment": 0.15,
    },
    "commuter": {
        "schools_and_healthcare": 0.08,
        "safety_and_security": 0.13,
        "power_reliability": 0.12,
        "future_infrastructure": 0.27,
        "water_and_drainage": 0.12,
        "air_and_environment": 0.28,
    },
    "investor": {
        "schools_and_healthcare": 0.12,
        "safety_and_security": 0.12,
        "power_reliability": 0.12,
        "future_infrastructure": 0.29,
        "water_and_drainage": 0.15,
        "air_and_environment": 0.20,
    },
}

BALANCED_WEIGHTS = {
    "schools_and_healthcare": 1 / 6,
    "safety_and_security": 1 / 6,
    "power_reliability": 1 / 6,
    "future_infrastructure": 1 / 6,
    "water_and_drainage": 1 / 6,
    "air_and_environment": 1 / 6,
}

PRIORITY_PROFILES = {
    "children": {
        "label": "Children at home",
        "pillar_weights": {"schools_and_healthcare": 0.32, "safety_and_security": 0.18, "power_reliability": 0.12, "future_infrastructure": 0.10, "water_and_drainage": 0.14, "air_and_environment": 0.14},
        "school_share": 0.68,
        "focus": "Emphasize nearby schools while still considering mapped healthcare facilities, safety, and air quality.",
    },
    "elders": {
        "label": "Elders / regular medical needs",
        "pillar_weights": {"schools_and_healthcare": 0.34, "safety_and_security": 0.18, "power_reliability": 0.14, "future_infrastructure": 0.08, "water_and_drainage": 0.10, "air_and_environment": 0.16},
        "school_share": 0.20,
        "focus": "Prioritize mapped healthcare facilities over school counts within the combined schools-and-healthcare pillar.",
    },
    "commuter": {
        "label": "Daily commuter / transit-first",
        "pillar_weights": {"schools_and_healthcare": 0.10, "safety_and_security": 0.12, "power_reliability": 0.12, "future_infrastructure": 0.32, "water_and_drainage": 0.10, "air_and_environment": 0.24},
        "school_share": 0.50,
        "focus": "Emphasize mapped transit features and air-quality readings; do not infer commute times or routes.",
    },
    "air_sensitive": {
        "label": "Air-quality sensitive household",
        "pillar_weights": {"schools_and_healthcare": 0.18, "safety_and_security": 0.10, "power_reliability": 0.10, "future_infrastructure": 0.10, "water_and_drainage": 0.12, "air_and_environment": 0.40},
        "school_share": 0.50,
        "focus": "Emphasize modeled AQI and particulate readings and clearly describe their limits.",
    },
    "remote_work": {
        "label": "Work / study from home",
        "pillar_weights": {"schools_and_healthcare": 0.10, "safety_and_security": 0.12, "power_reliability": 0.34, "future_infrastructure": 0.10, "water_and_drainage": 0.20, "air_and_environment": 0.14},
        "school_share": 0.50,
        "focus": "Emphasize stored power-outage and water baselines; do not present them as live measurements.",
    },
    "water_resilience": {
        "label": "Water / monsoon resilience",
        "pillar_weights": {"schools_and_healthcare": 0.10, "safety_and_security": 0.10, "power_reliability": 0.12, "future_infrastructure": 0.10, "water_and_drainage": 0.40, "air_and_environment": 0.18},
        "school_share": 0.50,
        "focus": "Emphasize the stored water-and-drainage baseline and flag that this app has no live waterlogging feed.",
    },
    "safety_first": {
        "label": "Safety-focused household",
        "pillar_weights": {"schools_and_healthcare": 0.10, "safety_and_security": 0.38, "power_reliability": 0.12, "future_infrastructure": 0.15, "water_and_drainage": 0.12, "air_and_environment": 0.13},
        "school_share": 0.50,
        "focus": "Emphasize the stored safety baseline and state that it is not a live crime or incident feed.",
    },
    "infra_long_term": {
        "label": "Long-term infrastructure interest",
        "pillar_weights": {"schools_and_healthcare": 0.10, "safety_and_security": 0.12, "power_reliability": 0.12, "future_infrastructure": 0.40, "water_and_drainage": 0.10, "air_and_environment": 0.16},
        "school_share": 0.50,
        "focus": "Use mapped nearby transit as the available infrastructure proxy; do not claim proposed projects are approved or funded.",
    },
    "price_context": {
        "label": "Compare price context",
        "pillar_weights": None,
        "school_share": None,
        "focus": "Highlight the supplied average price per square foot as context only; there is no budget input or affordability score.",
    },
}


def resolve_preferences(priorities=None, persona=None):
    selected = list(dict.fromkeys(priorities or []))
    unknown = sorted(set(selected) - set(PRIORITY_PROFILES))
    if unknown:
        raise ValueError(f"Unknown priorities: {', '.join(unknown)}")

    profiles = [PRIORITY_PROFILES[key] for key in selected]
    weighted_profiles = [profile["pillar_weights"] for profile in profiles if profile["pillar_weights"]]
    if weighted_profiles:
        weights = {
            pillar: sum(profile[pillar] for profile in weighted_profiles) / len(weighted_profiles)
            for pillar in BALANCED_WEIGHTS
        }
    elif not selected and persona in PERSONA_WEIGHTS:
        weights = PERSONA_WEIGHTS[persona]
    else:
        weights = BALANCED_WEIGHTS

    mix_profiles = [profile for profile in profiles if profile["school_share"] is not None]
    school_share = (
        sum(profile["school_share"] for profile in mix_profiles) / len(mix_profiles)
        if mix_profiles
        else 0.5
    )

    return {
        "priority_ids": selected,
        "priority_labels": [profile["label"] for profile in profiles] or ["Balanced (no extra priorities selected)"],
        "focus_instructions": [profile["focus"] for profile in profiles],
        "pillar_weights": weights,
        "school_share": school_share,
        "healthcare_share": 1 - school_share,
    }


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def as_number(value):
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def aqi_category(aqi):
    if aqi is None:
        return "Unavailable"
    if aqi <= 50:
        return "Good"
    if aqi <= 100:
        return "Moderate"
    if aqi <= 150:
        return "Unhealthy for Sensitive Groups"
    if aqi <= 200:
        return "Unhealthy"
    if aqi <= 300:
        return "Very Unhealthy"
    return "Hazardous"


def grade_from_score(score):
    if score >= 90:
        return "A+"
    if score >= 85:
        return "A"
    if score >= 80:
        return "A-"
    if score >= 75:
        return "B+"
    if score >= 70:
        return "B"
    if score >= 65:
        return "B-"
    if score >= 60:
        return "C+"
    if score >= 55:
        return "C"
    return "D"


def current_values(payload):
    current = payload.get("current") or {}
    values = {key: as_number(current.get(key)) for key in ("us_aqi", "pm2_5", "pm10")}
    if all(value is not None for value in values.values()):
        return values

    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    if not times:
        return values
    for index in range(len(times) - 1, -1, -1):
        candidate = {
            key: as_number((hourly.get(key) or [])[index])
            if index < len(hourly.get(key) or [])
            else None
            for key in ("us_aqi", "pm2_5", "pm10")
        }
        if any(value is not None for value in candidate.values()):
            return candidate
    return values


async def fetch_air_quality(client, locality, config):
    url = config["air_quality_api_url"]
    params = {
        "latitude": locality["lat"],
        "longitude": locality["lon"],
        "current": "us_aqi,pm2_5,pm10",
        "timezone": "Asia/Kolkata",
    }
    try:
        response = await client.get(url, params=params)
        response.raise_for_status()
        values = current_values(response.json())
        if all(value is None for value in values.values()):
            raise ValueError("No current air-quality values were returned")
        return {
            "status": "live",
            "provider": "Open-Meteo Air Quality",
            "retrieved_at": utc_now(),
            "values": values,
        }
    except Exception as exc:
        return {
            "status": "unavailable",
            "provider": "Open-Meteo Air Quality",
            "retrieved_at": None,
            "values": {"us_aqi": None, "pm2_5": None, "pm10": None},
            "error": f"{type(exc).__name__}: {str(exc)[:180]}",
        }


async def fetch_amenities(client, locality, config):
    lat = float(locality["lat"])
    lon = float(locality["lon"])
    query = (
        "[out:json][timeout:15];"
        "("
        f'nwr(around:2500,{lat},{lon})["amenity"~"^(school|university|college|kindergarten|hospital|clinic|doctors|bus_station|bus_stop)$"];'
        f'nwr(around:2500,{lat},{lon})["public_transport"~"^(station|stop_position|platform)$"];'
        f'nwr(around:2500,{lat},{lon})["railway"~"^(station|subway_entrance|tram_stop)$"];'
        ");out tags;"
    )
    try:
        response = await client.post(
            config["overpass_api_url"],
            content=query,
            headers={"Content-Type": "text/plain; charset=utf-8"},
        )
        response.raise_for_status()
        elements = response.json().get("elements", [])
        seen = set()
        schools = set()
        hospitals = set()
        transit = set()
        for element in elements:
            identity = (element.get("type"), element.get("id"))
            if identity in seen:
                continue
            seen.add(identity)
            tags = element.get("tags") or {}
            amenity = tags.get("amenity", "")
            if amenity in {"school", "university", "college", "kindergarten"}:
                schools.add(identity)
            if amenity in {"hospital", "clinic", "doctors"}:
                hospitals.add(identity)
            if amenity in {"bus_station", "bus_stop"}:
                transit.add(identity)
            if tags.get("public_transport") in {"station", "stop_position", "platform"}:
                transit.add(identity)
            if tags.get("railway") in {"station", "subway_entrance", "tram_stop"}:
                transit.add(identity)
        return {
            "status": "live",
            "provider": "OpenStreetMap Overpass",
            "retrieved_at": utc_now(),
            "schools_count": len(schools),
            "hospitals_count": len(hospitals),
            "transit_count": len(transit),
        }
    except Exception as exc:
        return {
            "status": "unavailable",
            "provider": "OpenStreetMap Overpass",
            "retrieved_at": None,
            "schools_count": None,
            "hospitals_count": None,
            "transit_count": None,
            "error": f"{type(exc).__name__}: {str(exc)[:180]}",
        }


async def fetch_news(client, config):
    query = "Gurugram (civic OR infrastructure OR waterlogging OR roads OR metro OR power) when:30d"
    params = {"q": query, "hl": "en-IN", "gl": "IN", "ceid": "IN:en"}
    try:
        response = await client.get(config["news_rss_url"], params=params)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        items = []
        for item in root.findall(".//item")[:30]:
            title = item.findtext("title", default="").strip()
            if not title:
                continue
            items.append(
                {
                    "title": title,
                    "url": item.findtext("link", default="").strip(),
                    "published_at": item.findtext("pubDate", default="").strip(),
                }
            )
        return {
            "status": "live",
            "provider": "Google News RSS",
            "retrieved_at": utc_now(),
            "articles": items,
            "articles_count": len(items),
        }
    except Exception as exc:
        return {
            "status": "unavailable",
            "provider": "Google News RSS",
            "retrieved_at": None,
            "articles": [],
            "articles_count": 0,
            "error": f"{type(exc).__name__}: {str(exc)[:180]}",
        }


def calculate_scores(locality, air, amenities, persona=None, priorities=None, preferences=None):
    values = air["values"]
    aqi = values.get("us_aqi")
    preferences = preferences or resolve_preferences(priorities, persona)
    if amenities["status"] == "live":
        school_score = min(100.0, 45 + 10 * min(amenities["schools_count"], 7))
        healthcare_score = min(100.0, 45 + 10 * min(amenities["hospitals_count"], 5))
        schools_score = (
            school_score * preferences["school_share"]
            + healthcare_score * preferences["healthcare_share"]
        )
        infra_score = min(100.0, 45 + 4 * min(amenities["transit_count"], 14))
    else:
        schools_score = 50.0
        infra_score = 50.0

    outage_hours = max(0.0, float(locality["power_outage_hrs_week"]))
    power_score = max(0.0, min(100.0, 100 - outage_hours * 6))
    air_score = max(0.0, min(100.0, 100 - aqi * 0.32)) if aqi is not None else 50.0
    pillars = {
        "schools_and_healthcare": round(schools_score),
        "safety_and_security": int(locality["base_safety_score"]),
        "power_reliability": round(power_score),
        "future_infrastructure": round(infra_score),
        "water_and_drainage": int(locality["base_water_score"]),
        "air_and_environment": round(air_score),
    }
    weights = preferences["pillar_weights"]
    overall = round(sum(pillars[key] * weights[key] for key in weights) / sum(weights.values()), 1)
    return pillars, overall


def _strengths_and_flags(locality, air, amenities, pillars):
    strengths = []
    red_flags = []
    if amenities["status"] == "live":
        if amenities["schools_count"] or amenities["hospitals_count"]:
            strengths.append(
                f"OpenStreetMap lists {amenities['schools_count']} schools and {amenities['hospitals_count']} healthcare facilities within 2.5 km."
            )
        else:
            red_flags.append("OpenStreetMap returned no mapped schools or healthcare facilities within 2.5 km; verify local coverage.")
        if amenities["transit_count"]:
            strengths.append(f"OpenStreetMap lists {amenities['transit_count']} nearby transit features within 2.5 km.")
        else:
            red_flags.append("OpenStreetMap returned no mapped transit features within 2.5 km; verify local coverage.")
    else:
        red_flags.append("Nearby school, healthcare, and transit counts could not be refreshed from OpenStreetMap.")

    if air["status"] == "live" and air["values"].get("us_aqi") is not None:
        aqi = round(air["values"]["us_aqi"])
        if aqi <= 100:
            strengths.append(f"Current modelled US AQI is {aqi} ({aqi_category(aqi)}).")
        else:
            red_flags.append(f"Current modelled US AQI is {aqi} ({aqi_category(aqi)}); sensitive groups may need extra precautions.")
    else:
        red_flags.append("Current air-quality values are unavailable; the air pillar uses a neutral fallback score.")

    strengths.append(f"The project's baseline safety score is {pillars['safety_and_security']}/100.")
    strengths.append(f"The project's baseline water and drainage score is {pillars['water_and_drainage']}/100.")
    if float(locality["power_outage_hrs_week"]) <= 2:
        strengths.append(f"The project's estimated power interruption baseline is {locality['power_outage_hrs_week']} hours per week.")
    else:
        red_flags.append(f"The project's estimated power interruption baseline is {locality['power_outage_hrs_week']} hours per week.")
    if len(strengths) < 2:
        strengths.append("The locality has a stored Gurugram residential price and location record.")
    return strengths[:5], red_flags[:5]


def build_rule_based_audit(locality, persona, score, air, amenities, news, pillars, preferences=None):
    preferences = preferences or resolve_preferences(persona=persona)
    persona_label = {"family": "families", "commuter": "daily commuters", "investor": "investors"}.get(persona, "locality buyers")
    if preferences["priority_ids"]:
        persona_label = "households prioritizing " + ", ".join(preferences["priority_labels"])
    if score >= 80:
        verdict = f"Strong fit for {persona_label}; verify current property pricing and civic conditions before deciding."
    elif score >= 65:
        verdict = f"Potential fit for {persona_label}; compare the weaker score pillars and confirm them locally."
    else:
        verdict = f"Proceed cautiously as {persona_label}; several quality indicators need verification."

    aqi = air["values"].get("us_aqi")
    if aqi is None:
        air_sentence = "Current air-quality data is unavailable."
    else:
        air_sentence = f"The current modelled US AQI is {round(aqi)} ({aqi_category(aqi)})."
    if amenities["status"] == "live":
        amenity_sentence = (
            f"OpenStreetMap lists {amenities['schools_count']} schools, {amenities['hospitals_count']} healthcare facilities, "
            f"and {amenities['transit_count']} transit features within 2.5 km."
        )
    else:
        amenity_sentence = "Nearby amenities could not be refreshed from OpenStreetMap."
    summary = (
        f"{locality['name']} has a preference-weighted score of {score}/100 for {persona_label}. "
        f"{air_sentence} {amenity_sentence} Safety, water, and power figures are stored project baselines, "
        "not live sensor readings. Air data is modelled; amenity data is from © OpenStreetMap contributors, "
        "and civic headlines are from Google News RSS."
    )
    strengths, red_flags = _strengths_and_flags(locality, air, amenities, pillars)
    if news["status"] != "live":
        red_flags.append("The Gurugram civic-news feed could not be refreshed.")
    elif news["articles_count"] == 0:
        red_flags.append("No matching Gurugram civic-news articles were returned for the last 30 days.")
    outlook = (
        "The free feeds used here do not verify funded or scheduled local infrastructure projects. Check official GMDA, "
        "Haryana, and DHBVN notices before relying on a future works timeline."
    )
    if news["status"] == "live" and news["articles"]:
        outlook = (
            f"The civic feed returned {news['articles_count']} Gurugram articles from the last 30 days. "
            "This is a current-news snapshot, not a verified five-year project forecast; confirm proposals with official notices."
        )
    score_intro = "Your selected needs shape" if preferences["priority_ids"] else "This balanced report gives"
    if amenities["status"] == "live":
        priority_fit = (
            f"{score_intro} a score of {score}/100. Nearby maps list {amenities['schools_count']} schools, "
            f"{amenities['hospitals_count']} healthcare sites and {amenities['transit_count']} transit features."
        )
    else:
        priority_fit = f"{score_intro} a score of {score}/100, but nearby facility counts could not be refreshed."

    if "water_resilience" in preferences["priority_ids"]:
        check_before_deciding = "Water and drainage are stored estimates, not live supply or monsoon readings."
    elif amenities["status"] != "live":
        check_before_deciding = "Nearby facility counts could not refresh; confirm schools, care and transit locally."
    elif air["status"] != "live":
        check_before_deciding = "Air-quality data did not refresh; the air score uses a neutral placeholder."
    else:
        check_before_deciding = "Map counts do not show quality or travel time; water, safety and power are stored baselines."
    return {
        "model": "rule_based",
        "buyer_verdict": verdict,
        "executive_summary": summary,
        "priority_fit": priority_fit,
        "check_before_deciding": check_before_deciding,
        "key_strengths": strengths,
        "red_flags": red_flags[:5],
        "infrastructure_outlook": outlook,
    }


def _normalize_audit(candidate, fallback, model_name):
    if not isinstance(candidate, dict):
        return fallback
    audit = {"model": model_name}
    for key in ("buyer_verdict", "executive_summary", "infrastructure_outlook"):
        value = candidate.get(key)
        audit[key] = value.strip()[:1200] if isinstance(value, str) and value.strip() else fallback[key]
    for key in ("priority_fit", "check_before_deciding"):
        value = candidate.get(key)
        audit[key] = " ".join(value.strip().split()[:20]) if isinstance(value, str) and value.strip() else fallback.get(key, "")
    for key in ("key_strengths", "red_flags"):
        value = candidate.get(key)
        if isinstance(value, list):
            items = [item.strip()[:400] for item in value if isinstance(item, str) and item.strip()]
            audit[key] = items[:5] or fallback[key]
        else:
            audit[key] = fallback[key]
    return audit


async def generate_gemma_analysis(locality, persona, score, pillars, live_metrics, news, fallback, config, preferences=None):
    """Generate the personalized narrative with local Gemma, falling back to the rule-based audit if needed."""
    model = config.get("ollama_model", "").strip()
    if not model:
        return fallback
    preferences = preferences or resolve_preferences(persona=persona)
    prompt_data = {
        "locality": locality["name"],
        "average_price_sqft_inr": int(locality["avg_price_sqft"]),
        "selected_priorities": preferences["priority_labels"],
        "priority_focus_instructions": preferences["focus_instructions"],
        "applied_pillar_weights": preferences["pillar_weights"],
        "schools_healthcare_mix": {
            "schools_share": preferences["school_share"],
            "healthcare_share": preferences["healthcare_share"],
        },
        "score": score,
        "pillars": pillars,
        "live_metrics": live_metrics,
        "news_titles": [item["title"] for item in news["articles"][:8]],
    }
    prompt = (
        "You are LocaleIQ's local neighborhood decision analyst. Personalize the analysis for every selected household priority; "
        "when priorities compete, explain the trade-off instead of ignoring one. Python has already calculated the authoritative "
        "score and weights: do not recalculate or change numeric scores. Return one JSON object with priority_fit and "
        "check_before_deciding, plus buyer_verdict, executive_summary, key_strengths, red_flags, and infrastructure_outlook. "
        "Make each of the first two fields one plain-language sentence of at most 20 words. Use everyday words, short sentences, and no jargon. "
        "Use only supplied facts. Do not invent amenities, safety events, "
        "water conditions, commute times, approved projects, or forecasts. Clearly distinguish stored baselines from live/modelled "
        "data, and state when the evidence is missing. Keep strengths and red_flags as short string arrays. Data: "
        + json.dumps(prompt_data, ensure_ascii=False)
    )
    url = config.get("ollama_url", "http://localhost:11434").rstrip("/") + "/api/generate"
    try:
        timeout = float(config.get("ollama_timeout_seconds", "18"))
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                url,
                json={"model": model, "prompt": prompt, "stream": False, "format": "json"},
            )
            response.raise_for_status()
            generated = response.json().get("response", "")
            return _normalize_audit(json.loads(generated), fallback, f"ollama:{model}")
    except Exception:
        return fallback


async def build_live_report(locality, persona, config, priorities=None):
    timeout = float(config.get("request_timeout_seconds", "12"))
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": "LocaleIQ/1.0 local hackathon prototype"},
    ) as client:
        air, amenities, news = await asyncio.gather(
            fetch_air_quality(client, locality, config),
            fetch_amenities(client, locality, config),
            fetch_news(client, config),
        )

    preferences = resolve_preferences(priorities, persona)
    pillars, score = calculate_scores(locality, air, amenities, persona, preferences=preferences)
    air_values = air["values"]
    live_metrics = {
        "us_aqi": round(air_values["us_aqi"]) if air_values["us_aqi"] is not None else None,
        "aqi_category": aqi_category(air_values["us_aqi"]),
        "pm2_5_ugm3": round(air_values["pm2_5"], 1) if air_values["pm2_5"] is not None else None,
        "pm10_ugm3": round(air_values["pm10"], 1) if air_values["pm10"] is not None else None,
        "power_outage_hrs_week": float(locality["power_outage_hrs_week"]),
        "schools_count": amenities["schools_count"],
        "hospitals_count": amenities["hospitals_count"],
        "transit_count": amenities["transit_count"],
        "air_quality_status": air["status"],
        "amenities_status": amenities["status"],
        "civic_news_status": news["status"],
        "news_articles_analyzed": news["articles_count"],
    }
    audit = build_rule_based_audit(locality, persona, score, air, amenities, news, pillars, preferences)
    audit = await generate_gemma_analysis(
        locality, persona, score, pillars, live_metrics, news, audit, config, preferences
    )
    statuses = {"air_quality": air["status"], "amenities": amenities["status"], "civic_news": news["status"]}
    live_count = sum(status == "live" for status in statuses.values())
    quality_status = "live" if live_count == len(statuses) else "partial" if live_count else "fallback"

    return {
        "locality_id": locality["id"],
        "locality_name": locality["name"],
        "buyer_persona": persona or ("custom" if preferences["priority_ids"] else "balanced"),
        "selected_priorities": preferences["priority_ids"],
        "priority_labels": preferences["priority_labels"],
        "priority_scoring": {
            "pillar_weights": preferences["pillar_weights"],
            "schools_share": preferences["school_share"],
            "healthcare_share": preferences["healthcare_share"],
        },
        "avg_price_sqft_inr": int(locality["avg_price_sqft"]),
        "standardized_quality_score": score,
        "grade": grade_from_score(score),
        "pillar_scores": pillars,
        "live_metrics": live_metrics,
        "gemma_audit": audit,
        "data_quality": {"status": quality_status, "live_sources": live_count, "source_count": len(statuses)},
        "data_sources": {
            "air_quality": air,
            "amenities": amenities,
            "civic_news": news,
            "attribution": [
                "Air quality: Open-Meteo, based on atmospheric composition forecast data.",
                "Amenities: © OpenStreetMap contributors, queried through Overpass API.",
                "Civic headlines: Google News RSS search feed.",
            ],
        },
        "news_items": news["articles"],
        "generated_at": utc_now(),
    }
