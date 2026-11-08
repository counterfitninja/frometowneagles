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
}

function setup(options = {}) {
    const match = {
        id: 7, opponent: 'Town', hasResult: true,
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
            }
        },
        window: { addEventListener: (name, callback) => { events[name] = callback; } },
        console: { error: (...args) => errors.push(args) },
        Intl, Date
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
        ['14:05:00', '14:10:00', 'Time unknown', 'Time unknown']);
    assert.equal(screen.timeline()[0].children[1].children[0].textContent, 'Town: goal');
    assert.equal(screen.timeline()[1].children[1].children[0].textContent, 'Eagles: Sam');
    assert.equal(screen.timeline()[1].children[1].children[1].textContent, 'Assist: Alex');
    assert.equal(screen.timeline()[1].children[0].dateTime, '2026-11-08T14:10:00.000Z');
    assert.equal(screen.element('result-home-goals-7').textContent, 'Sam (14:10:00), Alex (time unknown)');
    assert.equal(screen.element('result-away-goals-7').textContent, 'Goal (14:05:00), Goal (time unknown)');
    assert.equal(screen.element('result-assists-7').textContent, 'Alex (14:10:00)');
});

test('UK clock times respect daylight saving independently of device timezone', () => {
    const screen = setup({ match: { savedState: {
        goals: [{ scorer: 'Sam', at: Date.parse('2026-07-08T14:05:00Z') }],
        opponentGoals: 0, opponentGoalTimes: []
    } } });
    assert.equal(screen.timeline()[0].children[0].textContent, '15:05:00');
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
