const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const template = fs.readFileSync(path.join(__dirname, '..', 'templates', 'live.html'), 'utf8');
const stateFunctions = template.slice(template.indexOf('    function freshState()'),
    template.indexOf('    function currentFormation()'));

function restore(formations) {
    const saved = { formationIndex: 0, locked: false, formations, subLog: [{ off: 'Old', on: 'New' }] };
    const storage = new Map([['liveMatch_1', JSON.stringify(saved)]]);
    const context = {
        INITIAL_DATA: [{ name: 'Team', players: [{ id: 1 }], subs: [{ id: 2 }], squad: [{ id: 1 }, { id: 2 }] }],
        STATE_KEY: 'liveMatch_1',
        localStorage: {
            getItem: key => storage.get(key),
            setItem: (key, value) => storage.set(key, value)
        }
    };
    vm.runInNewContext('let state;\n' + stateFunctions + '\nloadState(); restored = state;', context);
    return JSON.parse(JSON.stringify(context.restored));
}

test('stale local lineups cannot restore ineligible players in any squad list', () => {
    for (const key of ['players', 'subs', 'squad', 'subbedOff']) {
        const restored = restore([{
            name: 'Cached team', players: [], subs: [], squad: [], subbedOff: [],
            [key]: [{ id: '4', name: 'Retired' }]
        }]);
        assert.equal(restored.formations[0].name, 'Team', key);
        assert.deepEqual(restored.subLog, [], key);
        assert.ok(!JSON.stringify(restored).includes('Retired'), key);
    }
});

test('eligible cached substitutions remain intact, including string player IDs', () => {
    const cached = [{
        name: 'Cached team', players: [{ id: '2' }], subs: [],
        squad: [{ id: 1 }, { id: '2' }], subbedOff: [{ id: 1 }]
    }];
    const restored = restore(cached);
    assert.deepEqual(restored.formations, cached);
    assert.equal(restored.subLog.length, 1);
    assert.equal(restored.locked, false);
});
