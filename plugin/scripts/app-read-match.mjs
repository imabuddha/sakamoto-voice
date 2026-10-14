// How app-read.mjs finds a response on the Claude app's page: shared with the tests (node imports it;
// app-read.mjs puts these functions into the page as text), so they use nothing from outside their
// bodies but each other.
//
// Why (2026-10-14 06:25 and 14:35, after tool-heavy turns and a reply with a code block): the key is
// the reply's opening letters and digits, and the page's text of a message holds more than the reply
// does: a code block's code, its language label and Copy button, a tool call's lines. Exact matching
// then missed it ("no matching message"), and the phone's own voice read the reply instead.

// Letters and digits only, lowercased.
export function norm(s) {
  return String(s || '').toLowerCase().replace(/[^\p{L}\p{N}]+/gu, '');
}

// A message's text for matching: its normalized text, without what its code blocks (`pre`) hold;
// speak.py's key leaves fenced code out too.
export function messageText(full, codeBlocks) {
  let text = norm(full);
  for (const code of codeBlocks) {
    const c = norm(code);
    if (c.length >= 4) text = text.split(c).join('');
  }
  return text;
}

// Where the key begins in the text, or -1: exactly; else as the key's letters in order with a few
// others among them (a code block's label, a button's text: at most `slack` in all, and the first
// and last letters the key's own), the earliest such place.
export function findKey(text, key, slack = 24) {
  if (!key) return 0;
  const exact = text.indexOf(key);
  if (exact >= 0) return exact;
  for (let start = text.indexOf(key[0]); start >= 0; start = text.indexOf(key[0], start + 1)) {
    let i = start;
    let k = 0;
    let extra = 0;
    while (k < key.length && i < text.length && extra <= slack) {
      if (text[i] === key[k]) k += 1; else extra += 1;
      i += 1;
    }
    if (k === key.length && extra <= slack) return start;
  }
  return -1;
}
