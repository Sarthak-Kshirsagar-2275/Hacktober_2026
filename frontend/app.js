let radarChart = null;
const API_BASE = window.location.protocol === 'file:' ? 'http://127.0.0.1:8000' : '';

document.addEventListener('DOMContentLoaded', () => {
    const generateBtn = document.getElementById('generateBtn');
    const localityInput = document.getElementById('localityInput');

    generateBtn.addEventListener('click', fetchReport);
    localityInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') fetchReport();
    });
});

async function fetchReport() {
    const query = document.getElementById('localityInput').value.trim();
    const persona = document.getElementById('personaSelect').value;
    const statusText = document.getElementById('statusText');
    const generateBtn = document.getElementById('generateBtn');

    if (!query) {
        statusText.textContent = 'Enter a Gurugram Sector';
        return;
    }

    statusText.textContent = 'Fetching Live Data & Running Gemma 4 12B...';
    generateBtn.disabled = true;

    try {
        const url = `${API_BASE}/api/report?query=${encodeURIComponent(query)}&persona=${encodeURIComponent(persona)}`;
        const res = await fetch(url);
        if (!res.ok) {
            throw new Error(`HTTP ${res.status}`);
        }
        const data = await res.json();
        renderReport(data);
        statusText.textContent = 'Live Audit Complete';
    } catch (err) {
        statusText.textContent = 'Error: Backend Offline or Locality Not Found';
    } finally {
        generateBtn.disabled = false;
    }
}

function renderReport(data) {
    document.getElementById('localityName').textContent = data.locality_name;
    document.getElementById('localityCoords').textContent = `${Number(data.lat).toFixed(4)}, ${Number(data.lon).toFixed(4)}`;
    document.getElementById('overallScore').textContent = data.standardized_quality_score;
    document.getElementById('overallGrade').textContent = data.grade;

    document.getElementById('buyerVerdict').textContent = data.gemma_audit.buyer_verdict;
    document.getElementById('execSummary').textContent = data.gemma_audit.executive_summary;

    const m = data.live_metrics;
    document.getElementById('liveAqi').textContent = m.us_aqi;
    document.getElementById('livePm25').textContent = m.pm2_5_ugm3;
    document.getElementById('livePm10').textContent = m.pm10_ugm3;
    document.getElementById('liveElevation').textContent = `${m.elevation_m}m`;
    document.getElementById('aqiCategory').textContent = m.aqi_category;
    document.getElementById('amenityCounts').textContent = `Schools: ${m.schools_count} | Hospitals: ${m.hospitals_count} | Transit: ${m.transit_count}`;
    document.getElementById('newsCount').textContent = `${m.news_articles_analyzed} recent Gurugram civic reports`;

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
