(() => {
    'use strict';
    const matches = JSON.parse(document.getElementById('resultsConfig').textContent);
    const clock = new Intl.DateTimeFormat('en-GB', {
        timeZone: 'Europe/London', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23'
    });
    const fullDate = new Intl.DateTimeFormat('en-GB', {
        timeZone: 'Europe/London', dateStyle: 'full', timeStyle: 'long'
    });
    const validTime = at => Number.isSafeInteger(at) && at >= 0 && at <= 8640000000000000;
    function goalTime(match, at) {
        if (!validTime(at)) return 'time unknown';
        const elapsed = at - clockTimestamp(match.match_date, '14:00');
        return elapsed < 0 ? 'before kick-off' : Math.floor(elapsed / 60000) + ' min';
    }
    const ukDate = new Intl.DateTimeFormat('en-CA', {
        timeZone: 'Europe/London', year: 'numeric', month: '2-digit', day: '2-digit'
    });

    function clockTimestamp(date, value) {
        if (!value) return null;
        if (!/^\d{2}:\d{2}(:\d{2})?$/.test(value)) throw new Error('Enter a valid clock time.');
        const wanted = value.length === 5 ? value + ':00' : value;
        const utc = Date.parse(date + 'T' + wanted + 'Z');
        const candidates = [utc, utc - 3600000].filter(at => {
            if (!validTime(at) || clock.format(at) !== wanted) return false;
            const parts = Object.fromEntries(ukDate.formatToParts(at).map(part => [part.type, part.value]));
            return parts.year + '-' + parts.month + '-' + parts.day === date;
        });
        if (candidates.length !== 1) {
            throw new Error('This UK time is ambiguous or does not exist due to the clock change. Choose another time.');
        }
        return candidates[0];
    }

    function renderEditor(match, result, isLocal) {
        const editor = document.getElementById('result-editor-' + match.id);
        editor.hidden = !result.opponentGoals;
        const form = document.getElementById('result-times-form-' + match.id);
        const fields = document.getElementById('result-time-fields-' + match.id);
        const status = document.getElementById('result-times-status-' + match.id);
        fields.replaceChildren();
        const previousTimes = Array.from({ length: result.opponentGoals },
            (_, index) => (result.opponentGoalTimes || [])[index] ?? null);
        const inputs = previousTimes.map((at, index) => {
            const label = document.createElement('label');
            label.textContent = 'Opposition goal ' + (index + 1);
            const input = document.createElement('input');
            input.type = 'time';
            input.step = '1';
            input.value = validTime(at) ? clock.format(at) : '';
            input.disabled = isLocal;
            label.appendChild(input);
            fields.appendChild(label);
            return input;
        });
        const button = form.querySelector('button');
        button.disabled = isLocal || Boolean(match.timeEditBlocked);
        status.textContent = isLocal ? 'Open the match and upload this device\'s result before editing times.' : '';
        form.onsubmit = async event => {
            event.preventDefault();
            button.disabled = true;
            try {
                if (!navigator.onLine) throw new Error('Reconnect before saving goal times. Your entries are still here.');
                const local = localResult(match);
                if (local) throw new Error('Upload this device\'s result from the live match before editing times.');
                const times = inputs.map((input, index) =>
                    validTime(previousTimes[index]) && input.value === clock.format(previousTimes[index])
                        ? previousTimes[index] : clockTimestamp(match.match_date, input.value));
                status.textContent = 'Saving goal times...';
                const response = await fetch('/api/matches/' + match.id + '/opposition-times', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ times, previousTimes })
                });
                if (!response.ok) {
                    if (response.status === 409) throw new Error('The result changed. Reload Results before editing goal times.');
                    throw new Error('Could not save goal times. Check your connection or login and try again.');
                }
                const body = await response.json();
                if (!body.success || !body.result) throw new Error(body.error || 'Could not save goal times.');
                match.savedState = body.result;
                let deviceWarning = '';
                try {
                    const raw = localStorage.getItem(match.storageKey);
                    const saved = raw ? JSON.parse(raw) : null;
                    if (saved && saved.pendingSync) {
                        deviceWarning = ' This device has newer unsynced changes; check the live match before uploading.';
                        match.timeEditBlocked = true;
                    } else {
                        localStorage.setItem(match.storageKey, JSON.stringify({
                            ...match.savedState, pendingSync: false
                        }));
                    }
                } catch (cause) {
                    console.error('Cannot update this device\'s saved goal times', cause);
                    deviceWarning = ' Saved on the server, but this device could not be updated.';
                }
                render(match, match.savedState, false);
                status.textContent = 'Goal times saved.' + deviceWarning;
            } catch (cause) {
                console.error('Cannot save opposition goal times', cause);
                status.textContent = cause.message;
            } finally {
                button.disabled = isLocal || Boolean(match.timeEditBlocked);
            }
        };
    }

    function localResult(match) {
        for (const key of [match.storageKey, ...match.legacyKeys]) {
            const raw = localStorage.getItem(key);
            if (!raw) continue;
            const saved = JSON.parse(raw);
            if (!Array.isArray(saved.goals) || saved.goals.some(goal => !goal || typeof goal !== 'object')
                || !Number.isInteger(saved.opponentGoals) || saved.opponentGoals < 0
                || (saved.opponentGoalTimes !== undefined && (!Array.isArray(saved.opponentGoalTimes)
                    || saved.opponentGoalTimes.length !== saved.opponentGoals
                    || saved.opponentGoalTimes.some(at => at !== null && !validTime(at))))) {
                throw new Error('Invalid result saved on this device');
            }
            const hasRecordedResult = saved.goals.length || saved.opponentGoals || saved.motmPlayerId;
            if (saved.pendingSync || (hasRecordedResult && (key !== match.storageKey || !match.hasResult))) return saved;
            return null;
        }
        return null;
    }

    function render(match, result, isLocal) {
        renderEditor(match, result, isLocal);
        const hasResult = match.hasResult || isLocal;
        const score = document.getElementById('result-score-' + match.id);
        score.replaceChildren();
        if (hasResult) {
            const home = document.createElement('span');
            home.textContent = result.goals.length;
            const divider = document.createElement('span');
            divider.className = 'result-score-divider';
            divider.textContent = ' : ';
            const away = document.createElement('span');
            away.textContent = result.opponentGoals;
            score.append(home, divider, away);
        } else {
            score.textContent = 'Not recorded';
        }
        score.classList.toggle('is-missing', !hasResult);
        const source = document.getElementById('result-source-' + match.id);
        source.textContent = isLocal
            ? 'Saved on this device. Open the match to upload or retry saving.'
            : hasResult ? 'Recorded score' : 'No result saved. Open the match to record one.';
        source.classList.toggle('is-local', isLocal);
        const events = result.goals.map(goal => ({
            at: validTime(goal.at) ? goal.at : null,
            label: 'Eagles: ' + goal.scorer,
            assist: goal.assist ? 'Assist: ' + goal.assist : 'No assist',
            opposition: false
        }));
        for (let index = 0; index < result.opponentGoals; index += 1) {
            const at = (result.opponentGoalTimes || [])[index];
            events.push({
                at: validTime(at) ? at : null,
                label: match.opponent + ': goal', assist: '', opposition: true
            });
        }
        document.getElementById('result-home-goals-' + match.id).textContent = result.goals.length
            ? result.goals.map(goal => goal.scorer + ' (' + goalTime(match, goal.at) + ')').join(', ')
            : hasResult ? 'No goals' : '-';
        document.getElementById('result-away-goals-' + match.id).textContent = result.opponentGoals
            ? events.filter(event => event.opposition).map(event => 'Goal (' + goalTime(match, event.at) + ')').join(', ')
            : hasResult ? 'No goals' : '-';
        const assists = result.goals.filter(goal => goal.assist);
        document.getElementById('result-assists-' + match.id).textContent = assists.length
            ? assists.map(goal => goal.assist + ' (' + goalTime(match, goal.at) + ')').join(', ')
            : 'No assists recorded';
        events.sort((a, b) => (a.at ?? Infinity) - (b.at ?? Infinity));
        const timeline = document.getElementById('result-timeline-' + match.id);
        timeline.replaceChildren();
        events.forEach(event => {
            const entry = document.createElement('li');
            entry.className = 'result-event' + (event.opposition ? ' is-opposition' : '');
            const time = document.createElement(event.at === null ? 'span' : 'time');
            time.className = 'result-event-time';
            time.textContent = event.at === null ? 'Time unknown' : goalTime(match, event.at);
            if (event.at !== null) {
                time.dateTime = new Date(event.at).toISOString();
                time.title = fullDate.format(event.at);
            }
            const detail = document.createElement('div');
            detail.className = 'result-event-detail';
            const label = document.createElement('strong');
            label.textContent = event.label;
            detail.appendChild(label);
            if (event.assist) {
                const assist = document.createElement('span');
                assist.textContent = event.assist;
                detail.appendChild(assist);
            }
            entry.append(time, detail);
            timeline.appendChild(entry);
        });
        if (!events.length && hasResult) {
            const empty = document.createElement('li');
            empty.className = 'result-no-goals';
            empty.textContent = 'No goals recorded.';
            timeline.appendChild(empty);
        }
    }

    function refresh() {
        matches.forEach(match => {
            let local = null;
            const error = document.getElementById('result-error-' + match.id);
            error.hidden = true;
            try {
                local = localResult(match);
            } catch (cause) {
                console.error('Cannot read the result saved on this device for match ' + match.id, cause);
                error.textContent = 'Cannot read this device\'s saved result. Showing the server result instead. '
                    + 'Open the match to check it; do not clear browser data.';
                error.hidden = false;
            }
            render(match, local || match.savedState, Boolean(local));
        });
    }
    window.addEventListener('storage', refresh);
    refresh();
})();
