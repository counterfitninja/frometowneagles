const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const template = fs.readFileSync(path.join(__dirname, '..', 'templates', 'live.html'), 'utf8');
const script = template.slice(template.indexOf('    const FORMATION_ID'),
    template.indexOf('    // \u2500\u2500 INIT'));

class Element {
    constructor() {
        this.children = [];
        this.events = {};
        this.attributes = {};
        this.style = {};
        this.dataset = {};
        this.className = '';
        this.classList = {
            add: name => this.classList.toggle(name, true),
            remove: name => this.classList.toggle(name, false),
            toggle: (name, active) => {
                const classes = new Set(this.className.split(' ').filter(Boolean));
                if (active) classes.add(name);
                else classes.delete(name);
                this.className = [...classes].join(' ');
            },
            contains: name => this.className.split(' ').includes(name)
        };
    }
    set innerHTML(value) { this.children = []; this.content = value; }
    get innerHTML() { return this.content || ''; }
    set textContent(value) { this.children = []; this.text = String(value); }
    get textContent() { return (this.text || '') + this.children.map(c => c.textContent).join(''); }
    appendChild(child) { this.children.push(child); }
    setAttribute(name, value) { this.attributes[name] = String(value); }
    addEventListener(name, callback) { this.events[name] = callback; }
    setPointerCapture() {}
}

const alex = { id: 1, name: 'Alex', position: 'DEF', xPercent: 30, yPercent: 40 };
const otherAlex = { id: 2, name: 'Alex', position: 'MID' };
const sam = { id: 3, name: 'Sam', xPercent: 70, yPercent: 50 };
const formations = [{
    name: 'First half', players: [alex, sam], subs: [otherAlex],
    squad: [alex, otherAlex, sam]
}, {
    name: 'Second half', players: [alex, otherAlex], subs: [sam],
    squad: [alex, otherAlex, sam]
}];

function setup(saved, initial = formations) {
    const elements = new Map();
    const element = id => {
        if (!elements.has(id)) elements.set(id, new Element());
        return elements.get(id);
    };
    const storage = new Map(saved ? [['liveMatch_1', saved]] : []);
    const requests = [];
    const alerts = [];
    const context = {
        document: {
            getElementById: element,
            createElement: () => new Element(),
            querySelectorAll: selector => {
                const match = selector.match(/^#(\w+) \.modal-player-btn$/);
                return match ? element(match[1]).children : [];
            },
            querySelector: selector => {
                const match = selector.match(/^#(\w+) \.modal-player-btn\[data-idx="(\d+)"\]$/);
                return match ? element(match[1]).children[Number(match[2])] : null;
            }
        },
        localStorage: {
            getItem: key => storage.get(key),
            setItem: (key, value) => storage.set(key, value)
        },
        alert: message => alerts.push(message),
        confirm: () => true,
        setTimeout() {},
        fetch: async (url, request) => {
            requests.push(JSON.parse(request.body));
            return { ok: true };
        }
    };
    vm.createContext(context);
    vm.runInContext(script.replace('{{ formation_id | tojson }}', '1')
        .replace('{{ formation_name | tojson }}', '"Teams"')
        .replace('{{ formations | tojson }}', JSON.stringify(initial)) +
        '\nloadState(); render();', context);
    return {
        api: context, element, storage, requests, alerts,
        state: () => JSON.parse(vm.runInContext('JSON.stringify(state)', context)),
        count: player => context.timesSubbedOff(player),
        swap: (off, on) => {
            context.openSubModal(off);
            context.selectOn(on);
            context.confirmSub();
        }
    };
}

test('double-click and keyboard open the locked pitch picker without recording until confirmed', () => {
    const screen = setup();
    const icon = screen.element('pitchPlayers').children[0];
    assert.equal(screen.state().locked, true);
    assert.equal(icon.attributes.role, 'button');
    assert.equal(icon.tabIndex, 0);
    icon.events.dblclick();
    assert.equal(screen.element('subModal').classList.contains('hidden'), false);
    assert.equal(screen.element('modalOffList').children[0].classList.contains('sel-off'), true);
    assert.equal(screen.element('confirmSubBtn').disabled, true);
    assert.equal(screen.count(alex), 0);
    screen.api.closeSubModal();
    assert.equal(screen.state().subLog.length, 0);
    for (const key of ['Enter', ' ']) {
        let prevented = false;
        screen.element('pitchPlayers').children[1].events.keydown({
            key, preventDefault: () => { prevented = true; }
        });
        assert.equal(prevented, true);
        assert.equal(screen.element('modalOffList').children[1].classList.contains('sel-off'), true);
        screen.api.closeSubModal();
    }
});

test('rolling substitutions count outgoing players by ID, show badges and preserve pitch positions', () => {
    const screen = setup();
    screen.swap(0, 0);
    assert.equal(screen.count(alex), 1);
    assert.equal(screen.count(otherAlex), 0);
    assert.equal(screen.element('benchPlayers').children[0].children[1].textContent, '1');
    assert.equal(screen.element('subBtn').disabled, false);
    assert.deepEqual(screen.state().formations[0].subbedOff.map(p => p.id), [1]);
    assert.equal(screen.state().formations[0].players[0].xPercent, 30);
    assert.equal(screen.state().formations[0].players[0].yPercent, 40);

    screen.swap(0, 0);
    assert.equal(screen.element('pitchPlayers').children[0].children[1].textContent, '1');
    assert.deepEqual(screen.state().formations[0].subbedOff.map(p => p.id), [2]);
    screen.swap(0, 0);
    assert.equal(screen.count(alex), 2);
    assert.equal(screen.count(otherAlex), 1);
    assert.equal(screen.element('benchPlayers').children[0].children[1].textContent, '2');
    assert.equal(screen.element('subTally').textContent, '3 subs');
    assert.equal(screen.state().subLog[0].offId, 1);
    assert.equal(screen.state().subLog[0].onId, 2);
    const savedFormation = JSON.parse(screen.requests[2].data).formations[0];
    assert.deepEqual(savedFormation.subs.map(p => p.id), [1]);
    assert.deepEqual(savedFormation.squad.map(p => p.id), [1, 2, 3]);
    assert.ok(!JSON.stringify(savedFormation).includes('subbedIn'));
    assert.equal(screen.alerts.length, 0);
});

test('saved lineups keep outgoing players on the bench when opened without local state', () => {
    const screen = setup();
    screen.swap(0, 0);
    const saved = JSON.parse(screen.requests[0].data).formations;
    const reopened = setup(undefined, saved);
    assert.equal(reopened.element('subBtn').disabled, false);
    reopened.swap(0, 0);
    assert.deepEqual(reopened.state().formations[0].players.map(p => p.id), [1, 3]);
    assert.deepEqual(reopened.state().formations[0].subbedOff.map(p => p.id), [2]);
    assert.equal(reopened.alerts.length, 0);
});

test('picker includes both unused and previously substituted bench players without duplicates', () => {
    const screen = setup(undefined, [{
        name: 'Team', players: [alex], subs: [otherAlex, sam], squad: [alex, otherAlex, sam]
    }]);
    screen.swap(0, 0);
    screen.api.openSubModal(0);
    assert.equal(screen.element('modalOnList').children.length, 2);
    screen.swap(0, 1);
    assert.deepEqual(screen.state().formations[0].players.map(p => p.id), [1]);
    assert.deepEqual(screen.state().formations[0].subs.map(p => p.id), [3]);
    assert.deepEqual(screen.state().formations[0].subbedOff.map(p => p.id), [2]);
});

test('counts survive reloads and formation changes, including ID type differences, and reset separately', () => {
    const screen = setup();
    screen.swap(0, 0);
    const restored = setup(screen.storage.get('liveMatch_1'));
    assert.equal(restored.count({ ...alex, id: '1' }), 1);
    restored.api.switchFormation(1);
    assert.equal(restored.element('pitchPlayers').children[0].children[1].textContent, '1');
    restored.api.confirmFullSwitch(0);
    assert.equal(restored.count(alex), 2);
    restored.storage.set('matchResult_1', '{"goals":[{"scorer_id":"1"}]}');
    restored.api.doReset();
    assert.equal(restored.count(alex), 0);
    assert.equal(restored.element('pitchPlayers').children[0].children.length, 1);
    assert.equal(restored.element('subTally').textContent, '0 subs');
    assert.equal(restored.storage.get('matchResult_1'), '{"goals":[{"scorer_id":"1"}]}');
});

test('legacy name-only logs still display counts and an empty bench cannot record a sub', () => {
    const screen = setup();
    const cached = screen.state();
    cached.subLog = [{ off: 'Sam', on: 'Alex', fi: 0, time: '12:00' }];
    const restored = setup(JSON.stringify(cached));
    assert.equal(restored.count(sam), 1);
    assert.equal(restored.element('pitchPlayers').children[1].children[1].textContent, '1');

    const empty = setup(undefined, [{ name: 'Team', players: [alex], subs: [], squad: [alex] }]);
    assert.equal(empty.element('subBtn').disabled, true);
    empty.element('pitchPlayers').children[0].events.dblclick();
    assert.equal(empty.alerts.length, 1);
    assert.equal(empty.state().subLog.length, 0);
});

test('unlocked single-tap emergency substitutions still work', () => {
    const screen = setup();
    screen.api.toggleLock();
    const icon = screen.element('pitchPlayers').children[0];
    icon.events.pointerdown({ clientX: 10, clientY: 10, pointerId: 1 });
    icon.events.pointerup({ clientX: 10, clientY: 10 });
    assert.equal(screen.element('modalOffList').children[0].classList.contains('sel-off'), true);
    assert.equal(screen.count(alex), 0);
});
