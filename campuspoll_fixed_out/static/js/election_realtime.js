// ── Election real-time helper ───────────────────────────────────────────────
// Included site-wide via base.html. No-ops entirely on pages with nothing
// relevant, so it's safe to load everywhere.
(function () {
    var electionCards = document.querySelectorAll('[data-election-id]');
    var countdowns     = document.querySelectorAll('.countdown[data-end]');
    if (electionCards.length === 0 && countdowns.length === 0) return;

    var RELOADED_ONCE = false;
    function softReload() {
        // Guard against multiple simultaneous triggers (socket + countdown + poll)
        if (RELOADED_ONCE) return;
        RELOADED_ONCE = true;
        // Small random jitter so many open tabs don't all hit the server
        // at the exact same millisecond when an election flips state.
        setTimeout(function () { window.location.reload(); }, 300 + Math.random() * 700);
    }

    // ── 1. Countdown timers: display + auto-reload once expired ────────────
    countdowns.forEach(function (el) {
        var end  = new Date(el.dataset.end);
        var mode = el.dataset.mode || 'closes'; // 'opens' or 'closes'
        function update() {
            var diff = end - new Date();
            if (diff <= 0) {
                el.textContent = mode === 'opens' ? ' (Voting is starting now…)' : ' (Closed)';
                softReload();
                return;
            }
            var h = Math.floor(diff / 3600000), m = Math.floor((diff % 3600000) / 60000), s = Math.floor((diff % 60000) / 1000);
            el.textContent = ' (' + h + 'h ' + m + 'm ' + s + 's ' + (mode === 'opens' ? 'until voting opens' : 'left') + ')';
            setTimeout(update, 1000);
        }
        update();
    });

    // ── 2. Socket.IO push: election status changes / results announced ─────
    if (typeof io === 'function' && electionCards.length > 0) {
        try {
            var socket = io();
            var ids = Array.prototype.map.call(electionCards, function (el) { return el.dataset.electionId; });
            socket.on('connect', function () {
                ids.forEach(function (id) { socket.emit('join_election', { election_id: parseInt(id, 10) }); });
            });
            socket.on('election_status', function (data) {
                if (ids.indexOf(String(data.election_id)) !== -1) softReload();
            });
            socket.on('results_announced', function (data) {
                if (ids.indexOf(String(data.election_id)) !== -1) softReload();
            });
        } catch (e) { /* Socket.IO not loaded on this page — fall back to polling below */ }
    }

    // ── 3. Polling fallback (covers dev setups without Celery/Redis bridge,
    //      dropped sockets, or throttled background tabs) — every 20s,
    //      re-check whether any visible election's voting start/end boundary
    //      has now been crossed since the page loaded, and reload once. ────
    var snapshot = Array.prototype.map.call(electionCards, function (el) {
        var now = new Date();
        return {
            start: new Date(el.dataset.votingStart),
            end:   new Date(el.dataset.votingEnd),
            wasBeforeStart: now < new Date(el.dataset.votingStart),
            wasBeforeEnd:   now < new Date(el.dataset.votingEnd),
        };
    });
    setInterval(function () {
        if (RELOADED_ONCE) return;
        var now = new Date();
        var crossed = snapshot.some(function (s) {
            return (s.wasBeforeStart && now >= s.start) || (s.wasBeforeEnd && now >= s.end);
        });
        if (crossed) softReload();
    }, 20000);
})();
