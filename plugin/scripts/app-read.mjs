// Presses "Read aloud" on a response in the Claude desktop app, so it speaks in its own voice. It
// needs the app's Developer menu → Enable Main Process Debugger (a Node inspector on
// 127.0.0.1:9229, off again after the app restarts). Prints "clicked", or why not; exit status 0
// only when it clicked. Usage: node app-read.mjs [port] [key]
//
// key: the response's letters and digits, lowercased (speak.py's read_key): only the button of the
// message whose text contains it is pressed, so an earlier response is never read by mistake. The
// page may not have drawn the new response's button yet, so it looks again every half second for up
// to WAIT_MS. A pressed button is marked and never pressed again. Without a key, the last unmarked
// button is pressed.
const port = process.argv[2] || '9229';
const key = process.argv[3] || '';
const WAIT_MS = 8000;

// Runs in the page: finds the button (newest first, among the last few), or says why not.
const inPage = `(async () => {
  const key = ${JSON.stringify(key)};
  const norm = (s) => s.toLowerCase().replace(/[^\\p{L}\\p{N}]+/gu, '');
  const label = 'button[aria-label="Read aloud"]';
  // The message a button belongs to: its largest ancestor holding no other Read aloud button.
  const messageOf = (button) => {
    let el = button;
    while (el.parentElement && el.parentElement.querySelectorAll(label).length === 1) el = el.parentElement;
    return el;
  };
  const end = Date.now() + ${WAIT_MS};
  let why = 'no Read aloud button';
  for (;;) {
    const buttons = [...document.querySelectorAll(label)].slice(-4).reverse();
    for (const button of buttons) {
      if (button.dataset.sakamotoRead) { why = 'already read'; continue; }
      if (key && !norm(messageOf(button).innerText || '').includes(key)) { why = 'no matching message'; continue; }
      button.dataset.sakamotoRead = '1';
      button.click();
      return 'clicked';
    }
    if (Date.now() > end) return why;
    await new Promise((r) => setTimeout(r, 500));
  }
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

const done = (message) => { console.log(message); process.exit(message === 'clicked' ? 0 : 1); };
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
