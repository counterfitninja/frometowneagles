const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const script = fs.readFileSync(path.join(__dirname, '..', 'static', 'results.js'), 'utf8');

class Element {
    constructor() {
        this.children = [];
        this.text = '';
        this.hidden = false;
        this.classes = new Set();
        this.classList = { toggle: (name, active) => active ? this.classes.add(name) : this.classes.delete(name) };
    }
    append(...children) { this.children.push(...children); }
    appendChild(child) { this.children.push(child); }
    replaceChildren() { this.children = []; this.text = ''; }
    get textContent() { return this.text + this.children.map(child => child.textContent).join(''); }
    set textContent(value) { this.text = String(value); this.children = []; }
    querySelector() {
        if (!this.button) this.button = new Element();
        return this.button;
    }
}

function setup(options = {}) {
    const match = {
        id: 7, match_date: '2026-11-08', opponent: 'Town', hasResult: true,
        storageKey: 'matchResult_7', legacyKeys: ['matchDay_match-7', 'matchDay_9'],
        savedState: { goals: [], opponentGoals: 0, opponentGoalTimes: [], motmPlayerId: null },
        ...options.match
    };
    const storage = new Map(Object.entries(options.storage || {}));
    const elements = new Map();
    const element = id => {
        if (!elements.has(id)) elements.set(id, new Element());
        return elements.get(id);
    };
    element('resultsConfig').textContent = JSON.stringify([match]);
    const events = {};
    const errors = [];
    vm.runInNewContext(script, {
        document: { getElementById: element, createElement: tag => Object.assign(new Element(), { tag }) },
        localStorage: {
            getItem: key => {
                if (options.storageFails) throw new Error('Storage unavailable');
                return storage.get(key) || null;
            },
            setItem: (key, value) => storage.set(key, value)
        },
        window: { addEventListener: (name, callback) => { events[name] = callback; } },
        console: { error: (...args) => errors.push(args) },
        Intl, Date,
        navigator: { onLine: options.online !== false },
        fetch: async (url, request) => options.fetch
            ? options.fetch(url, JSON.parse(request.body))
            : { ok: true, json: async () => ({
                success: true, result: { ...match.savedState, opponentGoalTimes: JSON.parse(request.body).times }
            }) }
    });
    return { element, events, errors, storage, timeline: () => element('result-timeline-7').children };
}

test('shows both teams in timestamp order, scorer and assist, then unknown times', () => {
    const screen = setup({
        match: { savedState: {
            goals: [
                { scorer: 'Sam', assist: 'Alex', at: Date.parse('2026-11-08T14:10:00Z') },
                { scorer: 'Alex', assist: null, at: null }
            ],
            opponentGoals: 2,
            opponentGoalTimes: [Date.parse('2026-11-08T14:05:00Z'), null]
        } }
    });
    assert.equal(screen.element('result-score-7').textContent, '2 : 2');
    assert.deepEqual(screen.timeline().map(row => row.children[0].textContent),
        ['5 min', '10 min', 'Time unknown', 'Time unknown']);
    assert.equal(screen.timeline()[0].children[1].children[0].textContent, 'Town: goal');
    assert.equal(screen.timeline()[1].children[1].children[0].textContent, 'Eagles: Sam');
    assert.equal(screen.timeline()[1].children[1].children[1].textContent, 'Assist: Alex');
    assert.equal(screen.timeline()[1].children[0].dateTime, '2026-11-08T14:10:00.000Z');
    assert.equal(screen.element('result-home-goals-7').textContent, 'Sam (10 min), Alex (time unknown)');
    assert.equal(screen.element('result-away-goals-7').textContent, 'Goal (5 min), Goal (time unknown)');
    assert.equal(screen.element('result-assists-7').textContent, 'Alex (10 min)');
});

test('UK clock times respect daylight saving independently of device timezone', () => {
    const screen = setup({ match: { match_date: '2026-07-08', savedState: {
        goals: [{ scorer: 'Sam', at: Date.parse('2026-07-08T14:05:00Z') }],
        opponentGoals: 0, opponentGoalTimes: []
    } } });
    assert.equal(screen.timeline()[0].children[0].textContent, '55 min');
});

test('game minutes use whole elapsed minutes from 2pm and flag pre-kickoff timestamps', () => {
    const screen = setup({ match: { savedState: {
        goals: [
            { scorer: 'Early', at: Date.parse('2026-11-08T13:59:59Z') },
            { scorer: 'Kick-off', at: Date.parse('2026-11-08T14:00:00Z') },
            { scorer: 'First', at: Date.parse('2026-11-08T14:00:59Z') },
            { scorer: 'Next', at: Date.parse('2026-11-08T14:01:00Z') }
        ], opponentGoals: 0, opponentGoalTimes: []
    } } });
    assert.deepEqual(screen.timeline().map(row => row.children[0].textContent),
        ['before kick-off', '0 min', '0 min', '1 min']);
});

test('35-minute halves exclude the 10-minute break and flag out-of-play timestamps', () => {
    for (const date of ['2026-11-08', '2026-07-08']) {
        const offset = date.includes('-07-') ? '+01:00' : 'Z';
        const times = ['14:34:59', '14:35:00', '14:44:59', '14:45:00',
            '14:50:00', '15:19:59', '15:20:00', '15:20:01'];
        const screen = setup({ match: {
            match_date: date,
            savedState: {
                goals: times.map(time => ({ scorer: 'Sam', assist: 'Alex', at: Date.parse(date + 'T' + time + offset) })),
                opponentGoals: times.length,
                opponentGoalTimes: times.map(time => Date.parse(date + 'T' + time + offset))
            }
        } });
        const expected = ['34 min', 'half-time', 'half-time', '35 min',
            '40 min', '69 min', '70 min', 'after full-time'];
        assert.deepEqual(screen.timeline().filter(row => !row.className.includes('is-opposition'))
            .map(row => row.children[0].textContent), expected);
        assert.deepEqual(screen.timeline().filter(row => row.className.includes('is-opposition'))
            .map(row => row.children[0].textContent), expected);
        assert.match(screen.element('result-assists-7').textContent, /Alex \(40 min\)/);
    }
});

test('saved goalless draws differ from fixtures without a result', () => {
    const saved = setup();
    assert.equal(saved.element('result-score-7').textContent, '0 : 0');
    assert.equal(saved.timeline()[0].textContent, 'No goals recorded.');
    const missing = setup({ match: { hasResult: false } });
    assert.equal(missing.element('result-score-7').textContent, 'Not recorded');
    assert.equal(missing.timeline().length, 0);
});

test('unsynced local goals and timestamps override the server without uploading or modifying storage', () => {
    const raw = JSON.stringify({
        goals: [{ scorer: 'Local player', at: 1000 }], opponentGoals: 1,
        opponentGoalTimes: [2000], pendingSync: true
    });
    const screen = setup({ storage: { matchResult_7: raw } });
    assert.equal(screen.element('result-score-7').textContent, '1 : 1');
    assert.match(screen.element('result-source-7').textContent, /Saved on this device/);
    assert.equal(screen.timeline()[1].children[0].dateTime, '1970-01-01T00:00:02.000Z');
    assert.equal(screen.storage.get('matchResult_7'), raw);
});

test('old synced local state never replaces newer server timestamps', () => {
    const screen = setup({
        match: { savedState: { goals: [], opponentGoals: 1, opponentGoalTimes: [2000] } },
        storage: { matchResult_7: JSON.stringify({ goals: [], opponentGoals: 0, pendingSync: false }) }
    });
    assert.equal(screen.element('result-score-7').textContent, '0 : 1');
    assert.equal(screen.timeline()[0].children[0].dateTime, '1970-01-01T00:00:02.000Z');
});

test('merely opening a live match does not turn an unrecorded fixture into a 0-0', () => {
    const screen = setup({
        match: { hasResult: false },
        storage: { matchResult_7: JSON.stringify({ goals: [], opponentGoals: 0, pendingSync: false }) }
    });
    assert.equal(screen.element('result-score-7').textContent, 'Not recorded');
});

test('legacy local opposition counts are shown without invented times', () => {
    const screen = setup({
        match: { hasResult: false },
        storage: { 'matchDay_match-7': JSON.stringify({ goals: [], opponentGoals: 2 }) }
    });
    assert.equal(screen.element('result-score-7').textContent, '0 : 2');
    assert.deepEqual(screen.timeline().map(row => row.children[0].textContent), ['Time unknown', 'Time unknown']);
});

test('corrupted or unavailable local storage reports an error and still shows server results', () => {
    for (const options of [
        { storage: { matchResult_7: '{broken' } },
        { storage: { matchResult_7: JSON.stringify({ goals: [], opponentGoals: 1, opponentGoalTimes: [] }) } },
        { storageFails: true }
    ]) {
        const screen = setup(options);
        assert.equal(screen.element('result-error-7').hidden, false);
        assert.match(screen.element('result-error-7').textContent, /Cannot read/);
        assert.equal(screen.element('result-score-7').textContent, '0 : 0');
        assert.equal(screen.errors.length, 1);
    }
});

test('goals and opponent names are rendered as text, never as HTML', () => {
    const name = '<img src=x onerror=alert(1)>';
    const screen = setup({ match: {
        opponent: name,
        savedState: { goals: [{ scorer: name, assist: name, at: 1000 }], opponentGoals: 1, opponentGoalTimes: [2000] }
    } });
    assert.equal(screen.timeline()[0].children[1].children[0].textContent, 'Eagles: ' + name);
    assert.equal(screen.timeline()[1].children[1].children[0].textContent, name + ': goal');
});

test('storage changes refresh unsynced device results', () => {
    const screen = setup();
    screen.storage.set('matchResult_7', JSON.stringify({
        goals: [], opponentGoals: 1, opponentGoalTimes: [2000], pendingSync: true
    }));
    screen.events.storage();
    assert.equal(screen.element('result-score-7').textContent, '0 : 1');
});

test('historical minute edits save without changing score and update device cache', async () => {
    const screen = setup({ match: { savedState: {
        goals: [], opponentGoals: 2, opponentGoalTimes: [null, null], motmPlayerId: null
    } } });
    const fields = screen.element('result-time-fields-7').children;
    fields[0].children[0].value = '40';
    fields[1].children[0].value = '';
    await screen.element('result-times-form-7').onsubmit({ preventDefault() {} });
    assert.equal(screen.element('result-away-goals-7').textContent, 'Goal (40 min), Goal (time unknown)');
    assert.equal(screen.element('result-times-status-7').textContent, 'Goal times saved.');
    const saved = JSON.parse(screen.storage.get('matchResult_7'));
    assert.deepEqual(saved.opponentGoalTimes, [Date.parse('2026-11-08T14:50:00Z'), null]);
    assert.equal(saved.opponentGoals, 2);
});

test('historical summer minute edits use UK daylight saving', async () => {
    const screen = setup({ match: {
        match_date: '2026-07-08', savedState: { goals: [], opponentGoals: 1, opponentGoalTimes: [null] }
    } });
    screen.element('result-time-fields-7').children[0].children[0].value = '40';
    await screen.element('result-times-form-7').onsubmit({ preventDefault() {} });
    assert.equal(JSON.parse(screen.storage.get('matchResult_7')).opponentGoalTimes[0],
        Date.parse('2026-07-08T13:50:00Z'));
});

test('invalid minutes are rejected without saving', async () => {
    for (const value of ['-1', '71', '1.5', '14:30', 'abc']) {
        const screen = setup({ match: {
            savedState: { goals: [], opponentGoals: 1, opponentGoalTimes: [null] }
        } });
        screen.element('result-time-fields-7').children[0].children[0].value = value;
        await screen.element('result-times-form-7').onsubmit({ preventDefault() {} });
        assert.match(screen.element('result-times-status-7').textContent, /whole match minute/);
        assert.equal(screen.storage.has('matchResult_7'), false);
    }
});

test('offline edits and conflicts retain entries and report errors', async () => {
    for (const options of [
        { online: false },
        { fetch: async () => ({ ok: false, status: 409 }) }
    ]) {
        const screen = setup({ ...options, match: { savedState: {
            goals: [], opponentGoals: 1, opponentGoalTimes: [null]
        } } });
        const input = screen.element('result-time-fields-7').children[0].children[0];
        input.value = '40';
        await screen.element('result-times-form-7').onsubmit({ preventDefault() {} });
        assert.equal(input.value, '40');
        assert.match(screen.element('result-times-status-7').textContent, /Reconnect|result changed/);
        assert.equal(screen.storage.has('matchResult_7'), false);
    }
});

test('minute conversion round trips half boundaries and timeline sorts unsorted goal entries', async () => {
    const minutes = [70, 35, 0, 34, 40];
    const screen = setup({ match: { savedState: {
        goals: [{ scorer: 'Sam', at: Date.parse('2026-11-08T14:48:00Z') }],
        opponentGoals: minutes.length, opponentGoalTimes: minutes.map(() => null)
    } } });
    screen.element('result-time-fields-7').children.forEach((label, index) => {
        label.children[0].value = String(minutes[index]);
    });
    await screen.element('result-times-form-7').onsubmit({ preventDefault() {} });
    assert.deepEqual(screen.element('result-time-fields-7').children.map(label => label.children[0].value),
        minutes.map(String));
    assert.deepEqual(screen.timeline().map(row => row.children[0].textContent),
        ['0 min', '34 min', '35 min', '38 min', '40 min', '70 min']);
    assert.equal(screen.element('result-away-goals-7').textContent,
        'Goal (0 min), Goal (34 min), Goal (35 min), Goal (40 min), Goal (70 min)');
});

test('unchanged minute fields preserve original seconds and timestamps outside playing time', async () => {
    const times = [
        Date.parse('2026-11-08T14:50:45Z'),
        Date.parse('2026-11-08T14:40:00Z')
    ];
    const screen = setup({ match: { savedState: {
        goals: [], opponentGoals: 2, opponentGoalTimes: times
    } } });
    assert.equal(screen.element('result-time-fields-7').children[0].children[0].value, '40');
    assert.equal(screen.element('result-time-fields-7').children[1].children[0].value, '');
    await screen.element('result-times-form-7').onsubmit({ preventDefault() {} });
    assert.deepEqual(JSON.parse(screen.storage.get('matchResult_7')).opponentGoalTimes, times);
});
