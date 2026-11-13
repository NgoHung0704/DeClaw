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
  setAttribute(key, value) { this.attributes[key] = value; if (key === 'data-role') this.dataset.role = value; }
  removeAttribute(key) { delete this.attributes[key]; }
  addEventListener(type, callback) { this.listeners[type] = callback; }
}

async function harness(page, responses = {}, desktop = null) {
  const main = new Element('main');
  const sockets = [];
  const document = { createElement: tag => new Element(tag), getElementById: () => main,
    querySelectorAll: () => [], querySelector: () => null, body: new Element('body') };
  const context = vm.createContext({ console, document, URLSearchParams, Date,
    window: { document, location: { hash: `#/${page}`, protocol: 'http:', host: '127.0.0.1:7842' },
      addEventListener() {}, dispatchEvent() {},
      ...(desktop ? { __TAURI__: { core: { invoke: desktop } }, __DECLAW_DESKTOP_GENERATION__: 7, __DECLAW_DESKTOP_ORIGIN__: 'http://127.0.0.1:7842' } : {}) },
    fetch: async url => ({ ok: true, status: 200, json: async () => responses[String(url).replace('http://127.0.0.1:7842', '')] || {} }),
    WebSocket: class { static OPEN = 1; constructor() { this.readyState = 1; this.sent = []; sockets.push(this); queueMicrotask(() => this.onopen?.()); } close() {} send(value) { this.sent.push(JSON.parse(value)); } },
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
  return { main, sockets };
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
test('audit shows the flat event fields returned by the API', async () => {
  const event = { id: 'one', event_type: 'tool.call', tool_name: 'filesystem_write', outcome: 'denied', args: { path: 'a.txt' } };
  const { main } = await harness('audit', { '/api/audit?': { events: [event] } });
  const table = main.children.find(node => node.tag === 'table');
  assert.match(table.children[1].children[0].children[2].textContent, /filesystem_write/);
});
