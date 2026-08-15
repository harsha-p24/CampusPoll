// ── CSRF helper ──────────────────────────────────────────────
function getCsrfToken() {
    return document.querySelector('meta[name="csrf-token"]')?.content || '';
}

// ── Analytics tracking ───────────────────────────────────────
function trackEvent(eventType, page, details) {
    fetch('/analytics/track', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
        body: JSON.stringify({ event_type: eventType, page: page, details: details || null })
    }).catch(function() {});
}

// Track page load time
window.addEventListener('load', function() {
    var loadTime = performance.timing ? performance.timing.loadEventEnd - performance.timing.navigationStart : null;
    fetch('/analytics/track', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
        body: JSON.stringify({ event_type: 'page_load', page: window.location.pathname, load_time_ms: loadTime })
    }).catch(function() {});
});

// Track button clicks
document.addEventListener('click', function(e) {
    var el = e.target;
    if (el.tagName === 'BUTTON' || el.tagName === 'A' || el.classList.contains('btn')) {
        trackEvent('button_click', window.location.pathname, 'element:' + el.textContent.trim().substring(0, 50));
    }
});

// ── Session timeout (25 min warning) ─────────────────────────
var sessionTimeout;
function resetSessionTimer() {
    clearTimeout(sessionTimeout);
    sessionTimeout = setTimeout(function() {
        if (confirm('Your session will expire soon. Stay logged in?')) {
            resetSessionTimer();
        } else {
            window.location.href = '/logout';
        }
    }, 25 * 60 * 1000);
}
document.addEventListener('mousemove', resetSessionTimer);
document.addEventListener('keypress', resetSessionTimer);
resetSessionTimer();

// ── Auto-dismiss alerts ───────────────────────────────────────
document.querySelectorAll('.alert').forEach(function(alert) {
    setTimeout(function() {
        alert.style.transition = 'opacity 0.5s';
        alert.style.opacity = '0';
        setTimeout(function() { alert.remove(); }, 500);
    }, 5000);
});

// ── Notification Bell ─────────────────────────────────────────
var bell = document.getElementById('notifBell');
if (bell) {
    // Toggle dropdown (click + keyboard)
    function toggleBell(e) {
        e.stopPropagation();
        bell.classList.toggle('open');
        var isOpen = bell.classList.contains('open');
        bell.setAttribute('aria-expanded', isOpen);
        if (isOpen) loadNotifications();
    }
    bell.addEventListener('click', toggleBell);
    bell.addEventListener('keydown', function(e) {
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            toggleBell(e);
        }
        if (e.key === 'Escape') {
            bell.classList.remove('open');
            bell.setAttribute('aria-expanded', 'false');
        }
    });
    document.addEventListener('click', function() { bell.classList.remove('open'); });

    // Load notifications
    function loadNotifications() {
        fetch('/notifications/', { headers: { 'X-CSRFToken': getCsrfToken() } })
            .then(r => r.json())
            .then(data => {
                var countEl = document.getElementById('notifCount');
                var listEl = document.getElementById('notifList');
                if (data.unread > 0) {
                    countEl.textContent = data.unread > 9 ? '9+' : data.unread;
                    countEl.style.display = 'inline-block';
                } else {
                    countEl.style.display = 'none';
                }
                if (data.notifications.length === 0) {
                    listEl.innerHTML = '<p style="padding:12px;color:#888;font-size:13px;">No notifications</p>';
                    return;
                }
                listEl.innerHTML = data.notifications.map(n => `
                    <div class="notif-item ${n.is_read ? '' : 'unread'}" onclick="markRead(${n.id}, this)">
                        <div class="notif-item-title">${n.title}</div>
                        <div class="notif-item-msg">${n.message}</div>
                        <div class="notif-item-time">${n.created_at}</div>
                    </div>
                `).join('');
            }).catch(function() {});
    }

    function markRead(id, el) {
        fetch('/notifications/mark-read/' + id, {
            method: 'POST', headers: { 'X-CSRFToken': getCsrfToken() }
        }).then(() => {
            el.classList.remove('unread');
            loadNotifications();
        });
    }

    window.markAllRead = function() {
        fetch('/notifications/mark-all-read', {
            method: 'POST', headers: { 'X-CSRFToken': getCsrfToken() }
        }).then(() => loadNotifications());
    };

    // Poll for new notifications every 60 seconds
    loadNotifications();
    setInterval(loadNotifications, 60000);
}

// ── Password strength meter ───────────────────────────────────
function initPasswordStrength() {
    var input = document.querySelector('input[name="password"]');
    var container = document.querySelector('.pw-strength');
    if (!input || !container) return;
    input.addEventListener('input', function() {
        var pw = input.value;
        var score = 0;
        var hints = [];
        if (pw.length >= 8) score++; else hints.push('At least 8 characters');
        if (/[A-Z]/.test(pw)) score++; else hints.push('One uppercase letter');
        if (/[a-z]/.test(pw)) score++; else hints.push('One lowercase letter');
        if (/\d/.test(pw)) score++; else hints.push('One number');
        if (/[@$!%*?&_\-]/.test(pw)) score++; else hints.push('One special character (@$!%*?&_-)');
        var bar = container.querySelector('.pw-bar');
        var hint = container.querySelector('.pw-hint');
        var colors = ['#f44336','#f44336','#ff9800','#ffc107','#4caf50'];
        var labels = ['Very Weak','Weak','Fair','Good','Strong'];
        bar.style.width = (score * 20) + '%';
        bar.style.background = colors[score] || '#eee';
        if (score === 5) {
            hint.textContent = '✅ ' + labels[score];
            hint.className = 'pw-hint ok';
            input.classList.remove('error'); input.classList.add('ok');
        } else {
            hint.textContent = labels[score] + (hints.length ? ' — Need: ' + hints[0] : '');
            hint.className = 'pw-hint';
            input.classList.remove('ok');
            if (pw.length > 0) input.classList.add('error');
        }
    });
}
initPasswordStrength();

// ── Loading state on form submit ──────────────────────────────
document.querySelectorAll('form').forEach(function(form) {
    form.addEventListener('submit', function() {
        var btn = form.querySelector('button[type="submit"]');
        if (btn) btn.classList.add('loading');
    });
});

// ── Real-time email validation ────────────────────────────────
var emailInput = document.querySelector('input[type="email"]');
if (emailInput) {
    emailInput.addEventListener('blur', function() {
        var val = emailInput.value.trim();
        var ok = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(val);
        emailInput.classList.toggle('ok', ok && val.length > 0);
        emailInput.classList.toggle('error', !ok && val.length > 0);
    });
}
