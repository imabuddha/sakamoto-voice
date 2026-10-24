// node --test plugin/tests/app-voice-speed.test.mjs: the speed app-voice.mjs asks the read-aloud
// service for (tts_speed). Miss Sakamoto's own, SPEED (1.5), unless --speed says otherwise; with
// --speed 0, the account's, held to 0.7 to 1.2 as the app's engine does. pageVoice runs here against
// a stand-in page (no engine module, a localStorage, a WebSocket that only notes its address), and
// app-voice.mjs against a stand-in debugger that notes what it was asked to run. Nothing here opens
// the Claude app or the network.
import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { pageVoice } from '../scripts/app-voice-lib.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const dir = mkdtempSync(join(tmpdir(), 'app-voice-speed-test-'));
test.after(() => rmSync(dir, { recursive: true, force: true }));

// The tts_speed pageVoice sends, with the page's saved speed (localStorage) and arg.speed.
async function sentSpeed(storedSpeed, argSpeed) {
  const opened = [];
  const page = {
    window: {},
    document: { querySelectorAll: () => [], getElementById: () => null, body: { children: [] } },
    localStorage: { getItem: (k) => (k === 'claude-voice-speed' ? storedSpeed : null) },
    location: { host: 'claude.ai' },
    WebSocket: class { constructor(url) { opened.push(url); } close() {} },
  };
  const saved = {};
  for (const [k, v] of Object.entries(page)) {
    saved[k] = Object.getOwnPropertyDescriptor(globalThis, k);
    Object.defineProperty(globalThis, k, { value: v, configurable: true, writable: true });
  }
  try {
    const started = await pageVoice('start', { id: 't', text: 'Hello there.', speed: argSpeed });
    await pageVoice('stop', '*');
    assert.equal(opened.length, 1, JSON.stringify(started));
    return { url: new URL(opened[0]).searchParams.get('tts_speed'), reported: started.speed };
  } finally {
    for (const [k, d] of Object.entries(saved)) {
      if (d) Object.defineProperty(globalThis, k, d); else delete globalThis[k];
    }
  }
}

test('pageVoice: the account speed is held to 1.2, as the app engine does', async () => {
  assert.deepEqual(await sentSpeed('1.2', ''), { url: '1.20', reported: '1.20' });
  assert.deepEqual(await sentSpeed('1.5', ''), { url: '1.20', reported: '1.20' });
  assert.deepEqual(await sentSpeed(null, ''), { url: '1.00', reported: '1.00' });
});

test('pageVoice: an asked speed is sent as asked, within 0.5 to 1.5', async () => {
  assert.deepEqual(await sentSpeed('1.2', 1.5), { url: '1.50', reported: '1.50' });
  assert.deepEqual(await sentSpeed('1.2', 3), { url: '1.50', reported: '1.50' });
  assert.deepEqual(await sentSpeed('1.2', 0.2), { url: '0.50', reported: '0.50' });
});

// app-voice.mjs against a stand-in debugger: it writes the start call's argument to a file and
// answers with an error, so the script stops there (exit 2).
const stub = join(dir, 'stub.mjs');
writeFileSync(stub, `
import { writeFileSync } from 'node:fs';
globalThis.fetch = async () => ({ json: async () => [{ webSocketDebuggerUrl: 'ws://stub' }] });
globalThis.WebSocket = class {
  constructor() { setTimeout(() => this.onopen && this.onopen(), 0); }
  send(data) {
    const { id, params } = JSON.parse(data);
    const m = params.expression.match(/\\('start', (\\{.*?\\})\\)/);
    if (m) writeFileSync(process.env.STARTED_FILE, JSON.parse('"' + m[1] + '"'));
    setTimeout(() => this.onmessage({ data: JSON.stringify({ id, result: { result: { value: { error: 'stub' } } } }) }), 0);
  }
  close() {}
};
`);

function startArg(...extra) {
  const file = join(dir, 'started.json');
  writeFileSync(file, '');
  const run = spawnSync(process.execPath, ['--import', stub, join(here, '..', 'scripts', 'app-voice.mjs'), '--text', 'Hello.', ...extra],
    { env: { ...process.env, STARTED_FILE: file }, encoding: 'utf8', timeout: 15000 });
  assert.equal(run.status, 2, run.stderr);
  return JSON.parse(readFileSync(file, 'utf8'));
}

test('app-voice.mjs asks for SPEED, 1.5, by default', () => {
  assert.equal(startArg().speed, 1.5);
});

test('app-voice.mjs --speed: that speed; 0, the account speed', () => {
  assert.equal(startArg('--speed', '1.2').speed, 1.2);
  assert.equal(startArg('--speed', '0').speed, '');
});
