// What app-voice.mjs needs that isn't the inspector: the code it puts into the Claude app's session
// page (pageVoice, sent there as text, so it uses nothing from outside its body), and the audio
// handling on this side (Resampler, wavHeader, Pacer). Shared with the tests: node imports it.

// Runs in the session page (the claude.ai origin, with its session), called as
// pageVoice(cmd, arg) for cmd "start" (async) or "stop"; drain() is called on the object it installs
// as window.__sakamotoVoice. The page's own WebSocket carries the request, so the session's
// cookies are the browser's business: nothing here reads them, and nothing about them leaves the page.
//
// Read aloud's protocol (the app's read-aloud engine, 2026-10-18): a WebSocket to
// /api/ws/text_to_speech/text_stream?output_format=pcm_16000&voice=…&tts_speed=…&client_platform=…;
// the client sends {"type":"text_chunk","text":…} per piece of the text (about 800 characters, split
// at sentences), then {"type":"close_stream"}, and {"type":"keep_alive"} every 4 s; the server sends
// binary audio frames (16-bit mono PCM at 16 kHz) and JSON frames whose type names a speech event
// (…Complete at the end, …Error or "error" on failure).
//
// The helpers the engine itself uses (its URL builder, its voice and speed store, the client
// platform, the organization parameter) are found through the engine's module: its file's name in
// the page's preloaded scripts, its imports, and the local names its code uses for them; each
// missing one falls back to a default (and says so in `notes`). Importing a module the page has
// loaded returns the page's own instance.
//
// The voice, speed, and language are the ones the Read aloud button passes the engine (its hook in
// the chat message's toolbar, 2026-10-18), all from the account's settings (Settings > General >
// Voice), which the page holds as React context (its CurrentAccountProvider; found here by walking
// the page's React tree to the provider whose value has `account` and `activeOrganization`):
//   voice     settings.voice_preference, else the voice store's selectedVoice (which holds only the
//             five English voices, so a Japanese style such as 明るい, "ja-akarui", is never there)
//   speed     settings.voice_speed when it's a number from 0.5 to 2, else the store's voiceSpeed;
//             then held to 0.7 to 1.2, as the engine does
//   language  settings.voice_language_code ("ja"; none when unset, as the button sends none)
//   organization  the active organization's uuid
// arg.voice, arg.speed, and arg.language, when given, override these; arg.speed (app-voice.mjs's
// --speed, the config's app_voice_speed) is sent as given, held to 0.5 to 1.5, not to the engine's
// 1.2 (the server closes the socket, 1003, at 1.75 and 2; measured 2026-10-24). The account's settings
// follow any change made in Settings at once (the page updates its context), so each reading uses
// the current ones.
//
// The page is left clean: a session ends when the stream is done, on stop, or when nobody has
// drained it for WATCHDOG_MS (app-voice.mjs gone); with no session left, the object is removed.
export async function pageVoice(cmd, arg) {
  const WATCHDOG_MS = 8000;
  const KEEP_ALIVE_MS = 4000;
  const PIECE = 800;
  const V = window.__sakamotoVoice || (window.__sakamotoVoice = { sessions: {}, timer: null });
  const end = (s, why) => {
    if (!s.closed) {
      s.closed = true;
      s.why = s.why || why;
    }
    try {
      if (s.ws && s.ws.readyState <= 1) s.ws.close();
    } catch (e) { /* closing anyway */ }
  };
  const tidy = () => {
    if (Object.keys(V.sessions).length) return;
    if (V.timer) clearInterval(V.timer);
    if (window.__sakamotoVoice === V) delete window.__sakamotoVoice;
  };
  const b64 = (parts) => {
    let s = '';
    for (const u8 of parts) {
      for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
    }
    return btoa(s);
  };
  V.drain = (id) => {
    const s = V.sessions[id];
    if (!s) return { state: 'gone' };
    s.lastPoll = Date.now();
    const out = { state: s.closed ? 'closed' : s.state, events: s.events.splice(0), audio: s.audio.length ? b64(s.audio) : '' };
    s.audio = [];
    if (s.error) out.error = s.error;
    if (s.closed) {
      out.why = s.why;
      if (s.closeCode !== undefined) out.close = s.closeCode;
      delete V.sessions[id];
      tidy();
    }
    return out;
  };
  if (cmd === 'stop') {
    for (const [id, s] of Object.entries(V.sessions)) {
      if (arg === '*' || arg === id) {
        end(s, 'stopped');
        delete V.sessions[id];
      }
    }
    tidy();
    return { stopped: true };
  }
  if (cmd !== 'start') return { error: 'unknown command ' + cmd };

  // A new reading supersedes any other (as the app's engine does).
  for (const [id, s] of Object.entries(V.sessions)) {
    end(s, 'superseded');
    delete V.sessions[id];
  }
  const notes = [];
  const helpers = {};
  try {
    const links = [...document.querySelectorAll('script[src], link[href]')].map((e) => e.src || e.href)
      .filter((u) => /\.js($|\?)/.test(u));
    let engineUrl = null;
    for (const u of links) {
      const text = await (await fetch(u)).text();
      const m = text.match(/cb17312fe-[\w-]+\.js/);
      if (m) {
        engineUrl = new URL(m[0], u).href;
        break;
      }
    }
    if (!engineUrl) throw new Error('the read-aloud engine module was not found');
    const src = await (await fetch(engineUrl)).text();
    const imports = {};
    for (const m of src.matchAll(/import\{([^}]*)\}from"([^"]+)"/g)) {
      for (const part of m[1].split(',')) {
        const words = part.trim().split(/\s+/);
        if (words[0]) imports[words[2] || words[0]] = [m[2], words[0]];
      }
    }
    const get = async (re, what) => {
      const local = (src.match(re) || [])[1];
      const from = local && imports[local];
      if (!from) {
        notes.push('no ' + what);
        return undefined;
      }
      return (await import(new URL(from[0], engineUrl).href))[from[1]];
    };
    helpers.url = await get(/([\w$]+)\(`\/api\/ws\/text_to_speech\/text_stream\?/, 'URL helper');
    helpers.store = await get(/\{selectedVoice:[\w$]+,voiceSpeed:[\w$]+\}=([\w$]+)\.getState\(\)/, 'voice store');
    helpers.platform = await get(/client_platform:([\w$]+)\(\)/, 'client platform');
    helpers.orgKey = await get(/\.\.\.[\w$]+\?\{\[([\w$]+)\]:[\w$]+\}:\{\}/, 'organization key');
    helpers.extra = await get(/:\{\},\.\.\.([\w$]+)\(\),\.\.\.[\w$]+\?\{speech_checkpoints/, 'extra parameters');
    helpers.chunk = (await import(engineUrl))._test?.chunkForTts;
  } catch (e) {
    notes.push('helpers: ' + e.message);
  }
  let state = {};
  try {
    state = helpers.store && typeof helpers.store.getState === 'function' ? helpers.store.getState() : {};
  } catch (e) {
    notes.push('store: ' + e.message);
  }
  const stored = (key) => {
    try {
      return localStorage.getItem(key);
    } catch (e) {
      return null;
    }
  };
  // The account context, as the button's hook reads it (useContext): the first provider, from the
  // top of the page's React tree, whose value holds the account and the active organization.
  let account = null;
  try {
    const roots = new Set();
    for (const el of [document.getElementById?.('root'), ...(document.body?.children || [])]) {
      if (!el) continue;
      for (const k of Object.keys(el)) if (k.startsWith('__reactContainer$') && el[k]) roots.add(el[k]);
    }
    const stack = [...roots];
    for (let seen = 0; stack.length && seen < 200000; seen++) {
      const f = stack.pop();
      const v = f.memoizedProps && f.memoizedProps.value;
      if (f.type && typeof f.type === 'object' && v && typeof v === 'object' && 'account' in v && 'activeOrganization' in v) {
        account = v;
        break;
      }
      if (f.sibling) stack.push(f.sibling);
      if (f.child) stack.push(f.child);
    }
    if (!account) notes.push(roots.size ? 'no account settings' : 'no React root');
  } catch (e) {
    notes.push('account: ' + e.message);
  }
  const settings = (account && account.account && account.account.settings) || {};
  const voice = arg.voice || settings.voice_preference || state.selectedVoice || stored('claude-selected-voice') || 'buttery';
  const saved = settings.voice_speed;
  const asked = Number(arg.speed);
  let speed = Number((typeof saved === 'number' && saved >= 0.5 && saved <= 2 ? saved : 0) ||
    state.voiceSpeed || stored('claude-voice-speed') || 1);
  if (!(speed > 0)) speed = 1;
  speed = (asked > 0 ? Math.min(1.5, Math.max(0.5, asked)) : Math.min(1.2, Math.max(0.7, speed))).toFixed(2);
  const language = arg.language || settings.voice_language_code || '';
  const organization = arg.organization || (account && account.activeOrganization && account.activeOrganization.uuid) || '';
  let platform = 'desktop_app';
  try {
    if (typeof helpers.platform === 'function') platform = helpers.platform() || platform;
  } catch (e) {
    notes.push('platform: ' + e.message);
  }
  let extra = {};
  try {
    if (typeof helpers.extra === 'function') extra = helpers.extra() || {};
  } catch (e) {
    notes.push('extra: ' + e.message);
  }
  const params = new URLSearchParams({ output_format: 'pcm_16000', voice, tts_speed: speed, client_platform: platform,
    ...(language ? { language } : {}),
    ...(organization && typeof helpers.orgKey === 'string' ? { [helpers.orgKey]: organization } : {}), ...extra });
  const path = '/api/ws/text_to_speech/text_stream?' + params;
  let url = null;
  try {
    if (typeof helpers.url === 'function') url = helpers.url(path);
  } catch (e) {
    notes.push('url: ' + e.message);
  }
  if (typeof url !== 'string' || !/^wss?:\/\//.test(url)) url = 'wss://' + location.host + path;

  let pieces = null;
  try {
    if (typeof helpers.chunk === 'function') pieces = helpers.chunk(arg.text);
  } catch (e) {
    notes.push('chunker: ' + e.message);
  }
  if (!Array.isArray(pieces) || !pieces.every((p) => typeof p === 'string')) {
    pieces = [];
    let piece = '';
    for (const sentence of String(arg.text).match(/[^.!?。！？\n]+[.!?。！？\n]*\s*/g) || [String(arg.text)]) {
      if (piece && piece.length + sentence.length > PIECE) {
        pieces.push(piece);
        piece = '';
      }
      piece += sentence;
    }
    if (piece.trim()) pieces.push(piece);
  }
  pieces = pieces.filter((p) => p.trim());
  if (!pieces.length) return { error: 'nothing to read' };

  const id = String(arg.id);
  const s = { ws: null, state: 'connecting', audio: [], events: [], error: null, closed: false, lastPoll: Date.now(), lastSent: Date.now() };
  V.sessions[id] = s;
  const ws = new WebSocket(url);
  s.ws = ws;
  ws.binaryType = 'arraybuffer';
  ws.onopen = () => {
    if (s.closed) return ws.close();
    s.state = 'open';
    for (const text of pieces) ws.send(JSON.stringify({ type: 'text_chunk', text }));
    ws.send(JSON.stringify({ type: 'close_stream' }));
    s.lastSent = Date.now();
  };
  ws.onmessage = (m) => {
    if (s.closed) return;
    if (typeof m.data !== 'string') {
      s.audio.push(new Uint8Array(m.data));
      return;
    }
    let msg = null;
    try {
      msg = JSON.parse(m.data);
    } catch (e) {
      s.events.push('?');
      return;
    }
    const type = String((msg && msg.type) || '?');
    s.events.push(type + (msg && msg.audio_sent_ms !== undefined ? ' ' + msg.audio_sent_ms + ' ms' : ''));
    if (/error/i.test(type)) {
      const detail = (msg.error && (msg.error.message || msg.error.type)) || msg.message || '';
      s.error = (type + (detail ? ': ' + detail : '')).slice(0, 200);
      end(s, 'server error');
    } else if (/complete/i.test(type)) {
      s.state = 'complete';
      end(s, 'complete');
    }
  };
  ws.onerror = () => {
    if (!s.error && s.state === 'connecting') s.error = 'the WebSocket did not open';
  };
  ws.onclose = (e) => {
    s.closeCode = e.code;
    if (!s.closed) end(s, s.state === 'connecting' ? 'did not open' : 'closed by the server (' + e.code + ')');
  };
  if (!V.timer) {
    V.timer = setInterval(() => {
      const now = Date.now();
      for (const [sid, x] of Object.entries(V.sessions)) {
        if (now - x.lastPoll > WATCHDOG_MS) {
          end(x, 'watchdog');
          delete V.sessions[sid];
        } else if (!x.closed && x.state === 'open' && now - x.lastSent >= KEEP_ALIVE_MS) {
          try {
            x.ws.send(JSON.stringify({ type: 'keep_alive' }));
          } catch (e) { /* the close handler says why */ }
          x.lastSent = now;
        }
      }
      tidy();
    }, 1000);
  }
  return { id, voice, speed, language, platform, pieces: pieces.length, chars: pieces.reduce((n, p) => n + p.length, 0), notes };
}

// Converts 16-bit mono PCM between rates, a chunk at a time (windowed-sinc interpolation, 2*half
// taps, cut off a little below the lower rate's Nyquist frequency). push(Buffer) returns what it can
// produce so far; flush() the rest.
export class Resampler {
  constructor(inRate, outRate, half = 16) {
    this.same = inRate === outRate;
    this.step = inRate / outRate;
    this.half = half;
    this.fc = 0.5 * Math.min(1, outRate / inRate) * 0.92;
    this.x = [];
    this.pos = 0;
    this.kernels = new Map();
    this.carry = null;
  }

  kernel(frac) {
    const key = Math.round(frac * 1e6);
    let k = this.kernels.get(key);
    if (k) return k;
    const { half, fc } = this;
    k = new Float64Array(2 * half);
    let sum = 0;
    for (let t = 0; t < 2 * half; t++) {
      const d = t - half + 1 - frac;
      const x = 2 * fc * d;
      const sinc = x === 0 ? 1 : Math.sin(Math.PI * x) / (Math.PI * x);
      const w = Math.abs(d) < half ? 0.5 * (1 + Math.cos(Math.PI * d / half)) : 0;
      k[t] = sinc * w;
      sum += k[t];
    }
    for (let t = 0; t < 2 * half; t++) k[t] /= sum;
    this.kernels.set(key, k);
    return k;
  }

  run(real) {
    const out = [];
    const { x, half } = this;
    while (Math.floor(this.pos) + half < x.length && this.pos < real) {
      const base = Math.floor(this.pos);
      const k = this.kernel(this.pos - base);
      let acc = 0;
      for (let t = 0; t < 2 * half; t++) {
        const i = base - half + 1 + t;
        if (i >= 0) acc += x[i] * k[t];
      }
      out.push(acc);
      this.pos += this.step;
    }
    const drop = Math.floor(this.pos) - half + 1;
    if (drop > 0) {
      this.x = x.slice(drop);
      this.pos -= drop;
    }
    const buf = Buffer.alloc(out.length * 2);
    out.forEach((v, i) => buf.writeInt16LE(Math.max(-32768, Math.min(32767, Math.round(v))), i * 2));
    return buf;
  }

  push(chunk) {
    if (this.carry) {
      chunk = Buffer.concat([this.carry, chunk]);
      this.carry = null;
    }
    if (chunk.length % 2) {
      this.carry = chunk.subarray(chunk.length - 1);
      chunk = chunk.subarray(0, chunk.length - 1);
    }
    if (this.same) return Buffer.from(chunk);
    for (let i = 0; i < chunk.length; i += 2) this.x.push(chunk.readInt16LE(i));
    return this.run(Infinity);
  }

  flush() {
    if (this.same) return Buffer.alloc(0);
    const real = this.x.length;
    for (let i = 0; i < this.half + 1; i++) this.x.push(0);
    return this.run(real);
  }
}

// A WAV file's 44-byte header for `bytes` of 16-bit mono PCM at `rate`.
export function wavHeader(rate, bytes) {
  const h = Buffer.alloc(44);
  h.write('RIFF', 0);
  h.writeUInt32LE(36 + bytes, 4);
  h.write('WAVE', 8);
  h.write('fmt ', 12);
  h.writeUInt32LE(16, 16);
  h.writeUInt16LE(1, 20);
  h.writeUInt16LE(1, 22);
  h.writeUInt32LE(rate, 24);
  h.writeUInt32LE(rate * 2, 28);
  h.writeUInt16LE(2, 32);
  h.writeUInt16LE(16, 34);
  h.write('data', 36);
  h.writeUInt32LE(bytes, 40);
  return h;
}

// Lets audio out no faster than it plays, `lead` seconds ahead at most, from the first byte on:
// as app-voice-tap's audio comes, so the phones and Sakamoto Eyes' hub (which times her emoji by the
// stream's pace) see the same thing. allowed(now) is how many bytes may go now; sent(n) counts them.
export class Pacer {
  constructor(rate, lead = 1.0) {
    this.rate = rate;
    this.lead = lead;
    this.t0 = null;
    this.bytes = 0;
  }

  allowed(now) {
    if (this.t0 === null) this.t0 = now;
    const due = ((now - this.t0) / 1000 + this.lead) * this.rate * 2;
    return Math.max(0, Math.floor((due - this.bytes) / 2) * 2);
  }

  sent(n) {
    this.bytes += n;
  }
}
