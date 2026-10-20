// Speaks text in the Claude desktop app's Read aloud voice, without its button: through the app's
// Main Process Debugger (Developer menu → Enable Main Process Debugger: a Node inspector on
// 127.0.0.1:9229), it opens Read aloud's own text-to-speech WebSocket in the claude.ai session page
// (app-voice-lib.mjs: pageVoice) and passes the audio out. It relies on claude.ai's private,
// undocumented endpoint, which may change or go away with any update of the app or the site.
//
// Usage: node app-voice.mjs [--port 9229] [--rate 24000] [--lead 1.0] [--max-seconds 900]
//                           [--voice ID] [--language CODE] [--wav FILE] [--text TEXT]
//        node app-voice.mjs --stop [--port 9229]
// The voice, speed, and language are Read aloud's own, from the account's settings in the page (as
// the button passes them; app-voice-lib.mjs); --voice (a voice ID, "ja-akarui" say) and --language
// ("ja") override them.
// The text comes from --text, else standard input. The audio (16-bit mono PCM at --rate; the
// service sends 16 kHz, resampled here) goes to standard output, as app-voice-tap --stdout's does,
// paced as it plays (--lead seconds ahead), or, with --wav, into that file as fast as it comes.
// Standard error says "ready" when the first audio arrives, then one line: what was read, or why
// not. Exit status: 0 when it read; 2 when nothing could start (no debugger, no session page, the
// page's code failed); 6 when no sound came (the service refused or said nothing). SIGTERM (speak.py
// stop, a new response) closes the page's socket before exiting; --stop closes any left open. Should
// this script die without closing it, the page closes it itself within 8 s (nobody drains it).
import { pageVoice, Resampler, wavHeader, Pacer } from './app-voice-lib.mjs';
import { openSync, writeSync, closeSync } from 'node:fs';

const args = process.argv.slice(2);
const opt = (name, fallback) => {
  const i = args.indexOf(name);
  return i >= 0 && i + 1 < args.length ? args[i + 1] : fallback;
};
const port = opt('--port', '9229');
const RATE = Number(opt('--rate', '24000')) || 24000;
const LEAD = Number(opt('--lead', '1.0'));
const MAX_SECONDS = Number(opt('--max-seconds', '900')) || 900;
const WAV = opt('--wav', '');
const VOICE = opt('--voice', '');
const LANGUAGE = opt('--language', '');
const POLL_MS = 60;
const FIRST_AUDIO_MS = 8000;    // no audio by then: give up (the button's path may still work)
const SERVICE_RATE = 16000;

// A person's own session (SAKAMOTO_OWNER): its page in the Claude app, named as in app-read.mjs.
const WANTED_PAGE = (process.env.SAKAMOTO_RELAY_PAGE || '').trim().toLowerCase();

let ws = null;
let nextId = 1;
const pending = new Map();
let pageId = null;
const session = `sv${process.pid}-${Date.now()}`;
let finished = false;

const status = (line) => process.stderr.write(line + '\n');

// Runs `pageExpr` in the session page (the one this reading started in, once it has), from the
// app's main process.
const inPage = (pageExpr) => `(async () => {
  const req = (typeof require === 'function') ? require : process.mainModule.require.bind(process.mainModule);
  const { webContents } = req('electron');
  let page = ${pageId === null ? 'null' : `webContents.fromId(${pageId})`};
  if (!page) {
    let pages = webContents.getAllWebContents().filter(w => w.getURL().includes('claude.ai/epitaxy/'));
    const wanted = ${JSON.stringify(WANTED_PAGE)};
    if (wanted) {
      const byUrl = pages.filter(w => w.getURL().toLowerCase().includes(wanted));
      const named = byUrl.length ? byUrl : pages.filter(w => String(w.getTitle()).toLowerCase().includes(wanted));
      // Only the text read here comes from the session; the voice engine is any session page's.
      // A session in a window of its own (Open in > New window: an about:blank page, no engine of
      // its own) borrows a session page's (2026-10-20, Tamamo's session); its audio still goes
      // only where speak.py sends it.
      if (named.length) pages = named;
    }
    page = pages.find(w => w.isFocused()) || pages[0];
  }
  if (!page || page.isDestroyed()) return { error: 'no session page' };
  page.setBackgroundThrottling(false);
  try {
    const value = await page.executeJavaScript(${JSON.stringify(pageExpr)});
    return Object.assign({ page: page.id }, value);
  } catch (e) {
    return { error: 'page: ' + String(e && e.message || e).slice(0, 200) };
  }
})()`;

const evaluate = (expression, timeout = 15000) => new Promise((resolve) => {
  const id = nextId++;
  const timer = setTimeout(() => {
    pending.delete(id);
    resolve({ error: 'the inspector did not answer' });
  }, timeout);
  pending.set(id, (reply) => {
    clearTimeout(timer);
    const value = reply.result?.result?.value;
    resolve(value && typeof value === 'object' ? value
      : { error: String(reply.result?.exceptionDetails?.text || reply.error?.message || 'no answer').slice(0, 200) });
  });
  ws.send(JSON.stringify({ id, method: 'Runtime.evaluate', params: { expression, awaitPromise: true, returnByValue: true } }));
});

const connect = async () => {
  let targets;
  try {
    targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  } catch (e) {
    throw new Error(`debugger not reachable (${e.cause?.code || e.message})`);
  }
  if (!targets.length) throw new Error('no inspector target');
  ws = new WebSocket(targets[0].webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    ws.onopen = resolve;
    ws.onerror = () => reject(new Error('inspector connection failed'));
  });
  ws.onmessage = (m) => {
    const reply = JSON.parse(m.data);
    const done = pending.get(reply.id);
    if (done) {
      pending.delete(reply.id);
      done(reply);
    }
  };
  ws.onerror = null;
};

const stopPage = async (which) => {
  if (!ws) return;
  await evaluate(inPage(`(${pageVoice})('stop', ${JSON.stringify(which)})`), 1500);
};

const exit = (code, line) => {
  if (finished) return;
  finished = true;
  if (line) status(line);
  try {
    ws?.close();
  } catch (e) { /* exiting */ }
  process.exitCode = code;
  setTimeout(() => process.exit(code), 50);
};

const readText = async () => {
  const given = opt('--text', null);
  if (given !== null) return given;
  const parts = [];
  for await (const chunk of process.stdin) parts.push(chunk);
  return Buffer.concat(parts).toString('utf8');
};

async function stopMode() {
  try {
    await connect();
    await stopPage('*');
    exit(0, 'stopped');
  } catch (e) {
    exit(2, e.message);
  }
}

async function speakMode() {
  const text = (await readText()).trim();
  if (!text) return exit(2, 'nothing to read');
  try {
    await connect();
  } catch (e) {
    return exit(2, e.message);
  }
  const quit = async (signal) => {
    if (finished) return;
    await stopPage(session);
    exit(signal === 'SIGTERM' ? 143 : 130);
  };
  process.on('SIGTERM', () => quit('SIGTERM'));
  process.on('SIGINT', () => quit('SIGINT'));

  const t0 = Date.now();
  const started = await evaluate(inPage(`(${pageVoice})('start', ${JSON.stringify({ id: session, text, voice: VOICE, language: LANGUAGE })})`), 15000);
  if (started.error || !started.id) return exit(2, `could not start: ${started.error || JSON.stringify(started).slice(0, 200)}`);
  pageId = started.page;
  const notes = started.notes?.length ? `; ${started.notes.join(', ')}` : '';
  const what = `${started.voice}${started.language ? ` (${started.language})` : ''} at ${started.speed}, ${started.pieces} piece${started.pieces === 1 ? '' : 's'}${notes}`;

  const resampler = new Resampler(SERVICE_RATE, RATE);
  const pacer = new Pacer(RATE, LEAD);
  let queue = [];
  let queued = 0;
  let received = 0;     // bytes of service audio
  let emitted = 0;      // bytes out, at RATE
  let firstAt = null;
  let wavFd = null;
  let wavBytes = 0;
  let outBroken = false;
  if (WAV) wavFd = openSync(WAV, 'w');
  if (wavFd !== null) writeSync(wavFd, wavHeader(RATE, 0));
  process.stdout.on('error', () => {
    outBroken = true;
  });

  const out = (buf) => {
    if (!buf.length) return;
    if (wavFd !== null) {
      writeSync(wavFd, buf);
      wavBytes += buf.length;
      emitted += buf.length;
      return;
    }
    queue.push(buf);
    queued += buf.length;
  };
  // Sends what the pace allows (all of it with --wav, which isn't paced).
  const pump = () => {
    if (wavFd !== null || !queued) return;
    let room = pacer.allowed(Date.now());
    while (room > 0 && queue.length) {
      let buf = queue[0];
      if (buf.length > room) {
        queue[0] = buf.subarray(room);
        buf = buf.subarray(0, room);
      } else {
        queue.shift();
      }
      queued -= buf.length;
      room -= buf.length;
      pacer.sent(buf.length);
      emitted += buf.length;
      if (!outBroken) process.stdout.write(buf);
    }
  };
  const seconds = (bytes, rate = RATE) => (bytes / 2 / rate).toFixed(1);

  let last = null;
  let events = [];
  for (;;) {
    if (finished) return;
    const got = await evaluate(inPage('window.__sakamotoVoice ? window.__sakamotoVoice.drain(' + JSON.stringify(session) + ') : { state: "gone" }'), 5000);
    if (got.error && !got.state) {
      await stopPage(session);
      return exit(received ? 0 : 2, `stopped: ${got.error}`);
    }
    if (got.events?.length) events = events.concat(got.events);
    if (got.audio) {
      const pcm = Buffer.from(got.audio, 'base64');
      received += pcm.length;
      if (firstAt === null) {
        firstAt = Date.now();
        status('ready');
      }
      out(resampler.push(pcm));
    }
    pump();
    if (outBroken) {
      await stopPage(session);
      return exit(0, `the reader went away after ${seconds(emitted)} s`);
    }
    if (emitted / 2 / RATE > MAX_SECONDS) {
      await stopPage(session);
      return exit(0, `cut at ${MAX_SECONDS} s`);
    }
    if (got.state === 'closed' || got.state === 'gone') {
      last = got;
      break;
    }
    if (firstAt === null && Date.now() - t0 > FIRST_AUDIO_MS) {
      await stopPage(session);
      return exit(6, `no sound after ${FIRST_AUDIO_MS / 1000} s (${what}; events: ${events.join(', ') || 'none'})`);
    }
    await new Promise((r) => setTimeout(r, POLL_MS));
  }
  out(resampler.flush());
  // The rest, at its pace.
  while (queued && !outBroken && !finished) {
    pump();
    if (queued) await new Promise((r) => setTimeout(r, POLL_MS));
  }
  if (wavFd !== null) {
    writeSync(wavFd, wavHeader(RATE, wavBytes), 0, 44, 0);
    closeSync(wavFd);
  }
  const lead = firstAt === null ? '' : `, first audio after ${((firstAt - t0) / 1000).toFixed(1)} s`;
  const tail = `${what}; events: ${events.join(', ') || 'none'}; ${last.why || last.state}` +
    (last.error ? ` (${last.error})` : '') + (last.close !== undefined ? ` [close ${last.close}]` : '');
  if (!received) return exit(6, `no sound: ${tail}`);
  const done = () => exit(0, `read: ${seconds(emitted)} s of audio${lead}; ${tail}`);
  if (wavFd === null && !outBroken && process.stdout.writableLength) process.stdout.once('drain', done);
  else done();
}

if (args.includes('--stop')) stopMode();
else speakMode();
