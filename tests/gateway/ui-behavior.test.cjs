// Execute the shipped modules, with a minimal DOM and deterministic transports.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '../../ui/js');

class Element {
  constructor(tag) { this.tag = tag; this.value = ''; this.textContent = ''; this.dataset = {}; this.children = []; this.listeners = {}; this.attributes = {}; }
  appendChild(node) { this.children.push(node); return node; }
  replaceChildren(...nodes) { this.children = nodes; }
  setAttribute(key, value) { this.attributes[key] = value; if (key === 'data-role') this.dataset.role = value; if (key === 'data-i18n') this.dataset.i18n = value; if (key === 'disabled') this.disabled = true; }
  removeAttribute(key) { delete this.attributes[key]; if (key === 'disabled') this.disabled = false; }
  addEventListener(type, callback) { this.listeners[type] = callback; }
  get childNodes() { return this.children; }
  remove() {}
  click() { this.clicked = true; }
}

async function harness(page, responses = {}, desktop = null) {
  const main = new Element('main');
  const sockets = [];
  const events = {};
  const requests = [];
  const downloads = [];
  const walk = node => [node, ...node.children.flatMap(walk)];
  const document = { createElement: tag => new Element(tag), getElementById: () => main,
    querySelectorAll: selector => selector === '[data-i18n]' ? walk(main).filter(node => node.dataset.i18n) : [],
    querySelector: () => null, body: new Element('body') };
  document.body.appendChild = node => { downloads.push(node); return node; };
  const context = vm.createContext({ console, document, URLSearchParams, Date,
    CustomEvent: class { constructor(type) { this.type = type; } },
    window: { document, location: { hash: `#/${page}`, protocol: 'http:', host: '127.0.0.1:7842' },
      addEventListener(name, listener) { (events[name] ||= []).push(listener); },
      removeEventListener(name, listener) { events[name] = (events[name] || []).filter(item => item !== listener); },
      dispatchEvent(event) { for (const listener of events[event.type] || []) listener(event); },
      open() {},
      ...(desktop ? { __TAURI__: { core: { invoke: desktop } }, __DECLAW_DESKTOP_GENERATION__: 7, __DECLAW_DESKTOP_ORIGIN__: 'http://127.0.0.1:7842' } : {}) },
    fetch: async (url, options) => {
      const key = String(url).replace('http://127.0.0.1:7842', '');
      requests.push({ url: key, options });
      const body = typeof responses === 'function' ? responses(key, options) : responses[key] || {};
      return new Response(JSON.stringify(body), { status: body.httpStatus || 200, headers: { 'content-type': 'application/json' } });
    },
    WebSocket: class { static OPEN = 1; constructor(url) { this.url = url; this.readyState = 1; this.sent = []; sockets.push(this); queueMicrotask(() => this.onopen?.()); } close() { this.readyState = 3; } send(value) { this.sent.push(JSON.parse(value)); } },
  });
  const modules = new Map();
  function load(file) {
    if (!modules.has(file)) modules.set(file, new vm.SourceTextModule(fs.readFileSync(file, 'utf8'), { context, identifier: file }));
    return modules.get(file);
  }
  const app = load(path.join(root, 'app.js'));
  await app.link((specifier, parent) => load(path.resolve(path.dirname(parent.identifier), specifier)));
  await app.evaluate();
  // Bootstrap awaits locales, settings, then the page's REST or WS setup.
  await app.namespace.ready;
  return { main, sockets, requests, downloads, async route(page) {
    context.window.location.hash = `#/${page}`;
    context.window.dispatchEvent({ type: 'hashchange' });
    await new Promise(resolve => setImmediate(resolve));
  }, async dispatch(type, detail) {
    context.window.dispatchEvent({ type, detail });
    await new Promise(resolve => setImmediate(resolve));
  } };
}

test('connect bootstrap displays the login form', async () => {
  const { main } = await harness('connect');
  assert.ok(main.children.some(node => node.tag === 'form'));
});

test('desktop picker supplies a candidate only and cancellation preserves the field', async () => {
  let selection = 'D:\\Documents\\Équipe workspace';
  const calls = [];
  const { main } = await harness('settings', { '/api/settings': { workspace_dir: 'D:\\old', language: 'en' } }, async (command, args) => {
    calls.push([command, args]); return selection;
  });
  const field = main.children.find(node => node.children?.some(child => child.attributes.id === 'workspace'));
  const input = field.children.find(node => node.attributes.id === 'workspace');
  const button = field.children.find(node => node.tag === 'button');
  assert.ok(button);
  await button.listeners.click();
  assert.equal(input.value, selection);
  assert.deepEqual(calls.map(call => call[0]), ['pick_workspace']);
  assert.equal(calls[0][1].generation, 7);
  selection = null;
  await button.listeners.click();
  assert.equal(input.value, 'D:\\Documents\\Équipe workspace');
});

test('browser settings retain a plain path field without native picker', async () => {
  const { main } = await harness('settings', { '/api/settings': {} });
  const field = main.children.find(node => node.children?.some(child => child.attributes.id === 'workspace'));
  assert.ok(field.children.some(node => node.attributes.id === 'workspace'));
  assert.equal(field.children.some(node => node.tag === 'button'), false);
});

test('desktop folder picker uses the shipped EN and FR labels', async () => {
  const en = JSON.parse(fs.readFileSync(path.join(root, '../locales/en.json'), 'utf8'));
  const fr = JSON.parse(fs.readFileSync(path.join(root, '../locales/fr.json'), 'utf8'));
  for (const [language, expected] of [['en', 'Choose folder…'], ['fr', 'Choisir un dossier…']]) {
    const { main } = await harness('settings', {
      'locales/en.json': en, 'locales/fr.json': fr,
      '/api/settings': { language },
    }, async () => null);
    const field = main.children.find(node => node.children?.some(child => child.attributes.id === 'workspace'));
    assert.equal(field.children.find(node => node.tag === 'button').textContent, expected);
  }
});

test('chat composer supports multiline input and prevents overlapping sends', async () => {
  const { main, sockets } = await harness('chat');
  const composer = main.children.find(node => node.className === 'chat-composer chat-input-bar');
  assert.ok(composer);
  const input = composer.children.find(node => node.tag === 'textarea');
  const send = composer.children.find(node => node.className === 'button-primary');
  const cancel = composer.children.find(node => node.attributes['data-variant'] === 'danger');
  assert.equal(cancel.disabled, true);
  input.value = 'First line\nSecond line';
  input.listeners.keydown({ key: 'Enter', shiftKey: true });
  assert.equal(sockets[0].sent.length, 0);
  let prevented = false;
  input.listeners.keydown({ key: 'Enter', preventDefault() { prevented = true; } });
  assert.equal(prevented, true);
  assert.equal(sockets[0].sent[0].text, 'First line\nSecond line');
  assert.equal(send.disabled, true);
  input.value = 'Do not send while busy';
  send.listeners.click();
  assert.equal(sockets[0].sent.length, 1);
  sockets[0].onmessage({ data: JSON.stringify({ type: 'turn.started', turn_id: 'one' }) });
  assert.equal(cancel.disabled, false);
  sockets[0].onmessage({ data: JSON.stringify({ type: 'chat.final', text: 'Done', sources: [] }) });
  assert.equal(cancel.disabled, true);
  assert.equal(send.disabled, false);
});
test('documents page mounts and displays catalog rows', async () => {
  const { main } = await harness('documents', { '/api/documents': { documents: [{ path: 'guide.txt', status: 'indexed' }] } });
  const table = main.children.find(node => node.tag === 'table');
  assert.equal(table.children[1].children[0].children[0].textContent, 'guide.txt');
});

test('a rejected chat turn releases the send control', async () => {
  const { main, sockets } = await harness('chat');
  const composer = main.children.find(node => node.className === 'chat-composer chat-input-bar');
  const input = composer.children.find(node => node.tag === 'textarea');
  const send = composer.children.find(node => node.className === 'button-primary');
  input.value = 'Hello';
  send.listeners.click();
  assert.equal(send.disabled, true);
  sockets[0].onmessage({ data: JSON.stringify({ type: 'error', code: 'rate_limited' }) });
  assert.equal(send.disabled, false);
});
test('chat final renders the authoritative answer and citations', async () => {
  const { main, sockets } = await harness('chat');
  const send = frame => sockets[0].onmessage({ data: JSON.stringify(frame) });
  send({ type: 'turn.started', turn_id: 'one' });
  send({ type: 'chat.final', text: 'Complete answer', sources: ['guide.txt'] });
  const bubble = main.children[2].children[0];
  assert.equal(bubble.textContent, 'Complete answer');
  assert.ok(bubble.children.some(node => node.tag === 'ul'));
});
test('tool events do not lose later assistant deltas', async () => {
  const { main, sockets } = await harness('chat');
  const send = frame => sockets[0].onmessage({ data: JSON.stringify(frame) });
  send({ type: 'turn.started', turn_id: 'one' });
  send({ type: 'tool.start', name: 'search' });
  send({ type: 'tool.end', name: 'search' });
  send({ type: 'chat.delta', text: 'Answer after search' });
  assert.equal(main.children[2].children[0].textContent, 'Answer after search');
});

test('in-app navigation retains the active chat socket, transcript, draft and cancellation', async () => {
  const app = await harness('chat');
  const { main, sockets } = app;
  const composer = main.children[3];
  composer.children[0].value = 'Unsent draft';
  sockets[0].onmessage({ data: JSON.stringify({ type: 'turn.started', turn_id: 'retained' }) });
  sockets[0].onmessage({ data: JSON.stringify({ type: 'chat.delta', text: 'First part' }) });
  await app.route('documents');
  sockets[0].onmessage({ data: JSON.stringify({ type: 'chat.delta', text: ' while away' }) });
  await app.route('chat');
  assert.equal(sockets.filter(socket => socket.url.endsWith('/ws/chat')).length, 1);
  assert.equal(sockets[0].readyState, 1);
  assert.equal(main.children[2].children[0].textContent, 'First part while away');
  assert.equal(main.children[3].children[0].value, 'Unsent draft');
  main.children[3].children[2].listeners.click();
  assert.equal(sockets[0].sent[0].turn_id, 'retained');
});

test('authentication loss closes and discards retained chat state', async () => {
  const app = await harness('chat');
  app.sockets[0].onmessage({ data: JSON.stringify({ type: 'turn.started', turn_id: 'private' }) });
  app.sockets[0].onmessage({ data: JSON.stringify({ type: 'chat.delta', text: 'Private answer' }) });
  await app.dispatch('declaw:unauthenticated');
  assert.equal(app.sockets[0].readyState, 3);
  await app.route('chat');
  assert.equal(app.sockets.length, 2);
  assert.equal(app.main.children[2].children.some(node => node.textContent === 'Private answer'), false);
});

test('cancelled partial response is explicitly marked and tools do not stay running', async () => {
  const { main, sockets } = await harness('chat');
  const frame = value => sockets[0].onmessage({ data: JSON.stringify(value) });
  frame({ type: 'turn.started', turn_id: 'one' });
  frame({ type: 'chat.delta', text: 'Partial answer' });
  frame({ type: 'tool.start', name: 'search' });
  frame({ type: 'turn.cancelled', turn_id: 'one' });
  const log = main.children[2];
  assert.ok(log.children.some(node => /chat.cancelled/.test(node.textContent)));
  assert.equal(log.children.some(node => /search.*…/.test(node.textContent)), false);
});

test('tool completion replaces its running activity instead of adding a second card', async () => {
  const { main, sockets } = await harness('chat');
  const frame = value => sockets[0].onmessage({ data: JSON.stringify(value) });
  frame({ type: 'turn.started', turn_id: 'one' });
  frame({ type: 'tool.start', name: 'search' });
  frame({ type: 'tool.end', name: 'search', result_preview: 'Found two matches' });
  const tools = main.children[2].children.filter(node => node.attributes['data-role'] === 'tool');
  assert.equal(tools.length, 1);
  assert.match(tools[0].textContent, /Found two matches/);
});
test('audit shows the flat event fields returned by the API', async () => {
  const event = { id: 'one', event_type: 'tool.call', tool_name: 'filesystem_write', outcome: 'denied', args: { path: 'a.txt' } };
  const { main } = await harness('audit', { '/api/audit?': { events: [event] } });
  const table = main.children.find(node => node.tag === 'table');
  const payload = table.children[1].children[0].children[2];
  const details = payload.children.find(node => node.tag === 'details');
  assert.ok(details, 'raw event payload must be available without dominating the table');
  assert.match(details.children.find(node => node.tag === 'pre').textContent, /filesystem_write/);
});

for (const format of ['json', 'md']) test(`audit exports ${format} through the authenticated API without opening another window`, async () => {
  const app = await harness('audit', { '/api/audit?': { events: [] } });
  app.main.children[2].children[0].value = '2026-11-14';
  await app.main.children[2].children[format === 'json' ? 2 : 1].listeners.click();
  const request = app.requests.find(request => request.url.includes('/api/audit/export'));
  assert.ok(request, 'export must request an authenticated response');
  assert.equal(request.url, `/api/audit/export?day=2026-11-14&format=${format}`);
  assert.equal(request.options.credentials, 'same-origin');
  const download = app.main.children[2].children.find(node => node.tag === 'a');
  assert.ok(download, 'native downloads require a visible link with a real user gesture');
  assert.equal(download.download, `declaw-audit-2026-11-14.${format}`);
  assert.notEqual(download.clicked, true);
  assert.equal(download.href, `http://127.0.0.1:7842/api/audit/export?day=2026-11-14&format=${format}`);
});

test('audit export reports authentication failure without creating a download', async () => {
  const app = await harness('audit', url => url.includes('/export') ? { httpStatus: 401 } : { events: [] });
  await app.main.children[2].children[1].listeners.click();
  assert.equal(app.downloads.length, 0);
  assert.equal(app.sockets.length, 0);
  assert.match(app.main.children[5].textContent, /unauthorized/);
});

test('native download completion reports success or failure without claiming a saved file early', async () => {
  const app = await harness('audit', { '/api/audit?': { events: [] } });
  await app.main.children[2].children[1].listeners.click();
  assert.match(app.main.children[5].textContent, /audit.download_ready/);
  await app.dispatch('declaw:download-finished', false);
  assert.match(app.main.children[5].textContent, /error.download_failed/);
  await app.dispatch('declaw:download-finished', true);
  assert.match(app.main.children[5].textContent, /audit.download_complete/);
});

test('audit Older then Newer restores the first page and resets history with filters', async () => {
  const app = await harness('audit', url => url.includes('cursor=older')
    ? { events: [{ id: 'old', event_type: 'tool.call' }], next_cursor: null }
    : { events: [{ id: 'new', event_type: 'tool.call' }], next_cursor: 'older' });
  const pager = app.main.children[4];
  await pager.children[1].listeners.click();
  assert.equal(pager.children[0].disabled, false);
  assert.equal(pager.children[1].disabled, true);
  await pager.children[0].listeners.click();
  assert.match(app.main.children[3].children[1].children[0].children[2].children[0].children[1].textContent, /"new"/);
  assert.equal(pager.children[0].disabled, true);
  await pager.children[1].listeners.click();
  await app.main.children[1].children[5].listeners.click();
  assert.equal(pager.children[0].disabled, true);
});

test('saving a new Settings language updates every label and feedback in that language', async () => {
  const en = JSON.parse(fs.readFileSync(path.join(root, '../locales/en.json'), 'utf8'));
  const fr = JSON.parse(fs.readFileSync(path.join(root, '../locales/fr.json'), 'utf8'));
  const app = await harness('settings', (url, options) => {
    if (url === 'locales/en.json') return en;
    if (url === 'locales/fr.json') return fr;
    if (options?.method === 'PUT') return { applied: { workspace_dir: 'restart_required' } };
    return { language: 'en', workspace_dir: 'D:\\unchanged', model: 'test-model' };
  }, async () => null);
  app.main.children[4].children[1].value = 'fr';
  await app.main.children[6].listeners.click();
  assert.equal(app.main.children[3].children[0].textContent, 'Modèle');
  assert.equal(app.main.children[5].children[0].textContent, 'Dossier de travail');
  assert.equal(app.main.children[5].children[1].value, 'D:\\unchanged');
  assert.equal(app.main.children[6].textContent, 'Enregistrer');
  assert.match(app.main.children[2].textContent, /Nécessite un redémarrage/);
  assert.doesNotMatch(app.main.children[2].textContent, /workspace_dir/);
});

test('closed chat offers a fresh session without replaying messages', async () => {
  const app = await harness('chat');
  app.sockets[0].readyState = 3;
  app.sockets[0].onclose();
  await app.route('documents');
  await app.route('chat');
  const newSession = app.main.children[0].children.find(node => node.tag === 'button');
  assert.ok(newSession, 'disconnected chat needs an explicit recovery control');
  await newSession.listeners.click();
  assert.equal(app.sockets.filter(socket => socket.url.endsWith('/ws/chat')).length, 2);
  assert.equal(app.sockets.at(-1).sent.length, 0);
  assert.equal(app.main.children[3].children[1].disabled, false);
});

test('retained Chat localizes the welcome and speaker labels after Settings changes', async () => {
  const en = JSON.parse(fs.readFileSync(path.join(root, '../locales/en.json'), 'utf8'));
  const fr = JSON.parse(fs.readFileSync(path.join(root, '../locales/fr.json'), 'utf8'));
  const app = await harness('chat', (url, options) => {
    if (url === 'locales/en.json') return en;
    if (url === 'locales/fr.json') return fr;
    if (options?.method === 'PUT') return { applied: { language: 'new_session' } };
    return { language: 'en' };
  });
  await app.route('settings');
  app.main.children[4].children[1].value = 'fr';
  await app.main.children[6].listeners.click();
  await app.route('chat');
  assert.equal(app.main.children[2].children[0].children[1].textContent, fr.chat.empty_title);
  const composer = app.main.children[3];
  composer.children[0].value = 'Preserve this text';
  composer.children[1].listeners.click();
  assert.equal(app.main.children[2].children[0].attributes['data-label'], fr.chat.you);
  await app.route('settings');
  app.main.children[4].children[1].value = 'en';
  await app.main.children[6].listeners.click();
  await app.route('chat');
  assert.equal(app.main.children[2].children[0].attributes['data-label'], en.chat.you);
  assert.equal(app.main.children[2].children[0].textContent, 'Preserve this text');
});

test('trusted bootstrap offers a same-core window retry after native creation failure', async () => {
  const ids = ['language', 'status', 'start', 'stop', 'restart', 'reveal', 'token', 'clear', 'help'];
  const elements = Object.fromEntries(ids.map(id => [id, new Element('button')]));
  elements.language.value = 'en';
  let state = { generation: 7, state: 'running', view_error: true };
  const calls = [];
  const refreshers = [];
  const document = { getElementById: id => elements[id], addEventListener() {}, documentElement: {} };
  const window = { __TAURI__: { core: { invoke: async name => { calls.push(name); return state; } } } };
  const source = fs.readFileSync(path.resolve(root, '../../tauri/bootstrap/app.js'), 'utf8');
  await vm.runInNewContext(source, { document, window, setInterval(callback) { refreshers.push(callback); } });
  assert.equal(elements.start.disabled, false);
  assert.equal(elements.start.textContent, 'Retry opening window');
  assert.match(elements.status.textContent, /core is still running/);
  await elements.start.listeners.click();
  assert.ok(calls.includes('desktop_start'));
  assert.equal(calls.includes('desktop_restart'), false);
  state = { ...state, view_error: false };
  await refreshers[0]();
  assert.equal(elements.start.disabled, true);
  assert.equal(elements.start.textContent, 'Start');
});
