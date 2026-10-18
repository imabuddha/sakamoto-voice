// Presses "Read aloud" on a response in the Claude desktop app, so it speaks in its own voice. It
// needs the app's Developer menu → Enable Main Process Debugger (a Node inspector on
// 127.0.0.1:9229, off again after the app restarts). Prints "clicked", or why not; exit status 0
// only when it clicked. Usage: node app-read.mjs [port] [key] [wait_ms]
//
// key: the response's letters and digits, lowercased (speak.py's read_key): only the button of the
// message whose text contains it is pressed, so an earlier response is never read by mistake. The
// page may not have drawn the new response's button yet, so it looks again every POLL_MS, for up to
// wait_ms (WAIT_MS by default; speak.py looks again for a few seconds more when the first look
// found no matching message). When the reply is drawn but the app holds its Read aloud button back (it
// adds it only at the next prompt while background tasks run: see inPage), it gives up after
// BUSY_GRACE_MS instead, and says so. The pauses run here, in the app's main process, and each look is one
// synchronous call into the page: a hidden page's own timers are throttled to a crawl (see
// watchPage). A pressed button is marked and never pressed again. Without a key, the last
// unmarked button is pressed.
//
// A message's text is matched without its code blocks, and the key may have a few other letters
// among its own (a code block's label and Copy button): app-read-match.mjs.
import { norm, stripStatus, messageText, findKey, watchPage } from './app-read-match.mjs';

const port = process.argv[2] || '9229';
const key = process.argv[3] || '';
const WAIT_MS = Number(process.argv[4]) > 0 ? Number(process.argv[4]) : 8000;
const POLL_MS = 50;         // pause between looks, taken in the main process (the page's timers may be throttled)
const EARLIER_TEXT = 12;    // letters and digits allowed before the reply (a label at most, not a message)
const BUSY_GRACE_MS = 2500; // when the reply is drawn but its button is held back (see inPage), give up this soon
const matchCode = `const norm = ${norm}; const stripStatus = ${stripStatus}; const messageText = ${messageText}; const findKey = ${findKey};`;

// Runs in the page, once and at once (no timers, no observers: a hidden page throttles them, and
// the loop would hang): finds the button (newest first, among the last few) and presses it, or says
// why not. Returns { done: the final answer } or { why: the reason so far }.
const inPage = `(() => {
  const key = ${JSON.stringify(key)};
  const EARLIER_TEXT = ${EARLIER_TEXT};
  const BUSY_GRACE_MS = ${BUSY_GRACE_MS};
  ${matchCode}
  const label = 'button[aria-label="Read aloud"]';
  // The message a button belongs to. The app marks each reply as data-testid="assistant-message"
  // (a row of only a background-task notice, "2 background commands running", has one too, with its
  // own Read aloud button); without that mark, the largest ancestor holding no other Read aloud button.
  const messageOf = (button) => {
    const marked = button.closest('[data-testid="assistant-message"]');
    if (marked) return marked;
    let el = button;
    while (el.parentElement && el.parentElement.querySelectorAll(label).length === 1) el = el.parentElement;
    return el;
  };
  // The reply's text and code blocks without the app's own chrome: elements marked data-find-omitted
  // (task cards, tool calls, the "Claude responded" heading) and the message-actions toolbar. A
  // detached copy, so the page is untouched. stripStatus catches status text outside such elements.
  const contentOf = (message) => {
    const copy = message.cloneNode(true);
    for (const chrome of copy.querySelectorAll('[data-find-omitted], [role="toolbar"], [data-testid="message-actions"]')) chrome.remove();
    return { full: copy.textContent || '', code: [...copy.querySelectorAll('pre')].map((p) => p.textContent || '') };
  };
  let why = null;
  const buttons = [...document.querySelectorAll(label)].slice(-4).reverse();
  for (const button of buttons) {
    // The mark names what was read: the app may reuse a button for a newer message.
    // The app may head a block with a label ("Claude responded"), which isn't earlier text.
    const message = messageOf(button);
    const content = contentOf(message);
    const text = messageText(content.full, content.code).replace(/^clauderesponded/, '');
    const at = findKey(text, key);
    if (at < 0) {
      // For the log: the start and length of what the newest button's message holds.
      // (a status-only row, with no text of its own, doesn't count as the newest message)
      if (text && !why) why = 'no matching message; the newest holds ' + text.length + ' chars: ' + text.slice(0, 40);
      continue;
    }
    if (button.dataset.sakamotoRead && button.dataset.sakamotoRead === text.slice(0, 80)) {
      // For the log: the page's last labeled buttons (a reading in progress may show a different control).
      const labels = [...document.querySelectorAll('button[aria-label]')].slice(-8).map((b) => b.getAttribute('aria-label'));
      why = 'already read; last buttons: ' + labels.join(' | ');
      continue;
    }
    // The button reads its whole block. When this reply comes well after the block's start, the
    // block also holds earlier text (a turn that followed a notice, not a new message), which the
    // app would read again first: don't press; the Mac's or the phone's voices read the reply.
    // A turn the user wrote into while it ran heads its block with a label that repeats the
    // reply's first sentence ("Claude responded: 08:18 Thanks, …"): not earlier text either.
    const repeatsReply = at > 0 && key.startsWith(text.slice(0, at));
    if (at > EARLIER_TEXT && !repeatsReply) return { done: 'earlier text first (' + at + ' chars before this reply: ' + text.slice(0, Math.min(at, 40)) + ')' };
    button.dataset.sakamotoRead = text.slice(0, 80);
    button.click();
    return { done: 'clicked' + (key ? ' (at ' + at + ' of ' + text.length + ')' : '') };
  }
  // The reply may be drawn with no button at all. Measured 2026-10-18 (after the app's layout update),
  // while background tasks ran (the app's Stop button stayed shown): a finished reply is drawn at once
  // as a "live" message (data-busy), then, a few seconds on, as an ordinary one, but either way
  // without its actions toolbar, so without Read aloud; the toolbar comes only when the next prompt
  // arrives: 11 of 11 times within 1 s of the next UserPromptSubmit, 2 to 23 s after the text. So
  // waiting is useless: say so, and let the caller give up soon (the first pass above found only the
  // previous reply's button: "no matching message", for the whole wait).
  if (key) {
    for (const message of [...document.querySelectorAll('[data-testid="assistant-message"]')].slice(-2).reverse()) {
      if (message.querySelector(label)) continue;     // looked at above
      const content = contentOf(message);
      const text = messageText(content.full, content.code).replace(/^clauderesponded/, '');
      if (!text || findKey(text, key) < 0) continue;
      const stop = document.querySelector('button[aria-label^="Stop"]');
      return { why: 'reply drawn without Read aloud: the app keeps its toolbar back' +
        (message.hasAttribute('data-busy') ? ' (live)' : '') +
        (stop ? ' (Stop button shown: "' + stop.getAttribute('aria-label') + '")' : ''), grace: BUSY_GRACE_MS };
    }
  }
  return { why };
})()`;

// Runs in the app's main process: finds the session page (the focused one when there are several),
// then looks at it every POLL_MS (watchPage) until the button is pressed or WAIT_MS has passed.
const expression = `(async () => {
  const req = (typeof require === 'function') ? require : process.mainModule.require.bind(process.mainModule);
  const { webContents } = req('electron');
  const pages = webContents.getAllWebContents().filter(w => w.getURL().includes('claude.ai/epitaxy/'));
  const page = pages.find(w => w.isFocused()) || pages[0];
  if (!page) return 'no session page';
  // A locked screen or covered window hides the page: it stops rendering new replies. Keep it
  // running (this also keeps document.visibilityState "visible"); it resets when the app restarts.
  page.setBackgroundThrottling(false);
  const watchPage = ${watchPage};
  return await watchPage(() => page.executeJavaScript(${JSON.stringify(inPage)}), ${WAIT_MS}, ${POLL_MS});
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
