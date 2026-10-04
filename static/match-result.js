(() => {
    'use strict';

    const config = JSON.parse(document.getElementById('resultConfig').textContent);
    const picker = document.getElementById('resultPicker');
    const status = document.getElementById('resultStatus');
    const retry = document.getElementById('retryResult');
    let storageError = false;
    let syncing = false;
    let revision = 0;
    let pendingScorer = null;
    let pickerTrigger = null;
    let playerError = '';

    function readState() {
        for (const key of [config.storageKey, ...config.legacyKeys]) {
            let raw;
            try {
                raw = localStorage.getItem(key);
            } catch (error) {
                storageError = true;
                console.error('Cannot read the saved match result', error);
                break;
            }
            if (!raw) continue;
            try {
                const saved = JSON.parse(raw);
                if (!Array.isArray(saved.goals) || !Number.isInteger(saved.opponentGoals)
                    || saved.opponentGoals < 0) throw new Error('Invalid saved result');
                return { ...saved, pendingSync: key !== config.storageKey || Boolean(saved.pendingSync) };
            } catch (error) {
                storageError = true;
                console.error('Cannot restore the saved match result', error);
                // Do not replace an unreadable local result with a success-shaped empty result.
                document.getElementById('goalButton').disabled = true;
                document.getElementById('opponentGoalButton').disabled = true;
                return null;
            }
        }
        return { ...config.savedState, pendingSync: false };
    }

    let result = readState();

    function setStatus(message, isError = false, canRetry = false) {
        status.textContent = message;
        status.classList.toggle('error', isError);
        retry.hidden = !canRetry;
    }

    function persist() {
        try {
            localStorage.setItem(config.storageKey, JSON.stringify(result));
            storageError = false;
        } catch (error) {
            storageError = true;
            console.error('Cannot save the match result on this device', error);
        }
    }

    function playerForGoal(goal, role) {
        const id = goal[role + '_id'];
        if (id != null) return config.squad.find(player => String(player.id) === String(id));
        const matches = config.squad.filter(player => player.name === goal[role]);
        return matches.length === 1 ? matches[0] : null;
    }

    function payload() {
        return {
            goals: result.goals.map(goal => {
                const scorer = playerForGoal(goal, 'scorer');
                const assist = playerForGoal(goal, 'assist');
                const scorerId = goal.scorer_id || (scorer && scorer.id);
                const assistId = goal.assist_id || (assist && assist.id);
                if (!scorerId || (goal.assist && !assistId)) {
                    playerError = 'A saved player cannot be identified. Remove and re-enter that goal to save it.';
                    throw new Error(playerError);
                }
                return {
                    ...goal,
                    scorer_id: String(scorerId),
                    assist_id: assistId ? String(assistId) : null
                };
            }),
            opponentGoals: result.opponentGoals,
            motmPlayerId: result.motmPlayerId || null
        };
    }

    async function sync() {
        if (!result || syncing) return;
        if (!config.matchId) {
            setStatus(storageError ? 'Cannot save on this device. Keep this screen open.'
                : 'Saved on this device only. Link this formation to a match to save season stats.', storageError);
            return;
        }
        if (!navigator.onLine) {
            setStatus(storageError ? 'Offline and unable to save on this device. Keep this screen open.'
                : 'Offline - saved on this device. Will upload when connected.', storageError);
            return;
        }
        if (!result.pendingSync) {
            setStatus(storageError ? 'Saved to the club, but not on this device.'
                : 'Result saved', storageError);
            return;
        }
        syncing = true;
        playerError = '';
        try {
            // Serialize uploads so an older request cannot overwrite a newer goal.
            while (result.pendingSync) {
                const sentRevision = revision;
                setStatus('Saving result...');
                const response = await fetch('/api/matches/' + config.matchId + '/result', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload())
                });
                if (!response.ok) throw new Error('Result upload failed');
                const body = await response.json();
                if (!body.success) throw new Error(body.error || 'Result upload failed');
                if (revision === sentRevision) {
                    result.pendingSync = false;
                    persist();
                }
            }
            setStatus(storageError ? 'Saved to the club, but not on this device.'
                : 'Result saved', storageError);
        } catch (error) {
            console.error('Cannot upload the match result', error);
            setStatus(
                playerError || (storageError ? 'Result not saved. Keep this screen open and retry.'
                    : 'Saved on this device, but upload failed. Check your connection or login and retry.'),
                true, true
            );
        } finally {
            syncing = false;
        }
    }

    function save() {
        revision += 1;
        result.pendingSync = true;
        persist();
        render();
        sync();
    }

    function closeMore() {
        document.getElementById('liveMore').open = false;
    }

    function render() {
        document.getElementById('usScore').textContent = result.goals.length;
        document.getElementById('themScore').textContent = result.opponentGoals;
        document.getElementById('goalLogSummary').textContent = 'Goals and assists · ' + result.goals.length;
        const motm = config.squad.find(player => String(player.id) === String(result.motmPlayerId));
        document.getElementById('motmButton').textContent = motm
            ? 'Man of the match: ' + motm.name : 'Choose man of the match';
        const log = document.getElementById('goalLog');
        log.replaceChildren();
        if (!result.goals.length) {
            const empty = document.createElement('p');
            empty.className = 'empty-goals';
            empty.textContent = 'Tap Goal! to record the scorer and assist.';
            log.appendChild(empty);
        }
        result.goals.forEach((goal, index) => {
            const entry = document.createElement('div');
            entry.className = 'goal-entry';
            const text = document.createElement('p');
            const scorer = document.createElement('strong');
            scorer.textContent = (index + 1) + '. ' + goal.scorer;
            const assist = document.createElement('span');
            assist.textContent = goal.assist ? 'Assist: ' + goal.assist : 'No assist';
            text.append(scorer, assist);
            const remove = document.createElement('button');
            remove.type = 'button';
            remove.textContent = 'Remove';
            remove.setAttribute('aria-label', 'Remove goal ' + (index + 1) + ' by ' + goal.scorer);
            remove.onclick = () => {
                if (!confirm('Remove this goal?')) return;
                result.goals.splice(index, 1);
                save();
            };
            entry.append(text, remove);
            log.appendChild(entry);
        });
    }

    function showPicker(title, onPick, emptyLabel = null, excludedId = null) {
        if (!picker.open) {
            const more = document.getElementById('liveMore');
            pickerTrigger = more.contains(document.activeElement)
                ? more.querySelector('summary') : document.activeElement;
        }
        closeMore();
        document.getElementById('resultPickerTitle').textContent = title;
        const grid = document.getElementById('resultPickerGrid');
        grid.replaceChildren();
        const addChoice = (label, player, wide = false) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.textContent = label;
            if (wide) button.className = 'wide';
            button.onclick = () => onPick(player);
            grid.appendChild(button);
        };
        if (emptyLabel) addChoice(emptyLabel, null, true);
        config.squad.forEach(player => {
            if (String(player.id) === String(excludedId)) return;
            const duplicate = config.squad.some(other => other.id !== player.id && other.name === player.name);
            addChoice(player.name + (duplicate ? ' · ' + (player.position || 'Player') + ' #' + player.id : ''), player);
        });
        if (!grid.children.length) {
            const empty = document.createElement('p');
            empty.textContent = 'No players available. Add players or plan the team first.';
            grid.appendChild(empty);
        }
        if (!picker.open) picker.showModal();
        const firstButton = grid.querySelector('button');
        if (firstButton) firstButton.focus();
    }

    function closePicker() {
        picker.close();
        pendingScorer = null;
        if (pickerTrigger) pickerTrigger.focus();
    }

    window.matchResult = {
        chooseScorer() {
            if (!result) return;
            pendingScorer = null;
            showPicker('Who scored?', scorer => {
                pendingScorer = scorer;
                showPicker('Who assisted?', assist => {
                    result.goals.push({
                        scorer_id: String(pendingScorer.id),
                        scorer: pendingScorer.name,
                        assist_id: assist ? String(assist.id) : null,
                        assist: assist ? assist.name : null,
                        at: Date.now()
                    });
                    closePicker();
                    save();
                }, 'No assist', scorer.id);
            });
        },
        chooseMotm() {
            if (!result) return;
            showPicker('Man of the match', player => {
                result.motmPlayerId = player ? String(player.id) : null;
                closePicker();
                save();
            }, 'No award');
        },
        addOpponentGoal() {
            if (!result) return;
            result.opponentGoals += 1;
            save();
        },
        removeOpponentGoal() {
            closeMore();
            if (!result || !result.opponentGoals) return;
            if (!confirm('Remove an opponent goal?')) return;
            result.opponentGoals -= 1;
            save();
        },
        reset() {
            closeMore();
            if (!result || !confirm('Clear the score, goals, assists and man of the match? Substitutions will not change.')) return;
            result = { goals: [], opponentGoals: 0, motmPlayerId: null, pendingSync: true };
            save();
        },
        async share() {
            closeMore();
            if (!result) return;
            let text = 'Eagles ' + result.goals.length + ' - ' + result.opponentGoals + ' ' + config.opponent;
            result.goals.forEach(goal => {
                text += '\n' + goal.scorer + (goal.assist ? ' (assist: ' + goal.assist + ')' : '');
            });
            const motm = config.squad.find(player => String(player.id) === String(result.motmPlayerId));
            if (motm) text += '\nMan of the match: ' + motm.name;
            try {
                if (navigator.share) await navigator.share({ text });
                else {
                    await navigator.clipboard.writeText(text);
                    setStatus('Result copied');
                }
            } catch (error) {
                if (error.name !== 'AbortError') setStatus('Could not share the result. Try again.', true);
            }
        },
        closePicker,
        retry: sync
    };

    picker.addEventListener('cancel', () => { pendingScorer = null; });
    document.addEventListener('click', event => {
        const more = document.getElementById('liveMore');
        if (!more.contains(event.target)) more.open = false;
        else if (event.target.closest('.live-more-actions button')) more.open = false;
    });
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape') closeMore();
    });
    window.addEventListener('online', sync);
    window.addEventListener('offline', sync);
    if (!result) {
        setStatus('Cannot restore the saved result on this device. Do not clear browser data; use another device to check the saved result.', true);
        return;
    }
    persist();
    render();
    sync();
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('/static/sw.js', { scope: '/' }).catch(error => {
            console.error('Cannot enable offline page caching', error);
        });
    }
})();
