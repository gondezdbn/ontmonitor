// static/js/main.js
document.addEventListener('DOMContentLoaded', () => {
    const socket = io();

    // --- Elemen UI ---
    const startBtn = document.getElementById('start-btn');
    const stopBtn = document.getElementById('stop-btn');
    const ipInput = document.getElementById('ip-address');
    const communityInput = document.getElementById('community-string');
    const statusMessage = document.getElementById('status-message');
    const pingValue = document.getElementById('ping-value');
    const userCount = document.getElementById('user-count');
    const downloadValue = document.getElementById('download-value');
    const uploadValue = document.getElementById('upload-value');
    const themeToggle = document.getElementById('theme-toggle');

    // --- Logika Mode Gelap ---
    const currentTheme = localStorage.getItem('theme');
    if (currentTheme) {
        document.body.classList.add(currentTheme);
        if (currentTheme === 'dark-mode') {
            themeToggle.checked = true;
        }
    }

    function updateChartTheme() {
        const isDarkMode = document.body.classList.contains('dark-mode');
        const newColor = isDarkMode ? 'rgba(255, 255, 255, 0.7)' : 'rgba(0, 0, 0, 0.7)';
        Chart.defaults.color = newColor;
        bandwidthChart.options.scales.x.grid.color = isDarkMode ? 'rgba(255, 255, 255, 0.1)' : 'rgba(0, 0, 0, 0.1)';
        bandwidthChart.options.scales.y.grid.color = isDarkMode ? 'rgba(255, 255, 255, 0.1)' : 'rgba(0, 0, 0, 0.1)';
        bandwidthChart.update();
    }

    themeToggle.addEventListener('click', () => {
        document.body.classList.toggle('dark-mode');
        let theme = 'light-mode';
        if (document.body.classList.contains('dark-mode')) {
            theme = 'dark-mode';
        }
        localStorage.setItem('theme', theme);
        updateChartTheme();
    });

    // --- Logika Chart.js ---
    const createChart = (canvasId) => {
        const ctx = document.getElementById(canvasId).getContext('2d');
        return new Chart(ctx, {
            type: 'line',
            data: {
                datasets: [{
                    label: 'Download (Kbps)',
                    borderColor: 'rgba(54, 162, 235, 1)',
                    backgroundColor: 'rgba(54, 162, 235, 0.2)',
                    data: [], fill: true, tension: 0.4
                }, {
                    label: 'Upload (Kbps)',
                    borderColor: 'rgba(255, 99, 132, 1)',
                    backgroundColor: 'rgba(255, 99, 132, 0.2)',
                    data: [], fill: true, tension: 0.4
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: { type: 'time', time: { unit: 'second', displayFormats: { second: 'HH:mm:ss' } } },
                    y: { beginAtZero: true, ticks: { callback: (value) => value + ' Kbps' } }
                }
            }
        });
    };

    const bandwidthChart = createChart('bandwidth-chart');
    updateChartTheme(); // Set tema awal untuk chart

    function addDataToChart(chart, newData) {
        const timestamp = new Date();
        chart.data.datasets[0].data.push({ x: timestamp, y: newData.download });
        chart.data.datasets[1].data.push({ x: timestamp, y: newData.upload });
        if (chart.data.datasets[0].data.length > 30) {
            chart.data.datasets.forEach(dataset => dataset.data.shift());
        }
        chart.update('quiet');
    }

    // --- Logika Tombol dan Status ---
    function setStatus(message, type = 'info') {
        statusMessage.innerHTML = `<div class="alert alert-${type} alert-dismissible fade show" role="alert">${message}<button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button></div>`;
    }

    startBtn.addEventListener('click', () => {
        const ip = ipInput.value;
        const community = communityInput.value;
        if (!ip) {
            setStatus('Alamat IP tidak boleh kosong.', 'warning');
            return;
        }
        socket.emit('start_monitoring', { ip, community });
        setStatus('Menyambungkan...', 'info');
        startBtn.disabled = true;
        stopBtn.disabled = false;
    });

    stopBtn.addEventListener('click', () => {
        socket.emit('stop_monitoring');
        startBtn.disabled = false;
        stopBtn.disabled = true;
    });

    // --- Event Handler Socket.IO ---
    socket.on('connect_success', (data) => setStatus(data.message, 'success'));
    socket.on('connect_error', (data) => {
        setStatus(data.message, 'danger');
        startBtn.disabled = false;
        stopBtn.disabled = true;
    });
    socket.on('disconnect_status', (data) => setStatus(data.message, 'warning'));
    socket.on('update_data', (data) => {
        pingValue.textContent = data.ping;
        userCount.textContent = data.users;
        downloadValue.textContent = data.download;
        uploadValue.textContent = data.upload;
        addDataToChart(bandwidthChart, {
            download: parseFloat(data.download),
            upload: parseFloat(data.upload)
        });
    });
});
