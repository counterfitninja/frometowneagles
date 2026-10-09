const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const script = fs.readFileSync(path.join(__dirname, '..', 'static', 'sw.js'), 'utf8');
const origin = 'https://eagles.test';

function response(text, redirected = false) {
    let consumed = false;
    return {
        status: 200, type: 'basic', redirected,
        clone() {
            if (consumed) throw new Error('Response body is already used');
            return response(text, redirected);
        },
        text: async () => { consumed = true; return text; }
    };
}

function setup(options = {}) {
    const handlers = {};
    const cached = new Map(Object.entries(options.cached || {}));
    const precached = [];
    let calls = 0;
    const context = {
        URL, Response, console,
        Request: class {
            constructor(url) { this.url = new URL(url, origin).href; }
        },
        self: {
            location: { origin },
            addEventListener: (name, callback) => { handlers[name] = callback; },
            skipWaiting() {},
            clients: { claim() {} }
        },
        caches: {
            match: async request => cached.get(typeof request === 'string' ? request : request.url),
            open: async () => ({
                put: async (request, value) => { cached.set(request.url, value); },
                addAll: async requests => { precached.push(...requests.map(request => request.url)); }
            })
        },
        fetch: async () => {
            calls += 1;
            if (options.offline) throw new Error('Offline');
            return options.response || response('Fresh page');
        }
    };
    vm.runInNewContext(script, context);
    return {
        cached, precached, handlers, calls: () => calls,
        async request(pathname, mode = 'navigate', method = 'GET') {
            let result;
            const work = [];
            const request = { url: origin + pathname, mode, method, clone() { return this; } };
            handlers.fetch({
                request,
                respondWith: value => {
                    result = options.consumeImmediately
                        ? value.then(response => { response.text(); return response; }) : value;
                },
                waitUntil: value => { work.push(value); }
            });
            const value = await result;
            await Promise.all(work);
            return value;
        }
    };
}

test('online match navigation fetches fresh server data instead of cached results', async () => {
    const worker = setup({ cached: { [origin + '/matches/1/live']: response('Old result') } });
    assert.equal(await (await worker.request('/matches/1/live')).text(), 'Fresh page');
    assert.equal(worker.calls(), 1);
    assert.equal(await worker.cached.get(origin + '/matches/1/live').text(), 'Fresh page');
});

test('offline navigation restores the exact previously opened match', async () => {
    const worker = setup({ offline: true, cached: { [origin + '/matches/1/live']: response('Saved match') } });
    assert.equal(await (await worker.request('/matches/1/live')).text(), 'Saved match');
    const missing = await worker.request('/matches/2/live');
    assert.equal(missing.status, 503);
    assert.match(await missing.text(), /Page unavailable offline/);
});

test('clones the network response before the browser consumes its body', async () => {
    const worker = setup({ consumeImmediately: true });
    await worker.request('/matches/1/live');
    assert.ok(worker.cached.has(origin + '/matches/1/live'));
});

test('login redirects cannot replace cached manager pages', async () => {
    const old = response('Saved match');
    const worker = setup({
        cached: { [origin + '/matches/1/live']: old },
        response: response('Login page', true)
    });
    await worker.request('/matches/1/live');
    assert.equal(worker.cached.get(origin + '/matches/1/live'), old);
});

test('API, authentication and uploads always bypass the offline cache', async () => {
    const worker = setup();
    for (const pathname of ['/api/matches/1/result', '/login', '/logout', '/players/absence']) {
        assert.equal(await worker.request(pathname), undefined);
    }
    assert.equal(await worker.request('/api/matches/1/result', 'cors', 'POST'), undefined);
    assert.equal(worker.calls(), 0);
});

test('static assets use the cache and the live bundle is precached', async () => {
    const worker = setup({ cached: { [origin + '/static/match-result.js']: response('Cached script') } });
    assert.equal(await (await worker.request('/static/match-result.js', 'cors')).text(), 'Cached script');
    assert.equal(worker.calls(), 0);
    let installed;
    worker.handlers.install({ waitUntil: value => { installed = value; } });
    await installed;
    assert.ok(worker.precached.includes(origin + '/static/match-result.js?v=20261004'));
    assert.ok(worker.precached.includes(origin + '/static/live-match.css?v=20261004'));
    assert.ok(worker.precached.includes(origin + '/static/icon-192.svg'));
    assert.ok(!worker.precached.includes(origin + '/players'));
});
