// node --test plugin/tests/app-voice-owner.test.mjs: two people's sessions reading in one page
// (SAKAMOTO_OWNER) don't cut each other off. A new reading ends only its own owner's others, and a
// stop of '*' stops only its own owner's (John and Tamamo, 2026-10-24: their replies cancelled each
// other). pageVoice runs against a stand-in page; nothing here opens the Claude app or the network.
import test from 'node:test';
import assert from 'node:assert/strict';
import { pageVoice } from '../scripts/app-voice-lib.mjs';

const page = {
  window: {},
  document: { querySelectorAll: () => [], getElementById: () => null, body: { children: [] } },
  localStorage: { getItem: () => null },
  location: { host: 'claude.ai' },
  WebSocket: class { constructor() {} close() {} send() {} },
};

test('readings end only their own owner\'s others', async () => {
  const saved = {};
  for (const [k, v] of Object.entries(page)) {
    saved[k] = Object.getOwnPropertyDescriptor(globalThis, k);
    Object.defineProperty(globalThis, k, { value: v, configurable: true, writable: true });
  }
  try {
    // The registry is removed once its last reading ends (pageVoice's tidy).
    const live = () => Object.keys(globalThis.window.__sakamotoVoice?.sessions ?? {}).sort();
    await pageVoice('start', { id: 'john1', owner: '', text: 'Hello.' });
    await pageVoice('start', { id: 'tamamo1', owner: 'tamamo', text: 'こんにちは。' });
    assert.deepEqual(live(), ['john1', 'tamamo1']);
    await pageVoice('start', { id: 'john2', owner: '', text: 'Again.' });
    assert.deepEqual(live(), ['john2', 'tamamo1']);
    await pageVoice('stop', { which: '*', owner: '' });
    assert.deepEqual(live(), ['tamamo1']);
    await pageVoice('stop', 'tamamo1');
    assert.deepEqual(live(), []);
  } finally {
    for (const [k, d] of Object.entries(saved)) {
      if (d) Object.defineProperty(globalThis, k, d);
      else delete globalThis[k];
    }
  }
});
