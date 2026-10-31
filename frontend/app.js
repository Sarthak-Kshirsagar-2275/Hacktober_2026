let radarChart = null;
const API_BASE = window.location.protocol === 'file:' ? 'http://127.0.0.1:8000' : '';

document.addEventListener('DOMContentLoaded', () => {
    loadLocalities();
    document.getElementById('generateBtn').addEventListener('click', fetchReport);
    document.querySelectorAll('.priority-option').forEach(option => {
        option.addEventListener('change', updatePriorityPickerLabel);
    });
});

function getSelectedPriorities() {
    return [...document.querySelectorAll('.priority-option:checked')].map(option => option.value);
}

function updatePriorityPickerLabel() {
    const count = getSelectedPriorities().length;
    document.getElementById('priorityPickerLabel').textContent = count
        ? `${count} priorit${count === 1 ? 'y' : 'ies'} selected`
        : 'Balanced — select any';
}

function setLoading(isLoading) {
    const overlay = document.getElementById('loadingOverlay');
    overlay.classList.toggle('is-active', isLoading);
    overlay.setAttribute('aria-hidden', String(!isLoading));
    document.body.classList.toggle('overflow-hidden', isLoading);
    document.querySelector('main').setAttribute('aria-busy', String(isLoading));
}

async function loadLocalities() {
    const select = document.getElementById('localitySelect');
    const statusText = document.getElementById('statusText');
    try {
        const res = await fetch(`${API_BASE}/api/localities`);
        if (!res.ok) throw new Error('Locality choices are not available right now.');
        const localities = await res.json();
        select.innerHTML = localities
            .map(loc => `<option value="${loc.id}">${loc.name}</option>`)
            .join('');
        statusText.textContent = 'Ready to generate report';
    } catch (err) {
        select.innerHTML = '<option value="">Locality choices are not available right now.</option>';
        statusText.textContent = 'Report temporarily unavailable';
    }
}

async function fetchReport() {
    const localityId = document.getElementById('localitySelect').value;
    const priorities = getSelectedPriorities();
    const statusText = document.getElementById('statusText');
    const generateBtn = document.getElementById('generateBtn');
    const priorityPicker = document.getElementById('priorityPicker');
    priorityPicker.open = false;

    if (!localityId) {
        statusText.textContent = 'Please choose a locality first.';
        return;
    }

    generateBtn.disabled = true;
    setLoading(true);

    try {
        const params = new URLSearchParams({ locality_id: localityId });
        priorities.forEach(priority => params.append('priorities', priority));
        const res = await fetch(`${API_BASE}/api/report?${params.toString()}`);
        if (!res.ok) throw new Error('The report is not available right now.');
        const data = await res.json();
        renderReport(data);
        statusText.textContent = 'Report ready';
    } catch (err) {
        statusText.textContent = 'We couldn’t prepare the report. Please try again.';
    } finally {
        setLoading(false);
        generateBtn.disabled = false;
    }
}

function renderReport(data) {
    document.getElementById('localityName').textContent = data.locality_name;
    const price = Number(data.avg_price_sqft_inr);
    document.getElementById('avgPrice').textContent = Number.isFinite(price)
        ? `₹${price.toLocaleString('en-IN')} per sq ft`
        : 'Not confirmed';
    document.getElementById('overallScore').textContent = data.standardized_quality_score;
    document.getElementById('overallGrade').textContent = data.grade;

    const audit = data.gemma_audit || {};
    const gemmaStatus = audit.used_gemma === true ? 'Local Gemma' : 'Backup insight';
    ['gemmaOverallStatus', 'gemmaTelemetryStatus', 'gemmaPillarsStatus'].forEach(id => {
        document.getElementById(id).textContent = gemmaStatus;
    });
    document.getElementById('gemmaOverallNumbers').textContent = audit.overall_numbers || 'The score and listed average price are shown above.';
    document.getElementById('gemmaOverallInsight').textContent = audit.overall_insight || 'Compare the figures with your needs and budget.';
    document.getElementById('gemmaTelemetryNumbers').textContent = audit.telemetry_numbers || 'Some current readings are not confirmed.';
    document.getElementById('gemmaTelemetryInsight').textContent = audit.telemetry_insight || 'Check local conditions before making a decision.';
    document.getElementById('gemmaPillarsNumbers').textContent = audit.pillar_numbers || 'The six ratings are shown above.';
    document.getElementById('gemmaPillarsInsight').textContent = audit.pillar_insight || 'A high total can still include a weaker area.';
    document.getElementById('buyerVerdict').textContent = audit.buyer_verdict || 'Compare the ratings with your needs before deciding.';
    document.getElementById('execSummary').textContent = audit.executive_summary || 'Review the figures above and confirm details locally.';
    document.getElementById('appliedPriorities').textContent = (data.priority_labels || []).join(' + ');
    const scoreWeights = data.priority_scoring?.pillar_weights;
    const pillarNames = {
        schools_and_healthcare: 'Schools & healthcare',
        safety_and_security: 'Safety',
        power_reliability: 'Power',
        future_infrastructure: 'Transit / infrastructure',
        water_and_drainage: 'Water',
        air_and_environment: 'Air quality'
    };
    if (scoreWeights) {
        const weightsText = Object.entries(scoreWeights)
            .map(([key, value]) => `${pillarNames[key] || key}: ${Math.round(value * 100)}%`)
            .join(' · ');
        const mix = data.priority_scoring;
        const serviceMix = `Within schools & healthcare: ${Math.round(mix.schools_share * 100)}% schools / ${Math.round(mix.healthcare_share * 100)}% healthcare.`;
        document.getElementById('priorityWeights').textContent = `${weightsText}. ${serviceMix}`;
    } else {
        document.getElementById('priorityWeights').textContent = '--';
    }

    const m = data.live_metrics;
    document.getElementById('liveAqi').textContent = displayValue(m.us_aqi);
    document.getElementById('livePm25').textContent = displayValue(m.pm2_5_ugm3);
    document.getElementById('livePm10').textContent = displayValue(m.pm10_ugm3);
    document.getElementById('powerOutage').textContent = displayValue(m.power_outage_hrs_week, ' hours/week');
    document.getElementById('aqiCategory').textContent = m.aqi_category && m.aqi_category !== 'Unavailable'
        ? m.aqi_category
        : 'Not confirmed';
    document.getElementById('amenityCounts').textContent = m.nearby_places_confirmed
        ? `Schools: ${displayValue(m.schools_count)} | Healthcare: ${displayValue(m.hospitals_count)} | Transit: ${displayValue(m.transit_count)}`
        : 'Nearby schools, healthcare and transit are not confirmed right now.';
    document.getElementById('newsCount').textContent = m.recent_news_available
        ? `${displayValue(m.news_articles_analyzed)} recent local stories reviewed`
        : 'Recent local news is not available right now.';

    const p = data.pillar_scores;
    setPillar('Schools', p.schools_and_healthcare);
    setPillar('Safety', p.safety_and_security);
    setPillar('Power', p.power_reliability);
    setPillar('Infra', p.future_infrastructure);
    setPillar('Water', p.water_and_drainage);
    setPillar('Air', p.air_and_environment);

    renderTextList('strengthsList', audit.key_strengths, '+');
    renderTextList('redFlagsList', audit.red_flags, '•');
    document.getElementById('infraOutlook').textContent = audit.infrastructure_outlook || 'Check current local notices before relying on future plans.';

    updateChart(p);
    renderComparison(data.comparison, audit);
}

function renderComparison(comparison, audit) {
    if (!comparison || !Array.isArray(comparison.rankings)) return;

    const selected = comparison.selected;
    const bestMatch = comparison.best_match;
    const bestValue = comparison.best_value;
    const price = value => `₹${Number(value).toLocaleString('en-IN')}/sq ft`;
    document.getElementById('comparisonStatus').textContent =
        `${comparison.rankings.length} areas scored with your selected priorities.`;
    document.getElementById('selectedRank').textContent =
        `Your area: #${comparison.selected_rank} of ${comparison.rankings.length}`;
    document.getElementById('bestMatchName').textContent = bestMatch.locality_name;
    document.getElementById('bestMatchDetails').textContent =
        `Score ${bestMatch.score}/100 · ${price(bestMatch.avg_price_sqft_inr)} · ${bestMatch.grade}`;
    document.getElementById('bestValueName').textContent = bestValue.locality_name;
    document.getElementById('bestValueDetails').textContent =
        `Score ${bestValue.score}/100 · ${price(bestValue.avg_price_sqft_inr)} · ${bestValue.value_score_per_10000_sqft} points per ₹10,000/sq ft`;

    const list = document.getElementById('comparisonRankings');
    list.replaceChildren();
    comparison.rankings.forEach(area => {
        const item = document.createElement('li');
        item.className = `bg-warm subtle-border px-2 py-1.5 text-xs ${area.locality_id === selected.locality_id ? 'border-l-4 border-l-[#5C3A21]' : ''}`;
        const topLine = document.createElement('div');
        topLine.className = 'flex items-start justify-between gap-2';
        const name = document.createElement('span');
        name.className = 'min-w-0 font-bold text-[#141414]';
        name.textContent = `#${area.rank} ${area.locality_name}`;
        const score = document.createElement('span');
        score.className = 'shrink-0 font-bold text-brown';
        score.textContent = `${area.score}`;
        topLine.append(name, score);
        const details = document.createElement('p');
        details.className = 'text-[10px] text-gray-600 mt-0.5';
        const badges = [];
        if (area.locality_id === selected.locality_id) badges.push('Your area');
        if (area.locality_id === bestMatch.locality_id) badges.push('Top match');
        if (area.locality_id === bestValue.locality_id) badges.push('Best value');
        details.textContent = `${price(area.avg_price_sqft_inr)} · ${badges.join(' · ') || `Value rank #${area.value_rank}`}`;
        item.append(topLine, details);
        list.appendChild(item);
    });

    const facts = document.getElementById('counterfactualFacts');
    const tradeoff = comparison.tradeoff;
    const alternative = comparison.alternative;
    if (!alternative || !tradeoff) {
        facts.textContent = 'Your area is already the top overall match and best value for these priorities.';
    } else {
        const priceDelta = tradeoff.price_delta_sqft;
        const priceText = priceDelta === 0
            ? 'the same listed average price'
            : `${price(Math.abs(priceDelta))} ${priceDelta > 0 ? 'more' : 'less'}`;
        const powerDelta = tradeoff.power_hours_delta_week;
        const powerText = powerDelta === 0
            ? 'similar estimated power interruptions'
            : `${Math.abs(powerDelta)} ${powerDelta > 0 ? 'more' : 'fewer'} estimated power-cut hours/week`;
        const waterDelta = tradeoff.pillar_deltas.water_and_drainage;
        const waterText = waterDelta === 0
            ? 'similar water rating'
            : `water rating ${waterDelta > 0 ? '+' : '−'}${Math.abs(waterDelta)} points`;
        facts.textContent = `${alternative.locality_name} vs ${selected.locality_name}: ${priceText}; ${powerText}; ${waterText}.`;
    }
    document.getElementById('counterfactualInsight').textContent = audit.counterfactual_insight
        || 'Compare the stronger ratings with the listed price before deciding.';
    document.getElementById('comparisonGemmaStatus').textContent =
        audit.used_gemma === true ? 'Local Gemma' : 'Backup insight';

    const hasUnconfirmed = comparison.rankings.some(area =>
        !area.air_reading_confirmed || !area.nearby_places_confirmed
    );
    document.getElementById('comparisonDataNote').textContent = hasUnconfirmed
        ? 'Safety, water and power use saved estimates. Air and nearby places are checked per area; unconfirmed checks use neutral ratings. Price is a listed average.'
        : 'Safety, water and power use saved estimates; air and nearby places use current checks. Price is a listed average.';
}

function displayValue(value, suffix = '') {
    return value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value))
        ? `${value}${suffix}`
        : 'Not confirmed';
}

function renderTextList(id, items, prefix) {
    const list = document.getElementById(id);
    list.replaceChildren();
    (Array.isArray(items) ? items : []).forEach(item => {
        const row = document.createElement('li');
        row.textContent = `${prefix} ${item}`;
        list.appendChild(row);
    });
    if (!list.children.length) {
        const row = document.createElement('li');
        row.textContent = 'No additional details to show.';
        list.appendChild(row);
    }
}

function setPillar(suffix, value) {
    const score = Math.max(0, Math.min(100, Math.round(Number(value) || 0)));
    document.getElementById(`score${suffix}`).textContent = score;
    document.getElementById(`bar${suffix}`).style.width = `${score}%`;
}

function updateChart(p) {
    const ctx = document.getElementById('pillarChart');
    if (radarChart) {
        radarChart.destroy();
    }
    radarChart = new Chart(ctx, {
        type: 'radar',
        data: {
            labels: ['Schools', 'Safety', 'Power', 'Infra', 'Water', 'Air'],
            datasets: [{
                label: 'Pillar Score',
                data: [
                    p.schools_and_healthcare,
                    p.safety_and_security,
                    p.power_reliability,
                    p.future_infrastructure,
                    p.water_and_drainage,
                    p.air_and_environment
                ],
                borderColor: '#5C3A21',
                backgroundColor: 'rgba(92, 58, 33, 0.18)',
                pointBackgroundColor: '#5C3A21',
                pointRadius: 3,
                borderWidth: 2
            }]
        },
        options: {
            animation: false,
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false }
            },
            scales: {
                r: {
                    min: 0,
                    max: 100,
                    ticks: { stepSize: 25, display: false },
                    grid: { color: '#D6C7B8' },
                    angleLines: { color: '#D6C7B8' },
                    pointLabels: {
                        color: '#141414',
                        font: { family: 'Space Grotesk', size: 11, weight: 'bold' }
                    }
                }
            }
        }
    });
}
