const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const script = fs.readFileSync(path.join(__dirname, '..', 'static', 'match-result.js'), 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));

class Element {
    constructor() {
        this.children = [];
        this.textContent = '';
        this.open = false;
        this.hidden = false;
        this.disabled = false;
        this.events = {};
        this.classes = new Set();
        this.classList = {
            toggle: (name, active) => active ? this.classes.add(name) : this.classes.delete(name)
        };
    }
    appendChild(child) { this.children.push(child); }
    append(...children) { this.children.push(...children); }
    replaceChildren() { this.children = []; }
    setAttribute() {}
    addEventListener(name, callback) { this.events[name] = callback; }
    querySelector() { return this.children.find(child => child.tag === 'button'); }
    contains(child) { return this.children.includes(child); }
    showModal() { this.open = true; }
    close() { this.open = false; }
    focus() { this.focused = true; }
}

function setup(options = {}) {
    const config = {
        matchId: 7,
        opponent: 'Town',
        storageKey: 'matchResult_7',
        legacyKeys: ['matchDay_9', 'matchDay_match-7'],
        squad: [
            { id: 1, name: 'Alex', position: 'GK' },
            { id: 2, name: 'Alex', position: 'DEF' },
            { id: 3, name: 'Sam', position: 'MID' }
        ],
        savedState: { goals: [], opponentGoals: 0, motmPlayerId: null },
        ...options.config
    };
    const elements = new Map();
    const getElement = id => {
        if (!elements.has(id)) elements.set(id, new Element());
        return elements.get(id);
    };
    getElement('resultConfig').textContent = JSON.stringify(config);
    const storage = new Map(Object.entries(options.storage || {}));
    const requests = [];
    const windowEvents = {};
    const navigator = { onLine: options.online !== false };
    const errors = [];
    const context = {
        document: {
            getElementById: getElement,
            createElement: tag => Object.assign(new Element(), { tag }),
            activeElement: new Element(),
            addEventListener() {}
        },
        localStorage: {
            getItem: key => storage.get(key) || null,
            setItem: (key, value) => {
                if (options.storageFails) throw new Error('Storage full');
                storage.set(key, value);
            }
        },
        navigator,
        console: { error: (...args) => errors.push(args) },
        confirm: () => options.confirm !== false,
        fetch: async (url, request) => {
            requests.push({ url, body: JSON.parse(request.body) });
            if (options.fetch) return options.fetch(requests.length);
            return { ok: true, json: async () => ({ success: true }) };
        }
    };
    context.window = {
        addEventListener: (event, callback) => { windowEvents[event] = callback; }
    };
    vm.runInNewContext(script, context);
    return {
        api: context.window.matchResult,
        config, elements, storage, requests, errors, navigator, windowEvents,
        element: getElement,
        saved: () => JSON.parse(storage.get(config.storageKey)),
        pick: label => {
            const button = getElement('resultPickerGrid').children.find(child => child.textContent === label);
            assert.ok(button, 'Missing player choice: ' + label);
            button.onclick();
        }
    };
}

test('records duplicate-name scorer and assister by ID, not name', async () => {
    const screen = setup();
    screen.api.chooseScorer();
    screen.pick('Alex · GK #1');
    assert.equal(screen.element('resultPickerTitle').textContent, 'Who assisted?');
    assert.ok(!screen.element('resultPickerGrid').children.some(b => b.textContent === 'Alex · GK #1'));
    screen.pick('Alex · DEF #2');
    await tick();
    assert.equal(screen.requests.length, 1);
    assert.equal(screen.requests[0].body.goals[0].scorer_id, '1');
    assert.equal(screen.requests[0].body.goals[0].assist_id, '2');
    assert.equal(screen.saved().pendingSync, false);
    assert.equal(screen.element('usScore').textContent, 1);
    assert.equal(screen.element('resultPicker').open, false);
});

test('no assist is optional and cancelling records nothing', async () => {
    const screen = setup();
    screen.api.chooseScorer();
    screen.pick('Sam');
    screen.api.closePicker();
    assert.equal(screen.saved().goals.length, 0);
    screen.api.chooseScorer();
    screen.pick('Sam');
    screen.pick('No assist');
    await tick();
    assert.equal(screen.requests[0].body.goals[0].assist_id, null);
    assert.equal(screen.requests[0].body.goals[0].assist, null);
});

test('offline goals survive reload and upload on reconnect', async () => {
    const screen = setup({ online: false });
    screen.api.chooseScorer();
    screen.pick('Sam');
    screen.pick('No assist');
    screen.api.addOpponentGoal();
    assert.equal(screen.requests.length, 0);
    assert.equal(screen.saved().pendingSync, true);
    const reloaded = setup({ online: false, storage: Object.fromEntries(screen.storage) });
    assert.equal(reloaded.element('usScore').textContent, 1);
    assert.equal(reloaded.element('themScore').textContent, 1);
    reloaded.navigator.onLine = true;
    await reloaded.windowEvents.online();
    assert.equal(reloaded.requests.length, 1);
    assert.equal(reloaded.saved().pendingSync, false);
});

test('legacy Match Day state migrates without losing scores or awards', async () => {
    for (const key of ['matchDay_9', 'matchDay_match-7']) {
        const legacy = { goals: [{ scorer: 'Sam', assist: null, at: 5 }], opponentGoals: 2, motmPlayerId: '3' };
        const screen = setup({ storage: { [key]: JSON.stringify(legacy) } });
        await tick();
        assert.equal(screen.requests[0].body.goals[0].scorer_id, '3');
        assert.equal(screen.saved().opponentGoals, 2);
        assert.equal(screen.saved().motmPlayerId, '3');
        assert.equal(screen.storage.get(key), JSON.stringify(legacy));
    }
});

test('uploads are serialized and new changes are sent after the pending request', async () => {
    const pending = [];
    const screen = setup({
        fetch: () => new Promise(resolve => pending.push(resolve))
    });
    screen.api.addOpponentGoal();
    screen.api.addOpponentGoal();
    screen.api.chooseScorer();
    screen.pick('Sam');
    screen.pick('No assist');
    assert.equal(screen.requests.length, 1);
    assert.equal(screen.requests[0].body.opponentGoals, 1);
    pending.shift()({ ok: true, json: async () => ({ success: true }) });
    await tick();
    assert.equal(screen.requests.length, 2);
    assert.equal(screen.requests[1].body.opponentGoals, 2);
    assert.equal(screen.requests[1].body.goals.length, 1);
    pending.shift()({ ok: true, json: async () => ({ success: true }) });
    await tick();
    assert.equal(screen.saved().pendingSync, false);
});

test('upload failures retain pending state and expose a working retry', async () => {
    const screen = setup({
        fetch: async count => ({ ok: count > 1, json: async () => ({ success: true }) })
    });
    screen.api.addOpponentGoal();
    await tick();
    assert.equal(screen.saved().pendingSync, true);
    assert.equal(screen.element('retryResult').hidden, false);
    assert.match(screen.element('resultStatus').textContent, /upload failed/);
    await screen.api.retry();
    assert.equal(screen.saved().pendingSync, false);
    assert.equal(screen.element('retryResult').hidden, true);
});

test('does not treat a login page as a successful save', async () => {
    const screen = setup({
        fetch: async () => ({ ok: true, json: async () => { throw new Error('HTML instead of JSON'); } })
    });
    screen.api.addOpponentGoal();
    await tick();
    assert.equal(screen.saved().pendingSync, true);
    assert.equal(screen.element('retryResult').hidden, false);
});

test('MOTM, removals and result reset affect results, not substitution state', async () => {
    const substitution = JSON.stringify({ subLog: [{ off: 'Alex', on: 'Sam' }] });
    const screen = setup({ storage: { liveMatch_9: substitution } });
    screen.api.chooseMotm();
    screen.pick('Sam');
    await tick();
    assert.equal(screen.saved().motmPlayerId, '3');
    screen.api.chooseScorer();
    screen.pick('Sam');
    screen.pick('No assist');
    await tick();
    screen.element('goalLog').children[0].children[1].onclick();
    await tick();
    assert.equal(screen.saved().goals.length, 0);
    screen.api.addOpponentGoal();
    await tick();
    screen.api.removeOpponentGoal();
    await tick();
    assert.equal(screen.saved().opponentGoals, 0);
    screen.api.reset();
    await tick();
    assert.equal(screen.saved().motmPlayerId, null);
    assert.equal(screen.storage.get('liveMatch_9'), substitution);
});

test('unlinked formation saves locally and never posts to a nonexistent match', async () => {
    const screen = setup({ config: { matchId: null } });
    screen.api.addOpponentGoal();
    await tick();
    assert.equal(screen.requests.length, 0);
    assert.equal(screen.saved().opponentGoals, 1);
    assert.match(screen.element('resultStatus').textContent, /device only/);
});

test('ambiguous legacy names are reported instead of assigning the wrong player', async () => {
    const screen = setup({
        storage: { matchDay_9: JSON.stringify({ goals: [{ scorer: 'Alex' }], opponentGoals: 0 }) }
    });
    await tick();
    assert.equal(screen.requests.length, 0);
    assert.match(screen.element('resultStatus').textContent, /cannot be identified/);
    assert.equal(screen.saved().pendingSync, true);
});

test('unreadable local result is preserved and blocks replacement', () => {
    const screen = setup({ storage: { matchResult_7: '{broken' } });
    assert.equal(screen.storage.get('matchResult_7'), '{broken');
    assert.equal(screen.element('goalButton').disabled, true);
    screen.api.reset();
    assert.equal(screen.storage.get('matchResult_7'), '{broken');
    assert.match(screen.element('resultStatus').textContent, /Cannot restore/);
});

test('storage failure while offline does not claim the result was saved', () => {
    const screen = setup({ online: false, storageFails: true });
    screen.api.addOpponentGoal();
    assert.match(screen.element('resultStatus').textContent, /unable to save/);
    assert.ok(screen.errors.length);
});
