document.addEventListener('DOMContentLoaded', function () {
    const startBtn = document.getElementById('start-btn');
    const pauseBtn = document.getElementById('pause-btn');
    const snoozeBtn = document.getElementById('snooze-btn');
    const darkModeToggle = document.getElementById('dark-mode-toggle');
    const miniModeToggle = document.getElementById('mini-mode-toggle');

    let monitoringActive = true;
    let snoozeActive = false;
    let snoozeInterval = null;

    if (darkModeToggle) {
        darkModeToggle.addEventListener('click', () => {
            document.body.classList.toggle('dark-mode');
        });
    }

    if (miniModeToggle) {
        miniModeToggle.addEventListener('click', () => {
            document.body.classList.toggle('mini-mode');
        });
    }

    if (startBtn) {
        startBtn.addEventListener('click', () => {
            monitoringActive = true;
            updateButtonStates();
        });
    }

    if (pauseBtn) {
        pauseBtn.addEventListener('click', () => {
            monitoringActive = false;
            updateButtonStates();
        });
    }

    if (snoozeBtn) {
        snoozeBtn.addEventListener('click', () => {
            fetch('/snooze', { method: 'POST' })
                .then(res => res.json())
                .then(data => {
                    if (data.snooze_until) {
                        startSnoozeCountdown(data.snooze_until);
                    }
                });
        });
    }

    function updateButtonStates() {
        if (!monitoringActive) {
            pauseBtn.classList.add('btn-disabled');
            snoozeBtn.classList.add('btn-disabled');
        } else {
            pauseBtn.classList.remove('btn-disabled');
            snoozeBtn.classList.remove('btn-disabled');
        }
    }

    function updateStats() {
        fetch('/get_stats')
            .then(res => {
                if (!res.ok) throw new Error('Network response was not ok');
                return res.json();
            })
            .then(data => {
                document.getElementById('posture-status').textContent =
                    data.posture_status === 'good' ? 'Good Posture' : 'Poor Posture';
                document.getElementById('focus-time').textContent = formatTime(data.focus_time);
                document.getElementById('posture-alerts').textContent = data.posture_alerts;
                document.getElementById('focus-alerts').textContent = data.focus_alerts;

                document.getElementById('posture-bar').className =
                    data.posture_status === 'good' ? 'progress-bar' : 'progress-bar bad-progress';
                document.getElementById('posture-bar').style.width =
                    data.posture_status === 'good' ? '100%' : '30%';

                const focusPercent = Math.min(100, (data.focus_time / 1800) * 100);
                document.getElementById('focus-bar').style.width = `${focusPercent}%`;

                updateMiniStats();
            })
            .catch(error => console.error('Error updating stats:', error));
    }

    function formatTime(seconds) {
        const mins = Math.floor(seconds / 60);
        const secs = seconds % 60;
        return `${mins}m ${secs}s`;
    }

    function updateMiniStats() {
        // Optional: update stats in mini-mode
    }

    function startSnoozeCountdown(snoozeUntil) {
        if (!snoozeUntil) return;
        const countdownElem = document.getElementById('snooze-countdown');
        if (!countdownElem) return;

        clearInterval(snoozeInterval);

        function updateCountdown() {
            const secondsLeft = Math.round(snoozeUntil - Date.now() / 1000);
            if (secondsLeft > 0) {
                countdownElem.textContent = `Snoozed for ${secondsLeft}s`;
            } else {
                countdownElem.textContent = '';
                clearInterval(snoozeInterval);
            }
        }

        updateCountdown();
        snoozeInterval = setInterval(updateCountdown, 1000);
    }

    setInterval(() => {
        if (monitoringActive && !snoozeActive) {
            updateStats();
        }
    }, 1000);
});
