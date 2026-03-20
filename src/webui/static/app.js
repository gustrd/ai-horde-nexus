document.addEventListener("DOMContentLoaded", () => {
    // State Tracking
    let speedChart = null;
    let expandedRows = new Set();
    let history = [];
    let activityChart = null;
    let lastKudosUpdate = 0;

    // Control API
    window.controlAction = async (action) => {
        try {
            if (action === 'shutdown' && !confirm("Are you sure you want to stop the worker? Current jobs will complete first.")) return;
            const resp = await fetch("/api/control", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ action })
            });
            const data = await resp.json();
            if (data.status === "ok" && action !== "shutdown") {
                updateUIState(data.paused);
            }
        } catch (e) {
            console.error("Control action failed:", e);
        }
    };

    const updateUIState = (isPaused) => {
        const pBtn = document.getElementById("btn-pause");
        const rBtn = document.getElementById("btn-resume");
        if (isPaused) {
            pBtn.classList.add("hidden");
            rBtn.classList.remove("hidden");
        } else {
            pBtn.classList.remove("hidden");
            rBtn.classList.add("hidden");
        }
    };

    // Helper for expandable rows
    window.toggleRow = (id) => {
        const row = document.getElementById(id);
        if (row) {
            row.classList.toggle('hidden');
            if (row.classList.contains('hidden')) {
                expandedRows.delete(id);
            } else {
                expandedRows.add(id);
            }
        }
    };

    // Charts Initialization
    const initCharts = () => {
        const actCtx = document.getElementById('activityChart').getContext('2d');
        const speedCtx = document.getElementById('speedChart').getContext('2d');

        activityChart = new Chart(actCtx, {
            type: 'line',
            data: {
                labels: [],
                datasets: [
                    {
                        label: 'Total Completed Jobs',
                        data: [],
                        borderColor: '#3b82f6',
                        backgroundColor: 'rgba(59, 130, 246, 0.1)',
                        borderWidth: 2, fill: true, tension: 0.2
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: { display: true, text: 'Completed Jobs over Session', color: '#fff' },
                    legend: { display: false }
                },
                scales: {
                    x: { ticks: { color: '#94a3b8' }, grid: { display: false } },
                    y: { type: 'linear', display: true, ticks: { color: '#3b82f6', precision: 0 }, grid: { color: '#334155' } }
                }
            }
        });

        speedChart = new Chart(speedCtx, {
            type: 'bar',
            data: {
                labels: [],
                datasets: [{
                    label: 'Tokens per Second (t/s)',
                    data: [],
                    backgroundColor: '#8b5cf6',
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: { display: true, text: 'Generation Speed (Avg t/s per 10m block)', color: '#fff' },
                    legend: { display: false }
                },
                scales: {
                    x: { ticks: { color: '#94a3b8' }, grid: { display: false } },
                    y: { grid: { color: '#334155' } }
                }
            }
        });
    };

    // Update Stats & Push to Activity Series
    const updateStats = async () => {
        try {
            const resp = await fetch("/api/stats");
            const data = await resp.json();
            
            // Format uptime (minutes only)
            const h = Math.floor(data.uptime_seconds / 3600);
            const m = Math.floor((data.uptime_seconds % 3600) / 60);
            document.getElementById("uptime").innerText = h > 0 ? `${h}h ${m}m` : `${m}m`;
            
            document.getElementById("total_jobs").innerText = data.total_jobs;
            document.getElementById("total_tokens").innerText = data.total_tokens;
            document.getElementById("total_kudos").innerText = data.total_kudos.toFixed(1);

            // Update Kudos/h only every minute (60,000ms)
            const nowTime = Date.now();
            if (nowTime - lastKudosUpdate > 60000 || lastKudosUpdate === 0) {
                document.getElementById("kudos_per_hour").innerText = data.kudos_per_hour.toFixed(2);
                lastKudosUpdate = nowTime;
            }
            
            document.getElementById("max_active_threads").innerText = data.max_active_threads;
            document.getElementById("active_jobs_count").innerText = data.active_jobs_count;
            
            // Sync Pause state
            updateUIState(data.paused);

            // Update Activity Chart from backend history
            if (data.session_history) {
                activityChart.data.labels = data.session_history.map(pt => {
                    const d = new Date(pt.timestamp * 1000);
                    return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`;
                });
                activityChart.data.datasets[0].data = data.session_history.map(pt => pt.total_jobs);
                activityChart.update('none');
            }
        } catch (e) {
            console.error("Failed to update stats", e);
        }
    };

    // Update Active Jobs Table
    const updateActive = async () => {
        try {
            const resp = await fetch("/api/jobs/active");
            const data = await resp.json();
            const body = document.getElementById("active-jobs-body");
            
            if (data.length === 0) {
                body.innerHTML = '<tr><td colspan="5" style="text-align:center">Idle</td></tr>';
                return;
            }

            // Generate HTML for each Active Job + Expanded Detail row
            body.innerHTML = data.map(j => `
                <tr class="clickable-row" onclick="toggleRow('act-${j.job_id}')" title="Click to expand details">
                    <td>${j.thread_id}</td>
                    <td><code>${j.job_id.slice(0, 12)}...</code></td>
                    <td>${j.model.slice(0, 20)}...</td>
                    <td><span class="status-badge status-${j.status.toLowerCase()}">${j.status}</span></td>
                    <td>${j.duration}s</td>
                </tr>
                <tr id="act-${j.job_id}" class="${expandedRows.has(`act-${j.job_id}`) ? '' : 'hidden'}">
                    <td colspan="5" class="details-cell">
                        <b>📝 Context Len:</b> ${j.context_len} tokens
                        <span style="margin: 0 1rem;">|</span>
                        <b>🎯 Requested:</b> ${j.requested_tokens} tokens
                        <span style="margin: 0 1rem;">|</span>
                        <b>✅ Delivered:</b> <i>(Processing)</i>
                    </td>
                </tr>
            `).join("");
        } catch (e) {
            console.error("Failed to update active jobs", e);
        }
    };

    // Update History Table and Speed Chart
    const updateHistory = async () => {
        try {
            const resp = await fetch("/api/jobs/history");
            const data = await resp.json();
            const body = document.getElementById("history-body");
            
            body.innerHTML = data.map(h => `
                <tr class="clickable-row" onclick="toggleRow('hist-${h.job_id}')" title="Click to expand details">
                    <td><code>${h.job_id.slice(0, 12)}...</code></td>
                    <td>${h.model.slice(0, 20)}...</td>
                    <td>${h.tokens}</td>
                    <td>${h.kudos.toFixed(1)}</td>
                    <td>${h.duration}s</td>
                    <td><span class="status-badge ${h.status.startsWith('error') ? 'status-error' : 'status-success'}">${h.status}</span></td>
                </tr>
                <tr id="hist-${h.job_id}" class="${expandedRows.has(`hist-${h.job_id}`) ? '' : 'hidden'}">
                    <td colspan="6" class="details-cell">
                        <b>📝 Context Len:</b> ${h.context_len} tokens
                        <span style="margin: 0 1rem;">|</span>
                        <b>🎯 Requested:</b> ${h.requested_tokens} tokens
                        <span style="margin: 0 1rem;">|</span>
                        <b>✅ Delivered:</b> ${h.tokens} tokens
                        <span style="margin: 0 1rem;">|</span>
                        <b>⚡ Speed:</b> ${h.duration > 0 ? (h.tokens / h.duration).toFixed(1) : 0} t/s
                    </td>
                </tr>
            `).join("");

            // Update Speed Chart if history changed
            if (JSON.stringify(data) !== JSON.stringify(history)) {
                history = data;
                updateSpeedChart(data);
            }
        } catch (e) {
            console.error("Failed to update history", e);
        }
    };

    const updateSpeedChart = (data) => {
        const validData = [...data].reverse().filter(e => !e.status.startsWith('error') && e.duration > 0);
        
        // Group by 10 minute blocks (600 seconds)
        const buckets = {};
        validData.forEach(e => {
            const blockStart = Math.floor(e.timestamp / 600) * 600;
            if (!buckets[blockStart]) buckets[blockStart] = { tokens: 0, duration: 0, count: 0 };
            buckets[blockStart].tokens += e.tokens;
            buckets[blockStart].duration += e.duration;
            buckets[blockStart].count += 1;
        });

        const sortedBlocks = Object.keys(buckets).sort((a,b) => a - b);
        const labels = sortedBlocks.map(ts => {
            const d = new Date(ts * 1000);
            return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`;
        });
        
        // Avg t/s = total tokens in block / total generation time in block
        const speeds = sortedBlocks.map(ts => {
            return buckets[ts].tokens / buckets[ts].duration;
        });

        speedChart.data.labels = labels;
        speedChart.data.datasets[0].data = speeds;
        speedChart.update('none');
    }

    // Main Loop
    initCharts();
    const tick = () => {
        updateStats();
        updateActive();
        updateHistory();
    };

    tick();
    setInterval(tick, 2000); // 2 second polling
});
