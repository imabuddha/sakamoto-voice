// Presses "Read aloud" on a response in the Claude desktop app, so it speaks in its own voice. It
// needs the app's Developer menu → Enable Main Process Debugger (a Node inspector on
// 127.0.0.1:9229, off again after the app restarts). Prints "clicked", or why not; exit status 0
// only when it clicked. Usage: node app-read.mjs [port] [key] [wait_ms]
//
// key: the response's letters and digits, lowercased (speak.py's read_key): only the button of the
// message whose text contains it is pressed, so an earlier response is never read by mistake. The
// page may not have drawn the new response's button yet, so it looks again as soon as the page's
// elements change (a MutationObserver) and at least every POLL_MS, for up to wait_ms (WAIT_MS by default; speak.py looks again for a few seconds more when the first look
// found no matching message). A pressed button is marked and never pressed again. Without a key, the
// last unmarked button is pressed.
//
// A message's text is matched without its code blocks, and the key may have a few other letters
// among its own (a code block's label and Copy button): app-read-match.mjs.
import { norm, messageText, findKey } from './app-read-match.mjs';

const port = process.argv[2] || '9229';
const key = process.argv[3] || '';
const WAIT_MS = Number(process.argv[4]) > 0 ? Number(process.argv[4]) : 8000;
const POLL_MS = 50;         // longest pause between looks (an observer wakes it sooner when the page changes)
const EARLIER_TEXT = 12;    // letters and digits allowed before the reply (a label at most, not a message)
const matchCode = `const norm = ${norm}; const messageText = ${messageText}; const findKey = ${findKey};`;

// Runs in the page: finds the button (newest first, among the last few), or says why not.
const inPage = `(async () => {
  const key = ${JSON.stringify(key)};
  const EARLIER_TEXT = ${EARLIER_TEXT};
  const POLL_MS = ${POLL_MS};
  ${matchCode}
  const label = 'button[aria-label="Read aloud"]';
  // The message a button belongs to: its largest ancestor holding no other Read aloud button.
  const messageOf = (button) => {
    let el = button;
    while (el.parentElement && el.parentElement.querySelectorAll(label).length === 1) el = el.parentElement;
    return el;
  };
  const end = Date.now() + ${WAIT_MS};
  let why = 'no Read aloud button';
  // Sleeps up to POLL_MS, or until the page's elements change (a new message or button).
  let wake = null;
  const observer = new MutationObserver(() => { if (wake) wake(); });
  observer.observe(document.body, { childList: true, subtree: true });
  const pause = () => new Promise((r) => {
    const timer = setTimeout(() => { wake = null; r(); }, POLL_MS);
    wake = () => { clearTimeout(timer); wake = null; setTimeout(r, 20); };
  });
  try {
  for (;;) {
    const buttons = [...document.querySelectorAll(label)].slice(-4).reverse();
    for (const button of buttons) {
      // The mark names what was read: the app may reuse a button for a newer message.
      // The app may head a block with a label ("Claude responded"), which isn't earlier text.
      const message = messageOf(button);
      const text = messageText(message.innerText || '', [...message.querySelectorAll('pre')].map((p) => p.innerText || ''))
        .replace(/^clauderesponded/, '');
      const at = findKey(text, key);
      if (at < 0) {
        // For the log: the start and length of what the newest button's message holds.
        if (button === buttons[0]) {
          why = 'no matching message; the newest holds ' + text.length + ' chars: ' + text.slice(0, 40);
        }
        continue;
      }
      if (button.dataset.sakamotoRead && button.dataset.sakamotoRead === text.slice(0, 80)) {
        why = 'already read'; continue;
      }
      // The button reads its whole block. When this reply comes well after the block's start, the
      // block also holds earlier text (a turn that followed a notice, not a new message), which the
      // app would read again first: don't press; the Mac's or the phone's voices read the reply.
      // A turn the user wrote into while it ran heads its block with a label that repeats the
      // reply's first sentence ("Claude responded: 08:18 Thanks, …"): not earlier text either.
      const repeatsReply = at > 0 && key.startsWith(text.slice(0, at));
      if (at > EARLIER_TEXT && !repeatsReply) return 'earlier text first (' + at + ' chars before this reply: ' + text.slice(0, Math.min(at, 40)) + ')';
      button.dataset.sakamotoRead = text.slice(0, 80);
      button.click();
      return 'clicked' + (key ? ' (at ' + at + ' of ' + text.length + ')' : '');
    }
    if (Date.now() > end) {
      // For the log, when the newest response has no Read aloud button: the page's last labeled
      // buttons (a reading in progress may show a different control).
      if (why === 'already read') {
        const labels = [...document.querySelectorAll('button[aria-label]')].slice(-8).map((b) => b.getAttribute('aria-label'));
        why += '; last buttons: ' + labels.join(' | ');
      }
      return why;
    }
    await pause();
  }
  } finally { observer.disconnect(); }
})()`;

// Runs in the app's main process: finds the session page (the focused one when there are several).
const expression = `(async () => {
  const req = (typeof require === 'function') ? require : process.mainModule.require.bind(process.mainModule);
  const { webContents } = req('electron');
  const pages = webContents.getAllWebContents().filter(w => w.getURL().includes('claude.ai/epitaxy/'));
  const page = pages.find(w => w.isFocused()) || pages[0];
  if (!page) return 'no session page';
  return await page.executeJavaScript(${JSON.stringify(inPage)});
})()`;

const done = (message) => { console.log(message); process.exit(String(message).startsWith('clicked') ? 0 : 1); };
setTimeout(() => done('timeout'), WAIT_MS + 4000);
try {
  const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  if (!targets.length) done('no inspector target');
  const ws = new WebSocket(targets[0].webSocketDebuggerUrl);
  ws.onopen = () => ws.send(JSON.stringify({ id: 1, method: 'Runtime.evaluate',
    params: { expression, awaitPromise: true, returnByValue: true } }));
  ws.onmessage = (m) => {
    const reply = JSON.parse(m.data);
    if (reply.id === 1) done(reply.result?.result?.value ?? JSON.stringify(reply.result ?? reply).slice(0, 200));
  };
  ws.onerror = () => done('inspector connection failed');
} catch (e) {
  done(`debugger not reachable (${e.cause?.code || e.message})`);
}
