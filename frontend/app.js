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

async function loadLocalities() {
    const select = document.getElementById('localitySelect');
    const statusText = document.getElementById('statusText');
    try {
        const res = await fetch(`${API_BASE}/api/localities`);
        if (!res.ok) throw new Error('Failed to load localities');
        const localities = await res.json();
        select.innerHTML = localities
            .map(loc => `<option value="${loc.id}">${loc.name}</option>`)
            .join('');
        statusText.textContent = 'Ready';
        if (localities.length > 0) {
            fetchReport();
        }
    } catch (err) {
        select.innerHTML = '<option value="">Database Offline — Start Backend</option>';
        statusText.textContent = 'Backend Offline';
    }
}

async function fetchReport() {
    const localityId = document.getElementById('localitySelect').value;
    const priorities = getSelectedPriorities();
    const statusText = document.getElementById('statusText');
    const generateBtn = document.getElementById('generateBtn');

    if (!localityId) {
        statusText.textContent = 'Select a Gurugram Locality';
        return;
    }

    statusText.textContent = 'Preparing your personalized neighborhood report...';
    generateBtn.disabled = true;

    try {
        const params = new URLSearchParams({ locality_id: localityId });
        priorities.forEach(priority => params.append('priorities', priority));
        const res = await fetch(`${API_BASE}/api/report?${params.toString()}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        renderReport(data);
        statusText.textContent = data.gemma_audit?.model?.startsWith('ollama:')
            ? 'Local Gemma Analysis Ready'
            : 'Rule-Based Report Ready';
    } catch (err) {
        statusText.textContent = 'Error Generating Report';
    } finally {
        generateBtn.disabled = false;
    }
}

function renderReport(data) {
    document.getElementById('localityName').textContent = data.locality_name;
    document.getElementById('avgPrice').textContent = `₹${Number(data.avg_price_sqft_inr).toLocaleString('en-IN')} / sq.ft`;
    document.getElementById('overallScore').textContent = data.standardized_quality_score;
    document.getElementById('overallGrade').textContent = data.grade;

    document.getElementById('buyerVerdict').textContent = data.gemma_audit.buyer_verdict;
    document.getElementById('execSummary').textContent = data.gemma_audit.executive_summary;
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
    document.getElementById('liveAqi').textContent = m.us_aqi;
    document.getElementById('livePm25').textContent = m.pm2_5_ugm3;
    document.getElementById('livePm10').textContent = m.pm10_ugm3;
    document.getElementById('powerOutage').textContent = `${m.power_outage_hrs_week}h/wk`;
    document.getElementById('aqiCategory').textContent = m.aqi_category;
    document.getElementById('amenityCounts').textContent = `Schools: ${m.schools_count} | Hospitals: ${m.hospitals_count} | Transit: ${m.transit_count}`;
    document.getElementById('newsCount').textContent = `${m.news_articles_analyzed} live Gurugram reports`;

    const p = data.pillar_scores;
    setPillar('Schools', p.schools_and_healthcare);
    setPillar('Safety', p.safety_and_security);
    setPillar('Power', p.power_reliability);
    setPillar('Infra', p.future_infrastructure);
    setPillar('Water', p.water_and_drainage);
    setPillar('Air', p.air_and_environment);

    document.getElementById('strengthsList').innerHTML = data.gemma_audit.key_strengths
        .map(item => `<li>[+] ${item}</li>`)
        .join('');

    document.getElementById('redFlagsList').innerHTML = data.gemma_audit.red_flags
        .map(item => `<li>[!] ${item}</li>`)
        .join('');

    document.getElementById('infraOutlook').textContent = data.gemma_audit.infrastructure_outlook;

    updateChart(p);
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
