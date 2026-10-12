#!/usr/bin/env python3
"""Miss Sakamoto's voice: speaks each finished Claude Code response aloud with macOS `say`, on the
Mac, on an iPhone running the Sakamoto Voice app (ios/), or both.

Run as (or, for the commands after the first two, `sakamoto ...`: bin/sakamoto, linked into the
PATH as README.md describes):
  speak.py                 as a Stop hook: reads the hook's JSON on stdin, finds the response's final
                           text, and hands it to a detached speaker so the hook returns at once.
  speak.py --speak FILE    the detached speaker (internal): reads FILE, speaks it, deletes it.
  speak.py on|off|stop|status|test ["text"]
                           the switch: on and off persist; stop silences the current response.
  speak.py pair CODE       pairs with the phone: stores its 6-digit code and finds it on the network.
  speak.py output mac|phone|both|app|app-phone
                           where responses are spoken.
  speak.py phone-mode text|audio
                           what the phone gets: text, spoken in its own voices, or audio rendered
                           here in the Mac's voices (`say -o`), such as a Siri system voice.
  speak.py phone-test ["text"]
                           sends a line to the phone now and reports what happened.

Settings live in ~/.config/sakamoto-voice/config.json (created on first use):
  enabled   true/false
  voice_en  the English voice, e.g. "Zoe (Premium)"; empty uses the system voice (Spoken Content's
            System Voice, which can be a Siri voice such as Maeve, the only way `say` reaches one).
            voice_ja the Japanese one, e.g. "Kyoko (Enhanced)". A voice that isn't installed falls
            back to the system voice.
  default_lang  the Mac's voice for text that isn't Japanese script (Japanese script always gets
            voice_ja): "auto" (the default; the macOS system language's, English unless it's
            Japanese), "en", or "ja" (Kyoko reads everything, English included). It applies to the
            Mac's own speech and to audio rendered for the phone; for text, the phone uses its own
            setting (Default Voice for Other Text) instead.
  rate      words per minute (say -r); 0 keeps the voice's own pace.
  device    a CoreAudio output device name or ID for `say -a` (a paired Bluetooth speaker, say);
            empty uses the current output. `say -a '?'` lists them.
  max_chars a response longer than this is cut there, with a note that the rest is on screen.
  output    "mac" (the default), "phone", "both", "app", "app-both", or "app-phone".
            "app": the Claude desktop app reads the response in its own voice (its Read aloud
            button, pressed through the app's Main Process Debugger, which Developer mode offers;
            app-read.mjs). When the debugger isn't on, the Mac's voice speaks instead.
            "app-both": the Claude app's voice on the Mac, and the text to the phone (its own voices).
            "app-phone": the same voice, streamed live to the phone while the Mac stays silent:
            app-voice-tap (mac/build.sh builds it) taps the Claude app's audio, muted on the Mac,
            and streams it to the phone, which also shows the text. When the debugger is off, the
            tool isn't built, or no sound comes, the phone gets the text instead (its own voices).
  app_voice_tap  where app-voice-tap is, when it's not in ~/.local/bin or on the PATH.
  dev_path  for working on the plugin: a checkout's plugin/ folder. The installed (cached) copy then
            runs that checkout's speak.py instead, so edits there take effect with the next
            response, without a plugin update or a restart (changes to hooks.json still need both).
  phone_mode  "text" (the default; the phone speaks it in its own voices) or "audio" (rendered here
            with voice_en, voice_ja, and rate, and played on the phone).
  phone_token the phone's 6-digit pairing code (speak.py pair sets it).
  phone     the phone's "host:port", found with Bonjour (dns-sd) and kept here; found again when a
            send fails. phone_name is its Bonjour name.
Voice markers in a response switch voices: 〔en〕 to voice_en and 〔ja〕 to voice_ja, from the marker
to the next one or to the end of its paragraph (a blank line), where the default voice resumes.
Markers are never spoken or shown; unknown ones, such as 〔xx〕, are dropped. They hold on the phone
too, whatever its setting.
A new response interrupts the one still being spoken, on the Mac and on the phone. Sending to the
phone happens in the detached speaker; its failures are silent but logged to speak.log here.
"""
import base64, json, os, pty, re, select, shutil, signal, socket, subprocess, sys, tempfile, threading
import time, wave

HOME = os.path.expanduser('~/.config/sakamoto-voice')
CONFIG = os.path.join(HOME, 'config.json')
PIDFILE = os.path.join(HOME, 'speaker.pid')
LOG = os.path.join(HOME, 'speak.log')
LOG_MAX = 64 * 1024          # then speak.log becomes speak.log.1, replacing the one before
DEFAULTS = {'enabled': True, 'voice_en': '', 'voice_ja': 'Kyoko', 'default_lang': 'auto', 'rate': 0,
            'device': '', 'max_chars': 6000,
            'output': 'mac', 'phone_mode': 'text', 'phone_token': '', 'phone': '', 'phone_name': '',
            'app_voice_tap': '', 'dev_path': ''}
OUTPUTS = ('mac', 'phone', 'both', 'app', 'app-both', 'app-phone')
PHONE_OUTPUTS = ('phone', 'both', 'app-both', 'app-phone')       # the outputs a stop also tells the phone
PHONE_MODES = ('text', 'audio')


def config():
    os.makedirs(HOME, exist_ok=True)
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG) as f:
            cfg.update(json.load(f))
    except FileNotFoundError:
        save(cfg)
    except (OSError, ValueError):
        pass
    return cfg


def save(cfg):
    os.makedirs(HOME, exist_ok=True)
    with open(CONFIG, 'w') as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
        f.write('\n')


def remember(**changes):
    """Updates only these settings, on the file as it is now (the switch may have changed others)."""
    cfg = config()
    cfg.update(changes)
    save(cfg)
    return cfg


def log(message):
    """One line in speak.log; never fails. The log is kept small: past LOG_MAX it starts over,
    keeping the one before as speak.log.1."""
    try:
        os.makedirs(HOME, exist_ok=True)
        if os.path.exists(LOG) and os.path.getsize(LOG) > LOG_MAX:
            os.replace(LOG, LOG + '.1')
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(time.strftime('%Y-%m-%d %H:%M:%S ') + message.replace('\n', ' ') + '\n')
    except OSError:
        pass


# ---- Finding the response -------------------------------------------------------------------

def is_prompt(entry):
    """A real user turn (typed text), not a tool result fed back to the model."""
    if entry.get('type') != 'user' or entry.get('isSidechain'):
        return False
    content = entry.get('message', {}).get('content')
    if isinstance(content, str):
        return True
    return isinstance(content, list) and any(b.get('type') == 'text' for b in content)


def final_text(transcript_path):
    """The text the model wrote after its last tool call in the current turn."""
    try:
        with open(transcript_path, encoding='utf-8') as f:
            lines = f.readlines()[-400:]
    except OSError:
        return ''
    pieces = []
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if entry.get('isSidechain'):
            continue
        if is_prompt(entry):
            break
        if entry.get('type') != 'assistant':
            continue
        content = entry.get('message', {}).get('content')
        if not isinstance(content, list):
            continue
        if any(b.get('type') == 'tool_use' for b in content):
            if pieces:
                break          # text before a tool call was an interim note, not the answer
            continue
        texts = [b.get('text', '') for b in content if b.get('type') == 'text']
        if texts:
            pieces.insert(0, '\n'.join(texts))
    return '\n\n'.join(pieces).strip()


# ---- Making it speakable --------------------------------------------------------------------

KEYS = {'⌘': ' command ', '⌥': ' option ', '⌃': ' control ', '⇧': ' shift ', '⏎': ' return ',
        '→': ' right arrow ', '←': ' left arrow ', '↑': ' up arrow ', '↓': ' down arrow '}
EMOJI = re.compile('[\U0001F000-\U0001FAFF☀-➿️‍]')


def speakable(text):
    text = re.sub(r'```.*?```', ' (code omitted) ', text, flags=re.S)
    text = re.sub(r'`([^`]*)`', r'\1', text)
    text = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', text)               # images
    text = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', text)            # links keep their words
    text = re.sub(r'https?://\S+', 'a link', text)
    lines = []
    for line in text.splitlines():
        s = line.strip()
        if re.fullmatch(r'\|?[\s:|-]+\|?', s) and '-' in s:
            continue                                                # a table's rule
        if s.startswith('|'):
            s = ', '.join(c.strip() for c in s.strip('|').split('|') if c.strip()) + '.'
        s = re.sub(r'^#{1,6}\s*', '', s)
        s = re.sub(r'^>\s?', '', s)
        s = re.sub(r'^[-*•]\s+', '', s)
        lines.append(s)
    text = '\n'.join(lines)
    text = re.sub(r'(\*\*|__|\*|_)(?=\S)(.+?)(?<=\S)\1', r'\2', text)  # bold and italics
    for key, word in KEYS.items():
        text = text.replace(key, word)
    text = EMOJI.sub('', text)
    return re.sub(r'[ \t]+', ' ', text).strip()


CJK = re.compile(r'([　-ヿ㐀-鿿豈-﫿＀-￯]'
                 r'[　-ヿ㐀-鿿豈-﫿＀-￯\s、。！？0-9]*)')


LANGS = ('en', 'ja')
# The tag for text in no particular voice (neither Japanese script nor marked): the phone reads it
# in the voice its own setting picks. (Phones before 0.2.5 read anything not "ja" in English.)
DEFAULT = 'default'
# A voice marker: 〔en〕 or 〔ja〕 (any short ASCII code is a marker; unknown ones are only
# stripped). Japanese in tortoise-shell brackets, such as 〔注〕, is ordinary text.
MARKER = re.compile(r'〔\s*([A-Za-z][A-Za-z-]{0,9})\s*〕')
PARAGRAPH = re.compile(r'\n[ \t]*\n\s*')     # a blank line (or several) ends a paragraph


def script_spans(text, other='en'):
    """Raw (lang, text) spans by script: Japanese script is "ja"; everything else is `other`."""
    out, pos = [], 0
    for m in CJK.finditer(text):
        if m.start() > pos:
            out.append((other, text[pos:m.start()]))
        out.append(('ja', m.group(1)))
        pos = m.end()
    if pos < len(text):
        out.append((other, text[pos:]))
    return out


def tidy(spans, absorb=False):
    """Joins neighboring spans in the same voice, then trims them and drops the ones with nothing
    but spaces and punctuation. With `absorb`, such a span joins the one before it instead, so the
    spans on either side of it can join too."""
    merged = []
    for lang, t in spans:
        if merged and (merged[-1][0] == lang or (absorb and not t.strip(' \n\t.,;:'))):
            merged[-1] = (merged[-1][0], merged[-1][1] + t)
        else:
            merged.append((lang, t))
    return [(lang, t.strip()) for lang, t in merged if t.strip(' \n\t.,;:')]


def segments(text, other='en'):
    """(lang, text) runs by script alone: Japanese script to the Japanese voice, the rest to
    `other`'s (the app's LanguageSplitter does the same with "en")."""
    return tidy(script_spans(text, other))


def voice_runs(text, default_lang=DEFAULT):
    """(lang, text) runs for the voices, with the voice markers applied and removed. Text is
    tagged `default_lang` ("en", "ja", or DEFAULT, which leaves the choice to the phone); 〔en〕 or
    〔ja〕 switches to that voice from there to the next marker or the end of the paragraph (a blank
    line), where the default resumes. Japanese script is always "ja". Unknown markers (〔xx〕) are
    dropped and change nothing."""
    default_lang = default_lang if default_lang in LANGS else DEFAULT
    spans, pos = [], 0
    for brk in PARAGRAPH.finditer(text + '\n\n'):
        paragraph, gap = text[pos:brk.start()], text[brk.start():brk.end()]
        pos = brk.end()
        lang, at = default_lang, 0
        for m in MARKER.finditer(paragraph):
            spans += script_spans(paragraph[at:m.start()], lang)
            code = m.group(1).lower()
            lang = code if code in LANGS else lang
            at = m.end()
        spans += script_spans(paragraph[at:], lang)
        if spans:
            spans[-1] = (spans[-1][0], spans[-1][1] + gap)   # the break stays with what it ends
    return tidy(spans, absorb=True)


def strip_markers(text):
    """The text without its voice markers, for the screen (the spaces they leave tidied)."""
    text = re.sub(r'[ \t]{2,}', ' ', MARKER.sub('', text))
    return '\n'.join(line.strip() for line in text.split('\n')).strip()


def system_lang():
    """"ja" when the macOS system language (the first of AppleLanguages) is Japanese, else "en"."""
    try:
        out = subprocess.run(['defaults', 'read', '-g', 'AppleLanguages'], stdin=subprocess.DEVNULL,
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return 'en'
    m = re.search(r'[A-Za-z]{2,3}', out)
    return 'ja' if m and m.group(0).lower() == 'ja' else 'en'


def mac_lang(cfg):
    """The Mac's default voice: default_lang when it's "en" or "ja", else ("auto") the system's."""
    lang = cfg.get('default_lang')
    return lang if lang in LANGS else system_lang()


def prepare(text, cfg):
    """For speakable text: (the text for the screen, the Mac's runs, the phone's runs). The Mac's
    are in its default_lang; the phone's leave unmarked text to the phone's own default (DEFAULT)."""
    return strip_markers(text), voice_runs(text, mac_lang(cfg)), voice_runs(text, DEFAULT)


# ---- The phone ------------------------------------------------------------------------------
#
# The Sakamoto Voice app listens for one JSON message per TCP connection (the sender writes it and
# closes its side) and answers with one JSON line, {"ok": true, ...} or {"ok": false, "error": ...};
# see ios/SakamotoVoiceKit/Sources/SakamotoVoiceKit/Message.swift. It advertises itself with
# Bonjour, which macOS's dns-sd browses and resolves without any Python packages.

SERVICE = '_sakamotovoice._tcp'


def normalize_code(code):
    """The pairing code's digits ("123 456" is "123456"); empty unless there are exactly six."""
    digits = re.sub(r'[\s-]', '', code or '')
    return digits if re.fullmatch(r'[0-9]{6}', digits) else ''


def run_dns_sd(args, seconds, done=None):
    """dns-sd's output for a few seconds (it never exits by itself), or until `done` is seen. It
    buffers its output into a pipe, so it gets a pseudo-terminal instead."""
    try:
        master, slave = pty.openpty()
    except OSError:
        return ''
    try:
        proc = subprocess.Popen(['dns-sd'] + args, stdin=subprocess.DEVNULL, stdout=slave, stderr=slave)
    except OSError:
        os.close(master)
        os.close(slave)
        return ''
    os.close(slave)
    out, end = b'', time.monotonic() + seconds
    try:
        while (left := end - time.monotonic()) > 0:
            ready, _, _ = select.select([master], [], [], left)
            if not ready:
                continue
            try:
                chunk = os.read(master, 4096)
            except OSError:
                break
            if not chunk:
                break
            out += chunk
            if done and done in out.decode('utf-8', 'replace'):
                break
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            proc.kill()
        os.close(master)
    return out.decode('utf-8', 'replace')


BROWSE_LINE = re.compile(r'^\S+\s+(Add|Rmv)\s+\d+\s+\d+\s+\S+\s+(\S+)\s+(.+?)\s*$')


def parse_browse(output, service=SERVICE):
    """The instance names `dns-sd -B` lists as present, in order of appearance."""
    names = []
    for line in output.splitlines():
        m = BROWSE_LINE.match(line)
        if not m or m.group(2).rstrip('.') != service:
            continue
        action, name = m.group(1), m.group(3)
        if action == 'Add' and name not in names:
            names.append(name)
        elif action == 'Rmv' and name in names:
            names.remove(name)
    return names


def parse_lookup(output):
    """"host:port" from `dns-sd -L`'s "can be reached at host.local.:47811", or ''."""
    m = re.search(r'can be reached at (\S+?)\.?:(\d+)\b', output)
    return f'{m.group(1)}:{m.group(2)}' if m else ''


def browse(seconds=2.0):
    return parse_browse(run_dns_sd(['-B', SERVICE, 'local.'], seconds))


def lookup(name, seconds=3.0):
    return parse_lookup(run_dns_sd(['-L', name, SERVICE, 'local.'], seconds, done='can be reached at'))


def split_address(address):
    host, _, port = address.rpartition(':')
    return host, int(port)


def message(token, kind, text='', runs=None, audio=None, fmt='m4a'):
    """One message for the phone, as bytes."""
    msg = {'token': token, 'kind': kind}
    if text:
        msg['text'] = text
    if runs:
        msg['lang_runs'] = [{'lang': lang, 'text': chunk} for lang, chunk in runs]
    if audio is not None:
        msg['audio_b64'] = base64.b64encode(audio).decode('ascii')
        msg['format'] = fmt
    return json.dumps(msg, ensure_ascii=False).encode('utf-8')


def exchange(address, payload, timeout=10.0):
    """Sends one message and returns the phone's answer (a dict). Raises OSError when the phone
    can't be reached and ValueError when its answer isn't JSON."""
    host, port = split_address(address)
    with socket.create_connection((host, port), timeout=min(timeout, 4.0)) as sock:
        sock.settimeout(timeout)
        sock.sendall(payload)
        sock.shutdown(socket.SHUT_WR)
        reply = b''
        while chunk := sock.recv(4096):
            reply += chunk
    return json.loads(reply.decode('utf-8') or 'null') or {}


def find_phone(token, browse_seconds=2.0):
    """(name, "host:port") of the phone that accepts this pairing code, or None. Every phone on
    the network running the app is asked (with a ping), so two phones are no trouble."""
    for name in browse(browse_seconds):
        address = lookup(name)
        if not address:
            log(f'phone: {name!r} did not resolve')
            continue
        try:
            ack = exchange(address, message(token, 'ping'), timeout=4.0)
        except (OSError, ValueError) as e:
            log(f'phone: {name!r} at {address}: {e}')
            continue
        if ack.get('ok'):
            return name, address
        log(f'phone: {name!r} at {address} refused the code: {ack.get("error")}')
    return None


def send_to_phone(payload, timeout=10.0):
    """Sends to the remembered phone, finding it again (and remembering it) when that fails.
    Returns the phone's answer, or None when no phone could be reached; logs what went wrong."""
    cfg = config()
    token = cfg.get('phone_token', '')
    if not token:
        log('phone: not paired (speak.py pair CODE)')
        return None
    address = cfg.get('phone', '')
    if address:
        try:
            return exchange(address, payload, timeout)
        except (OSError, ValueError) as e:
            log(f'phone: {address}: {e}; looking for it again')
    found = find_phone(token)
    if not found:
        log('phone: no phone with Sakamoto Voice answered with the pairing code')
        return None
    name, address = found
    remember(phone=address, phone_name=name)
    log(f'phone: found {name!r} at {address}')
    try:
        return exchange(address, payload, timeout)
    except (OSError, ValueError) as e:
        log(f'phone: {address}: {e}')
        return None


def concat_wavs(paths, out_path, gap=0.12):
    """Joins WAVs of one format into one, with a short pause between them (as between `say`s)."""
    with wave.open(out_path, 'wb') as out:
        params = None
        for path in paths:
            with wave.open(path, 'rb') as w:
                if params is None:
                    params = w.getparams()
                    out.setparams(params)
                elif w.getparams()[:3] != params[:3]:
                    continue
                else:
                    out.writeframes(b'\0' * int(gap * params.framerate) * params.sampwidth * params.nchannels)
                out.writeframes(w.readframes(w.getnframes()))
        if params is None:
            out.setparams((1, 2, 22050, 0, 'NONE', 'not compressed'))


def render_audio(chunks, cfg, voices):
    """The response in the Mac's voices (the same choices as speaking it here), as AAC in an M4A."""
    work = tempfile.mkdtemp(prefix='sakamoto-voice-')
    try:
        parts = []
        for i, (lang, chunk) in enumerate(chunks):
            path = os.path.join(work, f'{i}.wav')
            cmd = say_command(cfg, voices, lang, play=False) + ['--data-format=LEI16@22050', '-o', path, chunk]
            if subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True).returncode == 0:
                parts.append(path)
        if not parts:
            return None
        joined, m4a = os.path.join(work, 'all.wav'), os.path.join(work, 'all.m4a')
        concat_wavs(parts, joined)
        subprocess.run(['afconvert', '-f', 'm4af', '-d', 'aac', joined, m4a],
                       stdin=subprocess.DEVNULL, capture_output=True, check=True)
        with open(m4a, 'rb') as f:
            return f.read()
    except (OSError, subprocess.CalledProcessError, wave.Error) as e:
        log(f'phone: rendering audio failed: {e}')
        return None
    finally:
        shutil.rmtree(work, ignore_errors=True)


def phone_payload(cfg, text, runs, mac_runs, voices):
    """The message for this response: text and its language runs (`runs`, with unmarked text left
    to the phone's default), or audio rendered here from `mac_runs` (in the Mac's default)."""
    token = cfg.get('phone_token', '')
    if cfg.get('phone_mode') == 'audio':
        audio = render_audio(mac_runs, cfg, voices)
        if audio:
            return message(token, 'audio', text=text, audio=audio, fmt='m4a')
        log('phone: no audio; sending text instead')
    return message(token, 'text', text=text, runs=runs)


def deliver_to_phone(cfg, text, runs, mac_runs, voices):
    try:
        ack = send_to_phone(phone_payload(cfg, text, runs, mac_runs, voices),
                            timeout=30.0 if cfg.get('phone_mode') == 'audio' else 10.0)
        if ack is not None and not ack.get('ok'):
            log(f'phone: refused: {ack.get("error")}')
    except Exception as e:   # the speaker never fails loudly; the log says why
        log(f'phone: {type(e).__name__}: {e}')


def stop_phone(cfg):
    """Silences the phone, quickly and only at its remembered address."""
    if cfg.get('output') in PHONE_OUTPUTS and cfg.get('phone') and cfg.get('phone_token'):
        try:
            exchange(cfg['phone'], message(cfg['phone_token'], 'stop'), timeout=1.5)
        except (OSError, ValueError) as e:
            log(f'phone: stop: {e}')


# ---- Speaking -------------------------------------------------------------------------------

def stop_speaker():
    try:
        with open(PIDFILE) as f:
            pid = int(f.read().strip())
        os.killpg(pid, signal.SIGTERM)
    except (OSError, ValueError):
        pass
    try:
        os.remove(PIDFILE)
    except OSError:
        pass


def launch(text):
    """Hand text to a detached speaker, silencing any earlier one."""
    stop_speaker()
    fd, path = tempfile.mkstemp(prefix='sakamoto-voice-', suffix='.txt')
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(text)
    subprocess.Popen([sys.executable, os.path.abspath(__file__), '--speak', path],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def read_key(text, length=40):
    """The start of a response as app-read.mjs looks for it on the page: its letters and digits,
    lowercased, with what the page doesn't show as text (link and image addresses) left out."""
    text = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', text)
    text = re.sub(r'\]\([^)]*\)', ']', text)
    return ''.join(c for c in text.lower() if c.isalnum())[:length]


def app_read(text, delay=0.5):
    """Presses Read aloud on this response (the raw text) in the Claude app; True when it clicked.
    app-read.mjs waits for the page to draw the response's button, so the delay is only a head start."""
    time.sleep(delay)
    node = shutil.which('node') or next((p for p in ('/opt/homebrew/bin/node', '/usr/local/bin/node')
                                          if os.path.exists(p)), None)
    if not node:
        log('app: node not found')
        return False
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app-read.mjs')
    try:
        result = subprocess.run([node, script, '9229', read_key(text)], capture_output=True, text=True,
                                timeout=20)
    except (OSError, subprocess.TimeoutExpired) as e:
        log(f'app: {e}')
        return False
    log(f'app: {(result.stdout or result.stderr).strip()[:200]} ({read_key(text, 24)})')
    return result.returncode == 0


# ---- The Claude app's voice on the phone (output app-phone) ---------------------------------
#
# app-voice-tap (mac/AppVoiceTap, built by mac/build.sh) taps the Claude app's audio with a Core
# Audio process tap, muted on the Mac's speakers, and streams it live to the phone. It connects to
# the phone, starts the tap, and prints "ready"; then Read aloud is pressed; it streams until the
# app has been quiet for a moment, prints one line, and exits (status 6: no sound came).

APP_READ_DELAY = 0.5      # seconds from the Stop hook to looking for Read aloud (app-read.mjs waits for it)
TAP_WAIT_START = 10       # seconds the tap waits for the app's voice after "ready"
TAP_MAX_SECONDS = 900     # the longest reading streamed (max_chars of 6000 is about 7 minutes)
TAP_READY_TIMEOUT = 8     # seconds to connect to the phone and start the tap
TAP_NO_SOUND = 6          # app-voice-tap's exit status when no sound came


def tap_path(cfg):
    """app-voice-tap: the config's app_voice_tap, ~/.local/bin (where mac/build.sh links it), the
    PATH, or bin/ in the checkout this script runs from; None when it isn't built."""
    here = os.path.dirname(os.path.abspath(__file__))
    for path in (cfg.get('app_voice_tap') or '', os.path.expanduser('~/.local/bin/app-voice-tap'),
                 shutil.which('app-voice-tap') or '', os.path.join(here, '..', '..', 'bin', 'app-voice-tap')):
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return os.path.normpath(path)
    return None


class Tap:
    """app-voice-tap, running. It stays in the speaker's process group, so stopping the speaker
    (a new response, or `speak.py stop`) stops it too, and it removes its tap as it exits."""

    def __init__(self, path, address, token, text):
        self.proc = subprocess.Popen(
            [path, '--to', address, '--token', token, '--mute', '--text-stdin',
             '--wait-start', str(TAP_WAIT_START), '--max-seconds', str(TAP_MAX_SECONDS)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.output = b''
        try:
            self.proc.stdin.write(text.encode('utf-8'))
            self.proc.stdin.close()
        except OSError:      # it has already exited; its output says why
            pass

    def _read(self, timeout, until=None):
        """Reads its output until `until` is a line of it, it closes its output, or the time is up;
        True when `until` was seen."""
        fd = self.proc.stdout.fileno()
        end = time.monotonic() + timeout
        while (left := end - time.monotonic()) > 0:
            if until and until in self.output.split(b'\n')[:-1]:
                return True
            ready, _, _ = select.select([fd], [], [], left)
            if ready:
                chunk = os.read(fd, 4096)
                if not chunk:
                    break
                self.output += chunk
        return bool(until) and until in self.output.split(b'\n')[:-1]

    def wait_ready(self, timeout=TAP_READY_TIMEOUT):
        """True once it says the phone took the stream and the tap is running."""
        return self._read(timeout, until=b'ready')

    def last_line(self):
        lines = [line.strip() for line in self.output.decode('utf-8', 'replace').splitlines()]
        lines = [line for line in lines if line and line != 'ready']
        return lines[-1][:300] if lines else 'no output'

    def finish(self, timeout):
        """Waits for it to end (stopping it after `timeout`); (exit status, its last line)."""
        self._read(timeout)
        return self.stop(), self.last_line()

    def stop(self):
        """Stops it if it's still running; its exit status."""
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self.proc.stdout.close()
        return self.proc.returncode


def app_phone(cfg, raw, text, runs, mac_runs, voices):
    """The Claude app reads the response in its own voice, streamed live to the phone, with the
    Mac silent. Whenever that can't happen before the voice begins, the phone gets the text and
    speaks it in its own voices, so something is always heard; speak.log says why."""
    def fallback(reason):
        log(f'app-phone: {reason}; sending the text to the phone')
        deliver_to_phone(dict(cfg, phone_mode='text'), text, runs, mac_runs, voices)

    token = cfg.get('phone_token', '')
    if not token:
        log('app-phone: not paired (speak.py pair CODE)')
        return
    path = tap_path(cfg)
    if not path:
        return fallback('app-voice-tap is not built (run mac/build.sh)')
    started = time.monotonic()
    ack = send_to_phone(message(token, 'ping'), timeout=4.0)     # finds the phone again if it moved
    if not ack or not ack.get('ok'):
        log(f'app-phone: the phone did not answer ({(ack or {}).get("error", "unreachable")}); nothing read aloud')
        return
    address = config().get('phone') or cfg.get('phone')
    tap = Tap(path, address, token, text)
    if not tap.wait_ready():
        tap.stop()
        return fallback(f'app-voice-tap did not start: {tap.last_line()}')
    if not app_read(raw, delay=max(0.0, APP_READ_DELAY - (time.monotonic() - started))):
        tap.stop()
        return fallback("the Claude app's debugger is off, or its Read aloud button wasn't found")
    status, line = tap.finish(timeout=TAP_MAX_SECONDS + TAP_WAIT_START + 30)
    if status == TAP_NO_SOUND:
        fallback(f'no sound from the Claude app ({line})')
    elif status == 0:
        log(f'app-phone: {line}')
    else:
        log(f'app-phone: app-voice-tap stopped with status {status}: {line}')


def installed_voices():
    try:
        out = subprocess.run(['say', '-v', '?'], capture_output=True, text=True).stdout
    except OSError:
        return set()
    return {re.split(r'\s{2,}', line.strip())[0] for line in out.splitlines() if line.strip()}


def say_command(cfg, voices, lang, play=True):
    """`say` with the voice for this language and the rate (and, for playing, the device)."""
    voice = cfg.get('voice_ja' if lang == 'ja' else 'voice_en')
    cmd = ['say']
    if voice and voice in voices:
        cmd += ['-v', voice]
    if int(cfg.get('rate') or 0) > 0:
        cmd += ['-r', str(int(cfg['rate']))]
    if play and cfg.get('device'):
        cmd += ['-a', str(cfg['device'])]
    return cmd


def speak(path):
    with open(PIDFILE, 'w') as f:
        f.write(str(os.getpgrp()))
    try:
        with open(path, encoding='utf-8') as f:
            text = f.read()
    finally:
        os.remove(path)
    raw = text
    cfg = config()
    voices = installed_voices()
    limit = int(cfg.get('max_chars') or 0)
    if limit and len(text) > limit:
        text = text[:limit].rsplit(' ', 1)[0] + '. The rest is on screen.'
    text, chunks, phone_runs = prepare(speakable(text), cfg)
    output = cfg.get('output') if cfg.get('output') in OUTPUTS else 'mac'
    if output == 'app':
        output = None if app_read(raw, APP_READ_DELAY) else 'mac'   # the app's own voice, else the Mac's
    elif output == 'app-both':
        output = 'phone' if app_read(raw, APP_READ_DELAY) else 'both'   # the app's voice here, text there
    elif output == 'app-phone':
        if chunks:
            app_phone(cfg, raw, text, phone_runs, chunks, voices)   # the app's voice on the phone, else text there
        output = None
    phone = None
    if chunks and output in ('phone', 'both'):
        # Alongside the Mac's own speech, so both start together.
        phone = threading.Thread(target=deliver_to_phone, args=(cfg, text, phone_runs, chunks, voices))
        phone.start()
    if output in ('mac', 'both'):
        for lang, chunk in chunks:
            subprocess.run(say_command(cfg, voices, lang) + [chunk])
    if phone:
        phone.join()
    try:
        os.remove(PIDFILE)
    except OSError:
        pass


SAMPLE = 'Good heavens, Miss Sakamoto, you can talk! そうやで。 〔en〕And this is the English voice.'


def pair(code):
    token = normalize_code(code)
    if not token:
        print('The pairing code is the 6 digits Sakamoto Voice shows on the phone.')
        return 1
    remember(phone_token=token)
    print('Looking for the phone…')
    found = find_phone(token)
    if not found:
        print('No phone answered with that code. Is Sakamoto Voice open on the phone, on the same '
              'network as this Mac, with Local Network access allowed? The code is saved; '
              'speak.py phone-test tries again.')
        return 1
    name, address = found
    cfg = remember(phone=address, phone_name=name)
    print(f'Paired with {name} ({address}).')
    if cfg.get('output') == 'mac':
        print('Responses are still spoken on the Mac only: speak.py output phone (or both).')
    return 0


def phone_test(text):
    cfg = config()
    if not cfg.get('phone_token'):
        print('Not paired yet: speak.py pair CODE, with the code the phone shows.')
        return 1
    text, chunks, phone_runs = prepare(speakable(text), cfg)
    ack = send_to_phone(phone_payload(cfg, text, phone_runs, chunks, installed_voices()), timeout=30.0)
    cfg = config()
    if ack is None:
        print('No phone answered (see ~/.config/sakamoto-voice/speak.log).')
        return 1
    if not ack.get('ok'):
        print(f'The phone refused it: {ack.get("error")}.'
              + (' Pair again with the code it shows now.' if ack.get('error') == 'bad token' else ''))
        return 1
    print(f'Sent to {cfg.get("phone_name") or "the phone"} ({cfg.get("phone")}) as {cfg.get("phone_mode")}.')
    return 0


def main():
    args = sys.argv[1:]
    if args[:1] == ['--speak']:
        speak(args[1])
        return 0
    if args:
        cfg = config()
        cmd = args[0]
        if cmd in ('on', 'off'):
            cfg['enabled'] = cmd == 'on'
            save(cfg)
            if cmd == 'off':
                stop_speaker()
                stop_phone(cfg)
            print('Voice', cmd)
        elif cmd == 'stop':
            stop_speaker()
            stop_phone(cfg)
        elif cmd == 'status':
            print(json.dumps(cfg, indent=2, ensure_ascii=False))
        elif cmd == 'test':
            launch(' '.join(args[1:]) or SAMPLE)
        elif cmd == 'pair' and len(args) >= 2:
            return pair(''.join(args[1:]))
        elif cmd == 'output' and args[1:2] and args[1] in OUTPUTS:
            cfg = remember(output=args[1])
            print('Responses are spoken on', {
                'mac': 'the Mac', 'phone': 'the phone', 'both': 'the Mac and the phone',
                'app': "the Claude app, in its own voice (the Mac's when its debugger is off)",
                'app-both': "the Mac, in the Claude app's own voice (the Mac's when its debugger is off), "
                            "and the phone, in its own voices",
                'app-phone': "the phone, in the Claude app's own voice, streamed live while the Mac stays "
                             "silent (the phone's own voices, from the text, when the app's debugger is off)",
            }[args[1]] + '.')
            if args[1] in PHONE_OUTPUTS and not cfg.get('phone_token'):
                print('Not paired with a phone yet: sakamoto pair CODE, with the code the phone shows.')
            if args[1] == 'app-phone' and not tap_path(cfg):
                print("app-voice-tap isn't built yet: run mac/build.sh (until then the phone gets the text).")
        elif cmd == 'phone-mode' and args[1:2] and args[1] in PHONE_MODES:
            remember(phone_mode=args[1])
            print('The phone gets', 'text, in its own voices.' if args[1] == 'text'
                  else "audio, in the Mac's voices.")
        elif cmd == 'phone-test':
            return phone_test(' '.join(args[1:]) or SAMPLE)
        else:
            print(__doc__)
            return 2
        return 0
    # The Stop hook.
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    if not config().get('enabled'):
        return 0
    text = event.get('last_assistant_message')
    if not isinstance(text, str) or not text.strip():   # older versions: read the transcript
        text = final_text(event.get('transcript_path', ''))
    if text:
        launch(text)
    return 0


def dev_handoff():
    """With dev_path set, runs that checkout's speak.py in place of this copy (once: never again
    from there), with the same arguments and stdin."""
    dev = os.path.expanduser(config().get('dev_path') or '')
    target = os.path.join(dev, 'scripts', 'speak.py') if dev else ''
    if (target and os.environ.get('SAKAMOTO_DEV') is None and os.path.isfile(target)
            and os.path.realpath(target) != os.path.realpath(__file__)):
        os.environ['SAKAMOTO_DEV'] = '1'
        os.execv(sys.executable, [sys.executable, target] + sys.argv[1:])


if __name__ == '__main__':
    dev_handoff()
    sys.exit(main())
