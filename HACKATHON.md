# HACKATHON Submission Details

## 1. Team & Member Details
- Team Name: Monolith
- Team Member: Sarthak Kshirsagar
- Track / Domain: Real Estate & Urban Civic Intelligence

## 2. Selected Problem Statement
Homebuyers struggle to get concise data on matters like Electricity supply, Water supply, Nearby landmarks, Local Markets, average AQI, and many more.

### Problem Articulation
Purchasing a residential property in India is frequently a multi-crore, once-in-a-lifetime financial commitment, yet buyers are forced to make decisions under severe information asymmetry. While property listings, floor plans, and builder brochures heavily market what exists *inside* the boundary wall of a housing society, the actual livability and long-term value of a home are governed by the surrounding neighborhood ecosystem—where standardized, verifiable data is virtually non-existent.

Prospective homebuyers currently face four critical blind spots beyond individual property inspection:
1. Fragmented & Unverified Utility Realities: Crucial day-to-day living parameters—such as municipal canal water availability versus summer water-tanker dependency, monsoon waterlogging propensity, and feeder-level power outage frequencies—are never disclosed in real estate listings. Buyers must rely on biased broker assurances or scattered word-of-mouth feedback.
2. Hyperlocal Environmental & Safety Opacity: Air Quality Indices (AQI), particulate matter exposure (PM2.5/PM10), noise pollution corridors, street lighting, and localized crime statistics vary drastically even across adjacent sectors in rapidly urbanizing metros, yet no unified benchmark aggregates these risks at the neighborhood level.
3. Social Infrastructure Verification Gaps: Evaluating the real accessibility and quality of essential social infrastructure—schools, tertiary hospitals, parks, and public transit nodes—requires manual cross-referencing across multiple maps and directories without standardized scoring.
4. Speculative Infrastructure Claims: Homebuyers are routinely pitched inflated appreciation promises based on rumored metro extensions, expressway links, or civic master plans, with no neutral mechanism to separate approved, funded municipal projects from speculative sales pitches.

Because these environmental, civic, utility, and infrastructural signals remain trapped in disparate municipal reports, public sensor networks, and unstructured local forums, homebuyers lack an objective, apples-to-apples **Standardized Neighborhood Quality Report** to evaluate risk and livability before committing their capital.

## 3. Open-Weight AI Model & Justification
- Model Used: Gemma 2 9B locally run via ollama
- Justification:
  - Open-Weight Compliance & Local Reproducibility: Gemma 2 9B is a publicly available open-weight model that runs deterministically on local hardware via Ollama without proprietary vendor lock-in.
  - High Reasoning-to-Parameter Efficiency: Neighborhood quality assessment requires synthesizing messy, unstructured civic observations (municipal master-plan notes, commuter bottlenecks, utility reliability reports, and environmental metrics) into structured, objective risk assessments. At 9 billion parameters, Gemma 2 delivers strong instruction-following, JSON schema adherence, and analytical summarization comparable to much larger models while maintaining low inference latency suitable for interactive neighborhood audits.
  - Development & Runtime Synergy: Using Gemma 2 9B both as the core unstructured-data synthesis engine in the application and for code generation ensures a tight, maintainable architecture tailored to small-context, high-precision execution.
