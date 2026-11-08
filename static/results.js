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
    const goalTime = at => validTime(at) ? clock.format(at) : 'time unknown';

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
            ? result.goals.map(goal => goal.scorer + ' (' + goalTime(goal.at) + ')').join(', ')
            : hasResult ? 'No goals' : '-';
        document.getElementById('result-away-goals-' + match.id).textContent = result.opponentGoals
            ? events.filter(event => event.opposition).map(event => 'Goal (' + goalTime(event.at) + ')').join(', ')
            : hasResult ? 'No goals' : '-';
        const assists = result.goals.filter(goal => goal.assist);
        document.getElementById('result-assists-' + match.id).textContent = assists.length
            ? assists.map(goal => goal.assist + ' (' + goalTime(goal.at) + ')').join(', ')
            : 'No assists recorded';
        events.sort((a, b) => (a.at ?? Infinity) - (b.at ?? Infinity));
        const timeline = document.getElementById('result-timeline-' + match.id);
        timeline.replaceChildren();
        events.forEach(event => {
            const entry = document.createElement('li');
            entry.className = 'result-event' + (event.opposition ? ' is-opposition' : '');
            const time = document.createElement(event.at === null ? 'span' : 'time');
            time.className = 'result-event-time';
            time.textContent = event.at === null ? 'Time unknown' : clock.format(event.at);
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
