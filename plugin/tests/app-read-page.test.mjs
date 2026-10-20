// node --test plugin/tests/app-read-page.test.mjs: which Claude app page app-read.mjs presses Read
// aloud in. With SAKAMOTO_RELAY_PAGE (a person's own session, SAKAMOTO_OWNER) only the page whose
// address or title holds that text; without it the focused session page, as always. Run as the real
// script against a stand-in for the app's main-process debugger (a fetch and a WebSocket that run
// the expression in a fake `electron`). Nothing here opens the Claude app.
import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const dir = mkdtempSync(join(tmpdir(), 'app-read-test-'));
const stub = join(dir, 'stub.mjs');
writeFileSync(stub, `
const pages = JSON.parse(process.env.FAKE_PAGES);
const contents = pages.map((p) => ({
  id: p.id, getURL: () => p.url, getTitle: () => p.title, isFocused: () => !!p.focused, isDestroyed: () => false,
  setBackgroundThrottling: () => {},
  executeJavaScript: async () => ({ done: 'clicked on page ' + p.id }),
}));
const electron = { webContents: { getAllWebContents: () => contents, fromId: (id) => contents.find((c) => c.id === id) } };
globalThis.fetch = async () => ({ json: async () => [{ webSocketDebuggerUrl: 'ws://stub' }] });
globalThis.WebSocket = class {
  constructor() { setTimeout(() => this.onopen && this.onopen(), 0); }
  send(data) {
    const { params } = JSON.parse(data);
    const run = new Function('require', 'return ' + params.expression);
    Promise.resolve(run((name) => { if (name !== 'electron') throw new Error(name); return electron; }))
      .then((value) => this.onmessage({ data: JSON.stringify({ id: 1, result: { result: { value } } }) }));
  }
};
`);
test.after(() => rmSync(dir, { recursive: true, force: true }));

const pages = [
  { id: 1, url: 'https://claude.ai/epitaxy/local_aaaa1111', title: 'Main work', focused: false },
  { id: 2, url: 'https://claude.ai/epitaxy/local_bbbb2222', title: 'Her session', focused: true },
  { id: 3, url: 'https://claude.ai/settings', title: 'Settings', focused: false },
];

function read(page) {
  const env = { ...process.env, FAKE_PAGES: JSON.stringify(pages), SAKAMOTO_RELAY_PAGE: page };
  const run = spawnSync(process.execPath, ['--import', stub, join(here, '..', 'scripts', 'app-read.mjs'), '9229', 'hello', '2000'],
    { env, encoding: 'utf8', timeout: 15000 });
  return { status: run.status, out: run.stdout.trim() };
}

test('app-read.mjs without a page: the focused session page, as always', () => {
  const run = read('');
  assert.equal(run.status, 0, run.out);
  assert.match(run.out, /clicked on page 2/);
});

test('app-read.mjs with SAKAMOTO_RELAY_PAGE: that session page, focused or not', () => {
  assert.match(read('local_aaaa1111').out, /clicked on page 1/);
  assert.match(read('LOCAL_AAAA').out, /clicked on page 1/);
  assert.match(read('main work').out, /clicked on page 1/);          // by title
  assert.match(read('her session').out, /clicked on page 2/);
});

test('app-read.mjs with a page nothing matches: no session page, never another', () => {
  const run = read('local_cccc3333');
  assert.equal(run.status, 1);
  assert.equal(run.out, 'no session page');
  assert.equal(read('settings').out, 'no session page');             // not a session page
});
