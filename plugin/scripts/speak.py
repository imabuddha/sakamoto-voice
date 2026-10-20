#!/usr/bin/env python3
"""Miss Sakamoto's voice: speaks each finished Claude Code response aloud with macOS `say`, on the
Mac, on an iPhone running the Sakamoto Voice app (ios/), or both.

Run as (or, for the commands after the first two, `sakamoto ...`: bin/sakamoto, linked into the
PATH as README.md describes):
  speak.py                 as a Stop hook: reads the hook's JSON on stdin, finds the response's final
                           text, and hands it to a detached speaker so the hook returns at once.
  speak.py --speak FILE    the detached speaker (internal): reads FILE, speaks it, deletes it.
  speak.py on|off|stop|hush|status|test ["text"]
                           the switch: on and off persist; stop silences the current response;
                           hush does the same for a barge-in (Sakamoto Eyes runs it when you talk
                           over her), logged as one.
  speak.py pair CODE       pairs with the phone: stores its 6-digit code and finds it on the network.
  speak.py output mac|phone|both|app|app-both|app-phone
                           where responses are spoken.
  speak.py phone-mode text|audio
                           what the phone gets: text, spoken in its own voices, or audio rendered
                           here in the Mac's voices (`say -o`), such as a Siri system voice.
  speak.py phone-test ["text"]
                           sends a line to the phone now and reports what happened.
  speak.py announce "text" speaks the text on every phone the hub lists, whoever's (a hub-wide
                           announcement; see "One session for each person" below).

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
            "app-both": the Claude app's voice on the Mac, and streamed to the phone as "app-phone" does
            (without muting the Mac); when the stream can't start, the text goes to the phone.
            "app-phone": the same voice, streamed live to the phone while the Mac stays silent:
            app-voice-tap (mac/build.sh builds it) taps the Claude app's audio, muted on the Mac,
            and this script streams it to the phone, which also shows the text. When the debugger
            is off, the tool isn't built, or no sound comes, the phone gets the text instead (its
            own voices).
            In both, the phone has the last word (its Claude's Voice setting, 1.0 and later): while
            it wants the text (phone_voice), the Mac sends the text and streams nothing, and
            app-both has the app read on the Mac alone.
  app_voice true (the default) or false. True: while the app's debugger is on, the app's voice is
            asked for directly, without its button (app-voice.mjs: Read aloud's own text-to-speech
            WebSocket, opened in the claude.ai session page; a private endpoint that may change),
            for "app" (played on the Mac with ffmpeg), "app-phone" and "app-both" (streamed, and
            played on the Mac for app-both), and "phone" (her voice streamed to the phone, unless
            it wants the text); when that fails, the button (or, for "phone", the text) as before.
  app_voice_voice, app_voice_language  empty (the default): the voice and language Read aloud
            uses (the account's settings: Settings > General > Voice). Set, a voice ID ("ja-akarui")
            or a language code ("ja") that app-voice.mjs asks for instead.
  app_voice_tap  where app-voice-tap is, when it's not in ~/.local/bin or on the PATH.
  ffmpeg    the ffmpeg that plays the app's voice on the Mac, when it's not on the PATH or in
            /opt/homebrew/bin.
  phone_remote  another address for the phone, tried first: e.g. its Tailscale address
            ("100.x.y.z:47811"), so the phone is reached away from home too; when it fails, the
            local network as usual.
  phone_route  Sakamoto Eyes' voice route: the path of its hub's voice-route.json (empty: off).
            The hub names there, with each line it hears, the phone in the room where the
            conversation is and its addresses, and lists every connected phone that plays her
            voice ("phones"). Where a response goes depends on the prompt it answers (the
            UserPromptSubmit hook keeps its kind in last-prompt):
            - a line the hub heard and its relay typed ("👂 Lab: …"): only the routed phone (its
              addresses in turn; when none answers, silence, never the phone above, which may be
              in another room), with the Mac quiet ("both" plays as "phone", "app-both" as
              "app-phone"), so that phone's echo canceller can take her voice out of what it
              hears. When the Claude app's voice can't be streamed there, the phone's "fallback"
              decides: "stream_only" (the phone by the Mac, its back camera): nothing is heard;
              "any" (the phone held facing you): the text in the phone's own voices. A route to
              the Mac ("mac": true, the Mac app's room: the line came from the Mac app, or no
              phone there plays her voice): only the Mac, as the output's Mac side ("app-phone"
              and "app-both" play as "app", "phone" and "both" as "mac"), never a phone. A route
              older than 30 minutes, or naming neither an address nor the Mac, changes nothing.
              Sakamoto Eyes' Mac app, when it plays her voice, is named as a phone (its
              receiver on 127.0.0.1), so the Claude app's voice is streamed to it, muted here;
              when it doesn't answer, the Mac's own speakers play instead (its room), not silence.
              The reply's room is the one its 👂 label names ("👂 Nerdvana (late, 13:40): …"
              too): a route to another room is not followed (a late line renews no route). When
              that room is muted (its level Mute or Ears off, as the hub says: see below), or the
              route names the Mac's speakers while they are in a muted room ("mac_silent"),
              nothing is heard anywhere, and the hub shows the reply silently in that room (her
              sign for a few words, her board for more: a "silent_reply" line in its
              commands.jsonl, next to voice-route.json, created when missing). With no route to
              that room, the listed phones there, and the Mac when its speakers are there
              ("mac_rooms"); else silence;
            - no prompt (a response to a notice: she speaks unprompted), or a typed prompt (no
              room asked): while the hub knows the room John is in ("his_room"), only there (its
              listed phones, and the Mac when its speakers are there), nothing when it is muted;
              else every listed phone in a room that isn't muted (the app's voice streamed to all
              at once), and the Mac as output says unless the Mac's speakers are in a muted room
              ("mac_silent"); nothing at all when none is left. A route is never followed for
              these (2026-10-17 13:45-14:02: replies to typed prompts played in Labmac, where the
              route of a line 5 minutes old pointed, while John sat muted in Nerdvana). Without
              the hub's levels, as before: a notice's reply to every listed phone and the Mac as
              output says, a typed prompt's as without phone_route.
            The hub's levels (hub 0.2.35: "level", everyone's; "levels", each room's; each phone's
            "silent"; "mac_silent"; hub 0.2.36: "mac_rooms", "his_room") count only while the hub runs (its status.json, next to
            voice-route.json, written in the last LEVELS_MAX_AGE seconds).
            Every phone needs the same pairing code (phone_token). While the hub runs (its
            her-voice.sock next to voice-route.json), it also hears of every reading on the Mac's
            own speakers, as it plays: the stream's copy marked "mac", the app's voice on the Mac
            alone through app-voice-tap unmuted (the speaker follows it to its end), or a note
            with no audio while `say` speaks; its phones that would hear the Mac don't listen
            meanwhile (Sakamoto Eyes P2.8).
  dev_path  for working on the plugin: a checkout's plugin/ folder. The installed (cached) copy then
            runs that checkout's speak.py instead, so edits there take effect with the next
            response, without a plugin update or a restart (changes to hooks.json still need both).
  phone_mode  "text" (the default; the phone speaks it in its own voices) or "audio" (rendered here
            with voice_en, voice_ja, and rate, and played on the phone).
  phone_token the phone's 6-digit pairing code (speak.py pair sets it).
  phone     the phone's "host:port", found with Bonjour (dns-sd) and kept here; found again when a
            send fails. phone_name is its Bonjour name.
  phone_voice  what the phone last said it wants for the Claude app's voice: "stream" or "text"
            (to save mobile data); kept from every answer it gives, empty until it has answered.
            A phone app older than 1.0 never says, and counts as "stream".
One session for each person (Sakamoto Eyes' hub 0.2.68, `owner_sessions`): a second Claude Code
session, for someone whose phone is their own (the hub's `owners`), runs with SAKAMOTO_OWNER=<name>
in its environment (a per-folder .claude/settings.json "env" in its own working folder). Then this
script is that person's session's: its replies go only to that person's phones (the `routes`
object of the hub's voice-route.json, for that name: their route, their phones, the levels as they
bear on them), never to the other session's, and the main session's (no SAKAMOTO_OWNER) go only
to the others'. It keeps its own prompted, responded, last-prompt, speaker.pid, app-reading, and
recordings in ~/.config/sakamoto-voice/owners/<name>/ (the name in lowercase, letters and digits
only), which the hub watches for that session; the settings, the pairing code, and speak.log are
shared. A reply of that session never plays on the Mac's speakers or on the usual phone unless the
hub says that person's room hears them. It tells the hub whose it is: `as` in its voice copy's
header and in its silent_reply commands. `speak.py announce` ignores all this: every phone the
hub lists (`all_phones`), except in muted rooms. Without SAKAMOTO_OWNER, everything is as before.
SAKAMOTO_RELAY_PAGE (the text that names the session's page in the Claude app, as the hub's
`owner_sessions` has it) points app-read.mjs and app-voice.mjs at that session's page.
Voice markers in a response switch voices: 〔en〕 to voice_en and 〔ja〕 to voice_ja, from the marker
to the next one or to the end of its paragraph (a blank line), where the default voice resumes.
Markers are never spoken or shown; unknown ones, such as 〔xx〕, are dropped. They hold on the phone
too, whatever its setting.
A new response interrupts the one still being spoken, on the Mac and on the phone. Sending to the
phone happens in the detached speaker; its failures are silent but logged to speak.log here.
While the Claude app's own Read aloud reads a response, ~/.config/sakamoto-voice/app-reading says
so (when it started, about when it ends, and the text), for Sakamoto Eyes, which watches
speaker.pid otherwise; the next response, stop, and hush remove it.
"""
import base64, json, os, pty, re, select, shutil, signal, socket, subprocess, sys, tempfile, threading
import time, unicodedata, wave

HOME = os.path.expanduser('~/.config/sakamoto-voice')


def owner_from_env(environ=None):
    """The person whose Claude session this is (SAKAMOTO_OWNER, set in that session's environment),
    as typed; '' for the main session (not set, empty, or "me")."""
    name = ((environ if environ is not None else os.environ).get('SAKAMOTO_OWNER') or '').strip()
    return '' if name.casefold() == 'me' else name


def owner_slug(name):
    """A name as a folder name: lowercase, letters and digits only, other runs a hyphen
    ("Mary Ann" -> "mary-ann"); the hub's OwnerLabel.slug is the same. "owner" when none is left."""
    out = re.sub(r'[^\w]+|_+', '-', name.lower()).strip('-')
    return out or 'owner'


OWNER = owner_from_env()                   # '' for the main session
OWNER_KEY = OWNER.casefold()               # how the hub's `routes` name it (its lowercase)
# This session's own files: the main session's are in HOME; another person's session keeps its own
# in HOME/owners/<name>, which the hub watches for it. The settings and the log are shared.
STATE = os.path.join(HOME, 'owners', owner_slug(OWNER)) if OWNER else HOME
CONFIG = os.path.join(HOME, 'config.json')
PIDFILE = os.path.join(STATE, 'speaker.pid')
# When the last prompt (UserPromptSubmit runs `speak.py stop`) and the last response (the Stop hook)
# came. A response with no prompt since the one before followed a notice, not a message from you,
# and the Claude app's Read aloud would read it together with the response before; so for such a
# response the app's voice is skipped (see speak()).
PROMPTED = os.path.join(STATE, 'prompted')
RESPONDED = os.path.join(STATE, 'responded')
# What kind of prompt the last one was (note_prompt): {"heard": a 👂 line Sakamoto Eyes' relay
# typed, "rooms", "at_unix"}, for where a reply goes (phone_route).
LAST_PROMPT = os.path.join(STATE, 'last-prompt')
# While the Claude app's Read aloud reads a response (app_read clicked): {"started", "ends" (Unix
# times; the end estimated from the text), "text"}. Its speaker has exited by then, so this is how
# Sakamoto Eyes' hub knows her voice is on (for its echo guard and barge-in).
APP_READING = os.path.join(STATE, 'app-reading')
LOG = os.path.join(HOME, 'speak.log')
LOG_MAX = 64 * 1024          # then speak.log becomes speak.log.1, replacing the one before
DEFAULTS = {'enabled': True, 'voice_en': '', 'voice_ja': 'Kyoko', 'default_lang': 'auto', 'rate': 0,
            'device': '', 'max_chars': 6000,
            'output': 'mac', 'phone_mode': 'text', 'phone_token': '', 'phone': '', 'phone_name': '',
            'app_voice_tap': '', 'dev_path': '', 'phone_remote': '', 'phone_voice': '', 'phone_route': '',
            'app_voice': True, 'app_voice_voice': '', 'app_voice_language': ''}
OUTPUTS = ('mac', 'phone', 'both', 'app', 'app-both', 'app-phone')
PHONE_OUTPUTS = ('phone', 'both', 'app-both', 'app-phone')       # the outputs a stop also tells the phone
PHONE_MODES = ('text', 'audio')
PHONE_VOICES = ('stream', 'text')     # what the phone wants for the Claude app's voice (phone_voice)


def config():
    os.makedirs(HOME, exist_ok=True)
    if STATE != HOME:
        os.makedirs(STATE, exist_ok=True)
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


ROUTE_MAX_AGE = 30 * 60      # seconds: an older voice route is ignored
# Sakamoto Eyes' listening levels at which her voice plays in no way in a room (John, 2026-10-17
# 15:24: a muted room hears her nowhere, not even through another room or the Mac).
SILENT_LEVELS = ('mute', 'off')
# Seconds: the hub's levels in voice-route.json count only while its status.json is this fresh
# (it rewrites it every 5 s), so a hub that stopped without tidying up never silences her.
LEVELS_MAX_AGE = 60
ROUTED_OUTPUTS = {'both': 'phone', 'app-both': 'app-phone'}   # the Mac stays quiet under a route
# A route to the Mac's speakers ("mac": the Mac app's room): each output's Mac side, no phone.
MAC_OUTPUTS = {'app': 'app', 'app-both': 'app', 'app-phone': 'app', 'mac': 'mac', 'both': 'mac', 'phone': 'mac'}


def addresses_of(entry):
    """The "host:port" strings in a route's or a listed phone's `addresses` (a list; anything
    else, or any item that isn't a non-empty string, is ignored)."""
    addresses = entry.get('addresses') if isinstance(entry, dict) else None
    return [a for a in addresses if isinstance(a, str) and a] if isinstance(addresses, list) else []


def text_of(value, default):
    """A route's field as text: `value` when it is a non-empty string, else `default`."""
    return value if isinstance(value, str) and value else default


def on_this_mac(addresses):
    """Whether every address is this Mac's loopback (Sakamoto Eyes' Mac app, which the hub names
    as a phone): the Mac's own room, so its own speakers are the fallback, not silence."""
    return bool(addresses) and all(a.startswith('127.') or a.startswith('[::1]') for a in addresses)


def route_file(cfg, whole=False):
    """Sakamoto Eyes' voice-route.json (phone_route) as a dict; {} when off or unreadable. As
    this session sees it: the main session's is the file itself; a person's own session
    (SAKAMOTO_OWNER) sees what the hub wrote for it under `routes`, and {} (no route, no phones, no
    levels: it stays silent) when the hub wrote none. `whole`: the file itself, for an announcement."""
    path = cfg.get('phone_route') or ''
    if not path:
        return {}
    try:
        with open(os.path.expanduser(path), encoding='utf-8') as f:
            route = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(route, dict):
        return {}
    if OWNER and not whole:
        routes = route.get('routes')
        view = next((v for k, v in routes.items() if isinstance(k, str) and k.casefold() == OWNER_KEY),
                    None) if isinstance(routes, dict) else None
        return view if isinstance(view, dict) else {}
    return route


def voice_route(cfg, now=None):
    """Sakamoto Eyes' voice route (phone_route, its hub's voice-route.json: {"room", "phone",
    "addresses", "fallback", "mac", "at_unix", "phones", …}), or None when there is none, it is
    older than ROUTE_MAX_AGE, names neither an address nor the Mac ("mac": true), or can't be
    read."""
    route = route_file(cfg)
    try:
        age = (now or time.time()) - float(route.get('at_unix', 0))
    except (TypeError, ValueError):
        return None
    addresses = addresses_of(route)
    if not (addresses or route.get('mac') is True) or not 0 <= age <= ROUTE_MAX_AGE:
        return None
    return dict(route, addresses=addresses)


def route_addresses(cfg, now=None):
    """The addresses ("host:port") of the phone the voice route names; [] without a route."""
    route = voice_route(cfg, now)
    return route['addresses'] if route else []


def hub_levels(cfg, now=None, whole=False):
    """Sakamoto Eyes' listening levels as they bear on her voice (voice-route.json's "level",
    "levels", and "mac_silent", hub 0.2.35; "mac_rooms" and "his_room", hub 0.2.36), as
    {"level", "levels", "mac_silent", "mac_rooms", "his_room"}; None when the
    hub doesn't say, or isn't running (its status.json, next to voice-route.json, older than
    LEVELS_MAX_AGE or missing). Malformed fields count as Normal and not silent."""
    route = route_file(cfg, whole)
    if 'level' not in route and 'levels' not in route:
        return None
    status = os.path.join(os.path.dirname(os.path.expanduser(cfg.get('phone_route') or '')), 'status.json')
    try:
        if (now or time.time()) - os.path.getmtime(status) > LEVELS_MAX_AGE:
            return None
    except OSError:
        return None
    levels = route.get('levels')
    levels = {k: v for k, v in levels.items() if isinstance(k, str) and isinstance(v, str)} \
        if isinstance(levels, dict) else {}
    mac_rooms = route.get('mac_rooms')
    mac_rooms = [r for r in mac_rooms if isinstance(r, str) and r] if isinstance(mac_rooms, list) else []
    return {'level': text_of(route.get('level'), 'normal'), 'levels': levels,
            'mac_silent': route.get('mac_silent') is True, 'mac_rooms': mac_rooms,
            'his_room': text_of(route.get('his_room'), '')}


def room_silent(levels, room):
    """Whether her voice plays in no way in `room` (its level Mute or Ears off; a room the hub
    doesn't list has everyone's level; names compared without regard to case)."""
    if not levels:
        return False
    level = next((v for k, v in levels['levels'].items() if same_room(k, room)), levels['level'])
    return level in SILENT_LEVELS


def last_heard_rooms():
    """The rooms of the last prompt when it was a 👂 line (LAST_PROMPT), else []."""
    try:
        with open(LAST_PROMPT, encoding='utf-8') as f:
            rooms = json.load(f).get('rooms')
    except (OSError, ValueError, AttributeError):
        return []
    return [r for r in rooms if isinstance(r, str) and r] if isinstance(rooms, list) else []


def listed_phones(cfg, whole=False):
    """The phones the hub lists as connected and playing her voice (voice-route.json's
    "phones"), each {"name", "room", "addresses", "fallback"}; [] when none or off. `whole`: every
    phone the hub lists, whoever's (`all_phones`, else `phones`), for an announcement."""
    route = route_file(cfg, whole)
    phones = route.get('all_phones') if whole and isinstance(route.get('all_phones'), list) else route.get('phones')
    if not isinstance(phones, list):
        return []
    return [dict(p, addresses=addresses_of(p), name=text_of(p.get('name'), 'a phone'))
            for p in phones if isinstance(p, dict) and addresses_of(p)]


# The kind of turn a response ends: 'heard', a reply to a line Sakamoto
# Eyes heard and its relay typed ("👂 Lab: …"); 'typed', a reply to a prompt typed at the
# keyboard; 'notice', a response with no prompt since the one before (a background task's
# notice, say): she speaks unprompted.
HEARD = re.compile(r'^\s*👂\s*([^:(]+?)\s*(?:\([^)]*\))?:\s')


def heard_rooms(prompt):
    """The rooms of a 👂 line ("👂 Lab + Den: …" → ["Lab", "Den"]), or None when the
    prompt isn't one."""
    match = HEARD.match(prompt) if isinstance(prompt, str) else None
    return [r.strip() for r in match.group(1).split(' + ') if r.strip()] if match else None


def note_prompt(prompt, now=None):
    """Keeps what kind of prompt the last one was (LAST_PROMPT), for the response's turn."""
    rooms = heard_rooms(prompt)
    try:
        os.makedirs(STATE, exist_ok=True)
        with open(LAST_PROMPT, 'w', encoding='utf-8') as f:
            json.dump({'heard': rooms is not None, 'rooms': rooms or [], 'at_unix': now or time.time()}, f)
    except OSError as e:
        log(f'prompt: {e}')


def turn_kind(prompted):
    """'notice' for a response without a new prompt; else 'heard' when the last prompt was a 👂
    line, 'typed' otherwise."""
    if not prompted:
        return 'notice'
    try:
        with open(LAST_PROMPT, encoding='utf-8') as f:
            return 'heard' if json.load(f).get('heard') else 'typed'
    except (OSError, ValueError, AttributeError):
        return 'typed'


def routed(cfg, turn='heard'):
    """The settings for speaking this turn under Sakamoto Eyes (phone_route). Never saved. John's
    rules (2026-10-17 15:24): (A) a reply goes to the room whose heard line asked for it; (B) when
    that room is muted, she speaks nowhere; (C) the hub shows it silently there instead; (D) what
    no room asked for (a notice's reply, a typed prompt's) goes to the room he is in, or, when the
    hub doesn't know it, to every device whose setting says so, except in muted rooms.
    - 'heard' (a reply to a 👂 line): its rooms are the ones the 👂 label names ("👂 Nerdvana
      (late, 13:40): …": last_heard_rooms), never a route from another room (2026-10-17, the
      skeptic: a late line renews no route, so a muted room's late line was answered aloud where
      the route of an older line pointed). One of them muted (hub_levels): `silent_in` (B, C),
      shown in each muted one (`silent_rooms`). Else, with a fresh route to one of them: her voice
      goes only to the routed phone (`targets`; silent when it doesn't answer: never the usual
      phone, which may be in another room), and the Mac stays quiet ("both" as "phone",
      "app-both" as "app-phone"). When the app's voice can't be streamed there, the phone's own
      choice (its `fallback`): "stream_only" (silence) or "any" (the text in its voices; also
      when it doesn't say). A route to the Mac ("mac": the line came from the Mac app's room):
      only the Mac, as the output's Mac side (MAC_OUTPUTS: "app-phone" as "app", "both" as
      "mac"), with no phone (`on_mac`); unless the Mac's speakers are in a muted room
      ("mac_silent"): then `silent_in` its room. With no fresh route there, but the hub's levels:
      the listed phones in those rooms, and the Mac when its speakers are in one of them
      (`in_rooms`); `silent` when none is. Without the levels and a route: unchanged.
    - 'notice' or 'typed' (D), with the hub's levels: `everywhere`. No route is followed
      (2026-10-17 13:45-14:02: typed prompts' replies played in Labmac by a route 5 minutes old
      while John sat muted in Nerdvana).
    - 'notice' without them, with phones listed: every one of them, and the Mac as `output` says.
    - 'typed' without them, or no route or list: unchanged.
    A target on this Mac (the Mac app, `mac_fallback`) that doesn't answer gives way to the Mac's
    own speakers (app_phone), never silence: it is in the Mac's room. A malformed route counts as
    none, field by field (never an exception)."""
    levels = hub_levels(cfg)
    if turn == 'heard':
        route = voice_route(cfg)
        room = text_of(route.get('room'), '') if route else ''
        heard = last_heard_rooms() or ([room] if room else [])
        muted = [r for r in heard if room_silent(levels, r)]
        if muted:
            return dict(cfg, silent_in=muted[0], silent_rooms=muted)
        if route and not any(same_room(room, r) for r in heard):
            route = None        # another room's: says nothing of where this line came from
        if not route:
            return in_rooms(cfg, levels, heard) if levels is not None else cfg
        if route.get('mac') is True:
            if levels and levels['mac_silent']:
                return dict(cfg, silent_in=room, silent_rooms=[room])
            return dict(cfg, output=MAC_OUTPUTS.get(cfg.get('output'), 'mac'), on_mac=True)
        target = {'name': text_of(route.get('phone'), text_of(route.get('room'), 'the routed phone')),
                  'addresses': route['addresses'], 'fallback': text_of(route.get('fallback'), 'any')}
        if on_this_mac(route['addresses']):
            target['mac_fallback'] = True
        return dict(cfg, output=ROUTED_OUTPUTS.get(cfg.get('output'), cfg.get('output')), targets=[target])
    if levels is not None and turn in ('notice', 'typed'):
        return everywhere(cfg, levels)
    if turn == 'notice':
        phones = listed_phones(cfg)
        if phones:
            return dict(cfg, targets=[dict(p, fallback=text_of(p.get('fallback'), 'any')) for p in phones])
    return cfg


def same_room(a, b):
    """Room names as the hub writes them, compared without regard to case."""
    return isinstance(a, str) and isinstance(b, str) and a.casefold() == b.casefold()


def in_rooms(cfg, levels, rooms):
    """Rule A with no route to them (a late line's, or an older route from another room): the
    listed phones in `rooms` that aren't muted, and the Mac's side of `output` when its speakers
    are in one of them ("mac_rooms") and in no muted room ("mac_silent"); `silent` when none is.
    With the Mac's rooms unknown (none named), the Mac only when no phone is there (as a route to
    a phone keeps the Mac quiet)."""
    if not rooms:
        return everywhere(cfg, levels)
    phones = [p for p in listed_phones(cfg)
              if any(same_room(p.get('room'), r) for r in rooms) and not room_silent(levels, text_of(p.get('room'), ''))]
    # (Another person's session: the Mac's speakers only where the hub names their room.)
    mac_here = any(same_room(m, r) for m in levels['mac_rooms'] for r in rooms) \
        if levels['mac_rooms'] else not phones and not OWNER
    return speakers(cfg, levels, phones, mac_here and not levels['mac_silent'])


def everywhere(cfg, levels):
    """Rule D (routed()), with the hub's levels: when auto-mute knows the room he is in
    ("his_room"; the coordinator's decision, 2026-10-17), only there: its listed phones, and the
    Mac's side of `output` when its speakers are in that room ("mac_rooms") and in no muted room
    ("mac_silent", where the hub leaves out a room auto-muted while he is in another the same
    speakers reach), nothing at all when his room is muted. When it doesn't
    know: the listed phones in rooms that aren't muted, and the Mac's side unless its speakers are
    in a muted room ("mac_silent"). Never the Mac's side when a target is the Mac app (it plays
    there)."""
    his = levels.get('his_room')
    if his:
        if room_silent(levels, his):
            return dict(cfg, silent=True)
        phones = [p for p in listed_phones(cfg) if same_room(p.get('room'), his)]
        mac_here = any(same_room(m, his) for m in levels['mac_rooms'])
        return speakers(cfg, levels, phones, mac_here and not levels['mac_silent'], unlisted=not phones)
    phones = [p for p in listed_phones(cfg)
              if p.get('silent') is not True and not room_silent(levels, text_of(p.get('room'), ''))]
    # (Another person's session never uses the Mac's speakers for what no room asked for.)
    return speakers(cfg, levels, phones, not levels['mac_silent'] and not OWNER, unlisted=not listed_phones(cfg))


def speakers(cfg, levels, phones, mac_ok, unlisted=False):
    """The settings for her voice on `phones` and, when `mac_ok` and `output` has one, the Mac's
    side (never with the Mac app among the targets: it plays there); `silent` when neither.
    `unlisted`: the hub lists no phone where she may speak (not one that is muted), so "app-phone"
    plays as the Mac app."""
    targets = []
    for p in phones:
        target = dict(p, fallback=text_of(p.get('fallback'), 'any'))
        if on_this_mac(target['addresses']):
            target['mac_fallback'] = True
        targets.append(target)
    output = cfg.get('output') if cfg.get('output') in OUTPUTS else 'mac'
    phone = output in PHONE_OUTPUTS and bool(targets)
    # No phone to carry her voice (the Mac app's room, say, which the hub lists as a phone only
    # while it plays): the Mac app on the Mac's own speakers ("app-phone" says the app, not only phones), never silence in a room that
    # may hear her (2026-10-18 04:16 and 04:38: "app-phone" and John in Labmac, no phone listed).
    mac = (output in ('mac', 'both', 'app', 'app-both') or (output == 'app-phone' and unlisted and not targets)) and mac_ok \
        and not any(t.get('mac_fallback') for t in targets)
    if phone and mac:
        return dict(cfg, output=output, targets=targets)
    if phone:
        return dict(cfg, output=ROUTED_OUTPUTS.get(output, output), targets=targets)
    if mac:
        return dict(cfg, output=MAC_OUTPUTS.get(output, 'mac'), on_mac=True)
    return dict(cfg, silent=True)


def announcement(cfg):
    """A hub-wide announcement (`speak.py announce`): every phone the hub lists, whoever's, except in
    rooms muted for everyone (a room's own Mute or Ears off), and the Mac's side of `output` unless
    its speakers are in a muted room. Without the hub's levels: every phone it lists and the Mac as
    `output` says (the usual phone and the Mac, with no hub). No route, no room he is in: it goes
    everywhere."""
    levels = hub_levels(cfg, whole=True)
    if levels is None:
        phones = listed_phones(cfg, whole=True)
        if phones:
            return dict(cfg, targets=[dict(p, fallback=text_of(p.get('fallback'), 'any')) for p in phones])
        return cfg
    phones = [p for p in listed_phones(cfg, whole=True)
              if not room_silent(levels, text_of(p.get('room'), ''))]
    return speakers(cfg, levels, phones, not levels['mac_silent'], unlisted=not listed_phones(cfg, whole=True))


def show_silently(cfg, room, text):
    """Rule C: asks Sakamoto Eyes' hub to show her reply silently in `room` (its commands.jsonl,
    next to voice-route.json: {"cmd": "silent_reply", "room", "text"}); its sign for a few words,
    its board for more (the hub decides). One append, so a line is never split; the file is
    created when missing (the hub reads it once it exists), but never its folder (the hub's)."""
    path = os.path.join(os.path.dirname(os.path.expanduser(cfg.get('phone_route') or '')), 'commands.jsonl')
    command = {'cmd': 'silent_reply', 'room': room, 'text': text[:SILENT_TEXT_MAX]}
    if OWNER:
        command['as'] = OWNER          # whose session shows it (the hub's `as`)
    line = json.dumps(command, ensure_ascii=False) + '\n'
    try:
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, line.encode('utf-8'))
        finally:
            os.close(fd)
    except OSError as e:
        log(f'silent reply for {room}: {e}')
        return False
    return True


SILENT_TEXT_MAX = 8000      # the hub's board holds this much (Signboard.textMax)


def owner_only(cfg):
    """A person's own session (SAKAMOTO_OWNER) speaks only where the hub named a place for it (a
    phone of theirs, their room's silence, the Mac when their room hears it): with none (no hub
    running, no route for it, or none of their phones connected) it is silent, never the usual
    phone or the Mac's speakers, which are the main session's."""
    if not OWNER or cfg.get('silent_in') or cfg.get('silent') or cfg.get('targets') or cfg.get('on_mac'):
        return cfg
    log('voice route: no device of the owner to speak on; silent')
    return dict(cfg, silent=True)


def target_name(target):
    return target['name'] if target else 'the phone'


def log(message):
    """One line in speak.log; never fails. The log is kept small: past LOG_MAX it starts over,
    keeping the one before as speak.log.1."""
    try:
        os.makedirs(HOME, exist_ok=True)
        if os.path.exists(LOG) and os.path.getsize(LOG) > LOG_MAX:
            os.replace(LOG, LOG + '.1')
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(time.strftime('%Y-%m-%d %H:%M:%S ') + (f'[{OWNER}] ' if OWNER else '')
                    + message.replace('\n', ' ') + '\n')
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
# Bonjour, which macOS's dns-sd browses and resolves without any Python packages. From 1.0 each
# answer to a message with the right code also says what the phone wants for the Claude app's
# voice, "voice": "stream" or "text", which note_voice() keeps as phone_voice.

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


def note_voice(ack):
    """Keeps what the phone says it wants for the Claude app's voice (phone_voice), from any of its
    answers: "stream" or "text". A phone app older than 1.0 never says; its accepting answers
    count as "stream". Refusals that don't say (a wrong code, say) change nothing. Returns what
    is kept now."""
    if not isinstance(ack, dict):
        return None
    voice = ack.get('voice') or ack.get('want')
    if voice not in PHONE_VOICES:
        if not ack.get('ok'):
            return None
        voice = 'stream'
    if config().get('phone_voice') != voice:
        remember(phone_voice=voice)
        log(f'phone: wants {"the text" if voice == "text" else "the stream"} for the Claude app\'s voice now')
    return voice


def exchange(address, payload, timeout=10.0):
    """Sends one message and returns the phone's answer (a dict), keeping what it says it wants
    (note_voice). Raises OSError when the phone can't be reached and ValueError when its answer
    isn't JSON."""
    host, port = split_address(address)
    with socket.create_connection((host, port), timeout=min(timeout, 4.0)) as sock:
        sock.settimeout(timeout)
        sock.sendall(payload)
        sock.shutdown(socket.SHUT_WR)
        reply = b''
        while chunk := sock.recv(4096):
            reply += chunk
    ack = json.loads(reply.decode('utf-8') or 'null') or {}
    note_voice(ack)
    return ack


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


def reach_phone(attempt, target=None):
    """`attempt(address)` at the remembered phone, and, when that raises OSError or ValueError, at
    the phone found again (and remembered). Returns what it returns, or None when no phone could be
    reached; logs what went wrong.

    target: a phone Sakamoto Eyes named (routed()'s `targets`): only its addresses are tried, in
    order, and nothing else when they fail (the usual phone may be in another room)."""
    cfg = config()
    token = cfg.get('phone_token', '')
    if not token:
        log('phone: not paired (speak.py pair CODE)')
        return None
    if target is not None:
        for address in target['addresses']:
            try:
                return attempt(address)
            except (OSError, ValueError) as e:
                log(f'phone: {target_name(target)} at {address} (phone_route): {e}')
        log(f'phone: {target_name(target)} did not answer; silent there')
        return None
    remote = cfg.get('phone_remote', '')
    if remote:                     # e.g. its Tailscale address: works at home and away
        try:
            return attempt(remote)
        except (OSError, ValueError) as e:
            log(f'phone: {remote} (phone_remote): {e}; trying the local network')
    address = cfg.get('phone', '')
    if address:
        try:
            return attempt(address)
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
        return attempt(address)
    except (OSError, ValueError) as e:
        log(f'phone: {address}: {e}')
        return None


def send_to_phone(payload, timeout=10.0, target=None):
    """Sends to the remembered phone, finding it again (and remembering it) when that fails, or
    to `target` alone (reach_phone). Returns the phone's answer, or None when no phone could be
    reached; logs what went wrong."""
    return reach_phone(lambda address: exchange(address, payload, timeout), target)


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
    """The response to the phone, or to each of routed()'s `targets` (at once, in parallel)."""
    timeout = 30.0 if cfg.get('phone_mode') == 'audio' else 10.0

    def deliver(payload, target):
        try:
            ack = send_to_phone(payload, timeout=timeout, target=target)
            if ack is not None and not ack.get('ok'):
                log(f'phone: refused: {ack.get("error")}' + (f' ({target_name(target)})' if target else ''))
        except Exception as e:   # the speaker never fails loudly; the log says why
            log(f'phone: {type(e).__name__}: {e}')

    try:
        payload = phone_payload(cfg, text, runs, mac_runs, voices)
    except Exception as e:
        log(f'phone: {type(e).__name__}: {e}')
        return
    targets = cfg.get('targets')
    if not targets:
        deliver(payload, None)
        return
    threads = [threading.Thread(target=deliver, args=(payload, t)) for t in targets]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()


def stop_phone(cfg):
    """Silences the phone, quickly and only at its remembered address (phone_remote first), and,
    under Sakamoto Eyes (phone_route), the routed phone and every phone the hub lists, before
    it (each at its first address)."""
    if cfg.get('output') not in PHONE_OUTPUTS or not cfg.get('phone_token'):
        return
    # (Another person's session stops only the phones the hub lists for it, never the usual phone,
    # which is the main session's.)
    addresses = route_addresses(cfg)[:1] + [addresses_of(p)[0] for p in listed_phones(cfg)] \
        + ([] if OWNER else [cfg.get('phone_remote') or cfg.get('phone')])
    for address in dict.fromkeys(a for a in addresses if a):
        try:
            exchange(address, message(cfg['phone_token'], 'stop'), timeout=1.5)
        except (OSError, ValueError) as e:
            log(f'phone: stop: {address}: {e}')


# ---- Speaking -------------------------------------------------------------------------------

def stop_speaker():
    """Silences the Mac's speaker, and drops the note that the Claude app is reading."""
    try:
        with open(PIDFILE) as f:
            pid = int(f.read().strip())
        os.killpg(pid, signal.SIGTERM)
    except (OSError, ValueError):
        pass
    for path in (PIDFILE, APP_READING):
        try:
            os.remove(path)
        except OSError:
            pass


NOTICE_TAGS = ('<task-notification', '<system-reminder', '<local-command', '<bash-')
# A scheduled (cron) prompt: "[Scheduled usage gauge update — not a message from John.] ...". The
# harness submits it like a prompt, but nobody typed it.
SCHEDULED = re.compile(r'\[Scheduled\b[^\]\n]*not a message from', re.I)


def is_notice(prompt):
    """Whether a submitted prompt is a notice Claude Code delivered rather than a message typed by
    you: it starts with one of the harness's tags, or is a scheduled prompt (a cron job's:
    2026-10-18 21:40, one such prompt arrived three seconds into a reply to a heard line and
    silenced it with `stop`, as if John had spoken)."""
    if not isinstance(prompt, str):
        return False
    prompt = prompt.lstrip()
    return prompt.startswith(NOTICE_TAGS) or bool(SCHEDULED.match(prompt))


def hook_prompt():
    """When stdin is a UserPromptSubmit hook's JSON, its prompt; else ''. (Typed at a terminal,
    stdin isn't read.)"""
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return ''
        # A hook's JSON is there at once; anything else (an open pipe with nothing coming) isn't
        # waited for.
        if not select.select([sys.stdin], [], [], 0.5)[0]:
            return ''
        prompt = json.load(sys.stdin).get('prompt', '')
    except (ValueError, OSError, AttributeError):
        return ''
    return prompt if isinstance(prompt, str) else ''


def notice_tag(prompt):
    """A notice's tag ("task-notification"), for the log."""
    if SCHEDULED.match(prompt.lstrip()):
        return 'scheduled prompt'
    return prompt.lstrip()[1:].split('>', 1)[0].split()[0][:30]


def touch(path):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'a'):
            pass
        os.utime(path)
    except OSError:
        pass


def nothing_to_say(text, now=None):
    """A response that is only an ellipsis or an emoji or two, with her time sign-off before or
    after it ("08:31 …", "08:31 🦉", "👍\n13:40", "😊 13:40": 2026-10-17, the skeptic: her spoken
    replies end with the time on its own last line), or her time sign-off alone (John, 2026-10-17
    15:35: it makes no sound in any mode). A bare time that isn't her sign-off ("8:30" for "when is
    the bus?" at 13:40) is an answer and is spoken: her sign-off is the time she replied, so only
    the minute `now` (default: this one) and SIGN_OFF_SLACK before it count. Emoji count as people
    see them: a sequence joined by zero-width joiners ("👩🏻‍🔬", "🧜🏻‍♀️") is one, and so is a flag.
    Up to three, plus Sakamoto Eyes' avatar escape (her avatar before an emoji, "👩🏻‍🔬🧜🏻‍♀️": she
    becomes a mermaid), which shows on a phone and says nothing either. Sakamoto Eyes' hub keeps
    the same rule (SilentReply.swift)."""
    bare = re.fullmatch(r'\s*(\d{1,2}):(\d{2})\s*', text)
    if bare:
        return is_sign_off(int(bare.group(1)), int(bare.group(2)), now)
    rest = without_times(text)
    if rest in ('', '…', '...'):
        return True
    units = emoji_units(rest)
    if units is None:
        return False
    limit = 4 if units and units[0] == AVATAR else 3
    return 0 < len(units) <= limit


SIGN_OFF_SLACK = 2      # minutes: her sign-off is the minute she replied in, or one of these before


def is_sign_off(hour, minute, now=None):
    """Whether HH:MM is her sign-off: the local time `now` (a Unix time; default now) or up to
    SIGN_OFF_SLACK minutes before it."""
    now = time.time() if now is None else now
    for back in range(SIGN_OFF_SLACK + 1):
        t = time.localtime(now - 60 * back)
        if (t.tm_hour, t.tm_min) == (hour, minute):
            return True
    return False


def without_times(text):
    """The text without her time sign-off before it or after it (its own last line, or after a
    space), trimmed. "08:31:15" keeps its time."""
    rest = re.sub(r'^\s*\d{1,2}:\d{2}(?![:\d])', '', text)
    return re.sub(r'(?<!\S)\d{1,2}:\d{2}\s*$', '', rest).strip()


AVATAR = '👩🏻‍🔬'


def emoji_units(text):
    """The emoji in `text` as people see them (ZWJ sequences and flags joined), or None when it
    holds anything else. Spaces between them are allowed."""
    glue = {'\u200d', '\ufe0f', '\ufe0e', '\u20e3'}
    units, joined = [], False
    for c in text:
        if c.isspace():
            joined = False
            continue
        if c == '\u200d':
            joined = True
            if not units:
                return None
            units[-1] += c
            continue
        if c in glue or 0x1F3FB <= ord(c) <= 0x1F3FF:
            if not units:
                return None
            units[-1] += c
            continue
        if unicodedata.category(c) != 'So':
            return None
        regional = 0x1F1E6 <= ord(c) <= 0x1F1FF
        if units and (joined or (regional and len(units[-1]) == 1 and 0x1F1E6 <= ord(units[-1]) <= 0x1F1FF)):
            units[-1] += c
        else:
            units.append(c)
        joined = False
    return units


def launch(text, prompted=True, turn=None):
    """Hand text to a detached speaker, silencing any earlier one. turn: turn_kind()'s, for
    Sakamoto Eyes' routing (None: 'typed', or 'notice' when not prompted)."""
    stop_speaker()
    fd, path = tempfile.mkstemp(prefix='sakamoto-voice-', suffix='.txt')
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(text)
    subprocess.Popen([sys.executable, os.path.abspath(__file__), '--speak', path]
                     + ([] if prompted else ['--unprompted']) + (['--turn', turn] if turn else []),
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def read_key(text, length=40):
    """The start of a response as app-read.mjs looks for it on the page: its letters and digits,
    lowercased, with what the page doesn't show as text (link and image addresses) left out, and
    its fenced code blocks, which app-read.mjs leaves out of the page's text too (their code, label,
    and Copy button; 2026-10-14 14:35: a reply with a code block wasn't found). A reply that is
    only code keeps it."""
    text = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', text)
    text = re.sub(r'\]\([^)]*\)', ']', text)
    prose = re.sub(r'(?ms)^[ \t]*(```|~~~).*?(^[ \t]*\1[ \t]*$|\Z)', ' ', text)
    key = ''.join(c for c in prose.lower() if c.isalnum())[:length]
    return key or ''.join(c for c in text.lower() if c.isalnum())[:length]


READ_WORDS_PER_SECOND = 2.75    # the Claude app's English voice, about 165 words a minute
READ_JA_PER_SECOND = 6.5        # and its Japanese, in characters
READ_LEAD = 1.5                 # seconds from the click to its first word
BABBLE_FACTOR = 2.0             # her streamed voice is cut once it runs past the larger of its
BABBLE_MARGIN = 8.0             # reading's estimate times this and the estimate plus this (seconds)


def reading_seconds(text):
    """About how long the Claude app takes to read this response aloud: Japanese characters at
    READ_JA_PER_SECOND, other words at READ_WORDS_PER_SECOND, after READ_LEAD."""
    spans = script_spans(strip_markers(speakable(text)))
    ja = sum(len(re.sub(r'[\s、。！？]', '', t)) for lang, t in spans if lang == 'ja')
    words = sum(len(re.findall(r'[^\W_]+', t)) for lang, t in spans if lang != 'ja')
    return READ_LEAD + words / READ_WORDS_PER_SECOND + ja / READ_JA_PER_SECOND


def babble_limit(text, cfg=None):
    """Seconds of the streamed voice after which it is babble, not her reply (Sakamoto Eyes P2.9;
    2026-10-14 19:12: the Claude app's Read aloud read about 6 s of text and went on "speaking"
    garbled, Japanese-sounding babble for 25.7 s): the larger of the reading's estimate
    (reading_seconds, without its lead) times babble_factor and the estimate plus babble_margin
    (2 and 8 s by default; 0 for either: no limit). Looser than Sakamoto Eyes' hub's own cut
    (1.5 times, or 4 s more, with a fade on the phones), which comes first when the hub runs:
    this one is the backstop without it. Tried on 188 real readings of 2026-10-14: it cut the
    three that babbled and none of the others (the closest at 84% of its limit)."""
    cfg = cfg or {}
    try:
        factor = float(cfg.get('babble_factor', BABBLE_FACTOR))
        margin = float(cfg.get('babble_margin', BABBLE_MARGIN))
    except (TypeError, ValueError):
        factor, margin = BABBLE_FACTOR, BABBLE_MARGIN
    if factor <= 0 or margin <= 0:
        return None
    expected = max(0.0, reading_seconds(text) - READ_LEAD)
    return max(expected * factor, expected + margin)


def note_app_reading(text, now=None):
    """Writes APP_READING: the app reads `text` from now until about reading_seconds() later."""
    now = time.time() if now is None else now
    try:
        os.makedirs(HOME, exist_ok=True)
        with open(APP_READING + '.tmp', 'w', encoding='utf-8') as f:
            json.dump({'started': round(now, 3), 'ends': round(now + reading_seconds(text), 3),
                       'text': strip_markers(text)}, f, ensure_ascii=False)
        os.replace(APP_READING + '.tmp', APP_READING)
    except OSError as e:
        log(f'app-reading: {e}')


def node_path():
    """node, for app-read.mjs and app-voice.mjs: on the PATH, else Homebrew's or /usr/local's; None."""
    return shutil.which('node') or next((p for p in ('/opt/homebrew/bin/node', '/usr/local/bin/node')
                                         if os.path.exists(p)), None)


APP_READ_WAIT = 8.0       # seconds app-read.mjs looks for the response's button
APP_READ_RETRY = 6.0      # then, when no message matched, this long again (the page may still be drawing)
APP_READ_AGAIN = ('no matching message', 'no Read aloud button')


def app_read(text, delay=0.0):
    """Presses Read aloud on this response (the raw text) in the Claude app; True when it clicked.
    app-read.mjs waits for the page to draw the response's button, so the delay is only a head start
    (none by default: it looks at once, then as the page changes).
    When it found no matching message (or no button at all) in its APP_READ_WAIT, it looks again for
    APP_READ_RETRY before giving up (2026-10-14 06:25: after a tool-heavy turn, the reply's message
    wasn't there yet, and the phone's own voice read it)."""
    if delay > 0:
        time.sleep(delay)
    node = node_path()
    if not node:
        log('app: node not found')
        return False
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app-read.mjs')
    for wait in (APP_READ_WAIT, APP_READ_RETRY):
        try:
            result = subprocess.run([node, script, '9229', read_key(text), str(int(wait * 1000))], capture_output=True,
                                    text=True, timeout=wait + 12)
        except (OSError, subprocess.TimeoutExpired) as e:
            log(f'app: {e}')
            return False
        said = (result.stdout or result.stderr).strip()
        log(f'app: {said[:200]} ({read_key(text, 24)})')
        if result.returncode == 0:
            note_app_reading(text)
            return True
        if not said.startswith(APP_READ_AGAIN) or wait == APP_READ_RETRY:
            return False
        log(f'app: looking again for {APP_READ_RETRY:g} s')
    return False


# ---- The Claude app's voice on the phone (output app-phone) ---------------------------------
#
# app-voice-tap (mac/AppVoiceTap, built by mac/build.sh) taps the Claude app's audio with a Core
# Audio process tap, muted on the Mac's speakers. Run with --stdout, it only captures: it writes
# the raw audio (16-bit mono PCM) to its standard output, and "ready" and a one-line result to its
# standard error. The network is this script's job: macOS's Local Network privacy blocks the tool's
# own connections once it's responsible for itself (as it must be, to hold the System Audio
# Recording permission), while this script, run by the Claude app, may reach the phone.
#
# So: connect to the phone and send the stream's header (the phone answers at once); start the
# tool and wait for "ready"; press Read aloud; pass the tool's audio on to the phone until the tool
# exits, once the app has been quiet for a moment (status 6: no sound came); then close. Since
# 2026-10-18 the app's voice is first asked for directly (AppVoice, below), and the tap and the
# button are the fallback.

APP_READ_DELAY = 0.0      # seconds from the Stop hook to looking for Read aloud (app-read.mjs waits for it; was 0.5
                          # until 2026-10-18: a head start the polling made pointless)
TAP_WAIT_START = 20       # seconds the tap waits for the app's voice after "ready" (app_read may look
                          # for the button APP_READ_WAIT + APP_READ_RETRY, and the voice takes READ_LEAD)
TAP_MAX_SECONDS = 900     # the longest reading streamed (max_chars of 6000 is about 7 minutes)
TAP_READY_TIMEOUT = 8     # seconds to start the tap
TAP_NO_SOUND = 6          # app-voice-tap's exit status when no sound came
STREAM_RATE = 24000       # the stream's frames a second (mono, 16-bit)
STREAM_ANSWER_TIMEOUT = 4.0   # seconds for the phone to answer a stream's header
STREAM_SEND_TIMEOUT = 5.0     # a phone that takes no audio for this long is given up on


def stream_header(token, text='', rate=STREAM_RATE):
    """A stream's header line, as bytes with its newline: the same keys as VoiceMessage.streamHeader
    in Message.swift, but the token first and the text last, so a receiver can check the code in
    the line's first bytes, however long the text."""
    msg = {'token': token, 'channels': 1, 'format': 'pcm16', 'kind': 'stream', 'rate': rate}
    if text:
        msg['text'] = text
    return json.dumps(msg, ensure_ascii=False, separators=(',', ':')).encode('utf-8') + b'\n'


def open_stream(address, header, timeout=STREAM_ANSWER_TIMEOUT):
    """Connects to the phone and sends a stream's header. Returns (the socket, the phone's answer:
    a dict, or None when it didn't answer in time, as phones before 0.3.0 don't), keeping what it
    says it wants (note_voice). A phone that wants the text declines the stream with
    {"ok": false, "want": "text"}, which isn't an error. Raises OSError when the phone can't be
    reached and ValueError when its answer isn't JSON."""
    host, port = split_address(address)
    sock = socket.create_connection((host, port), timeout=timeout)
    try:
        sock.settimeout(timeout)
        sock.sendall(header)
        line = b''
        try:
            while b'\n' not in line:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                line += chunk
        except socket.timeout:
            return sock, None
        ack = json.loads(line.split(b'\n', 1)[0].decode('utf-8') or 'null') or {}
        if not isinstance(ack, dict):
            raise ValueError(f'not an answer: {line[:80]!r}')
        note_voice(ack)
        sock.settimeout(STREAM_SEND_TIMEOUT)
        return sock, ack
    except BaseException:
        sock.close()
        raise


def end_stream(sock, timeout=2.0):
    """Ends the stream: closes the sending side, then waits up to `timeout` seconds for the phone
    to close its side (so the last audio isn't cut off by a reset), and closes."""
    try:
        sock.shutdown(socket.SHUT_WR)
        sock.settimeout(timeout)
        end = time.monotonic() + timeout
        while time.monotonic() < end and sock.recv(4096):
            pass
    except OSError:
        pass
    finally:
        sock.close()


VOICE_CLOCK_SOCKET = 'her-voice.sock'   # next to the hub's voice-route.json (phone_route)
COPY_MAX = 2 * 2 * STREAM_RATE          # bytes: 2 s of the stream waiting for the hub, at most


def hub_socket(cfg):
    """Sakamoto Eyes' hub's her-voice.sock (next to its voice-route.json, phone_route) when it is
    there; else None (no hub, or phone_route off)."""
    route = cfg.get('phone_route') or ''
    if not route:
        return None
    path = os.path.join(os.path.dirname(os.path.expanduser(route)), VOICE_CLOCK_SOCKET)
    return path if os.path.exists(path) else None


def voice_clock(cfg, text, rate=STREAM_RATE, mac=False, audio=True, phones=None):
    """Sakamoto Eyes' hub times the emoji in a reply to the voice reading it, from a copy of the
    stream the phones get: a Unix socket next to its voice-route.json (phone_route). Returns the
    connected socket, the header sent ({"text", "rate", "format", "channels", "mac"}, a line), or
    None when there is no hub there. It never holds up the phones: see Tap.relay's `copy`.

    Sakamoto Eyes P2.8 (2026-10-14 17:59: her voice on the Mac's speakers, heard by the lab's
    phone, went to her as John's): the hub hears of every reading on the Mac's speakers too, so
    the phones that would hear them don't listen meanwhile (a phone's echo canceller takes out
    only what that phone plays). `mac`: her voice plays on the Mac's speakers (app-both, or the
    app's voice on the Mac alone, tapped unmuted). `audio` False: no audio follows (`say` on the
    Mac, or no tap): the connection, open while her voice plays, is the whole message.

    Sakamoto Eyes P2.9: `phones`, the names of the phones the stream goes to, so the hub never
    tells them to stop listening while the Mac plays her voice too (app-both): each plays it
    itself, and its echo canceller takes it out."""
    path = hub_socket(cfg)
    if not path:
        return None
    sock = None
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(0.5)
        sock.connect(path)
        header = {'text': text, 'rate': rate, 'format': 'pcm16', 'channels': 1, 'mac': bool(mac)}
        if OWNER:
            header['as'] = OWNER       # whose reply it is: the hub times its cues for that person's phones
        if not audio:
            header['audio'] = False
        if phones:
            header['phones'] = list(phones)
        sock.sendall(json.dumps(header, ensure_ascii=False, separators=(',', ':')).encode('utf-8') + b'\n')
        sock.setblocking(False)
        return sock
    except OSError as e:
        log(f'voice clock: {e}')
        if sock:
            sock.close()
        return None


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
    """app-voice-tap --stdout, running: its audio on standard output, its status lines on standard
    error. It stays in the speaker's process group, so stopping the speaker (a new response, or
    `speak.py stop`) stops it too, and it removes its tap as it exits; it also stops by itself
    when nobody reads its audio any more."""

    name = 'app-voice-tap'

    def __init__(self, path, mute=True):
        self.proc = subprocess.Popen(
            [path, '--stdout'] + (['--mute'] if mute else []) + ['--rate', str(STREAM_RATE),
             '--wait-start', str(TAP_WAIT_START), '--max-seconds', str(TAP_MAX_SECONDS)],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.output = b''        # its standard error
        self.sent = 0            # bytes of audio passed on

    def _lines(self):
        return self.output.split(b'\n')[:-1]

    def _read_status(self):
        """Reads what's waiting on its standard error; False at its end."""
        chunk = os.read(self.proc.stderr.fileno(), 4096)
        self.output += chunk
        return bool(chunk)

    def wait_ready(self, timeout=TAP_READY_TIMEOUT):
        """True once it says the tap is running ("ready" on its standard error)."""
        fd = self.proc.stderr.fileno()
        end = time.monotonic() + timeout
        while b'ready' not in self._lines() and (left := end - time.monotonic()) > 0:
            ready, _, _ = select.select([fd], [], [], left)
            if ready and not self._read_status():
                break
        return b'ready' in self._lines()

    @property
    def seconds(self):
        """How much audio has been passed on, in seconds."""
        return self.sent / 2 / STREAM_RATE

    def relay(self, sock, timeout, record=None, copy=None, limit=None):
        """Passes its audio on to the phone until it ends it (closing its standard output), the
        phone closes the stream, sending fails, or `timeout` seconds pass, or (`limit`) more than
        `limit` seconds of audio have gone (babble: babble_limit). None when it ended by
        itself; else why the stream was cut short (it may still be running: stop() it). With
        `record`, a WAV path, the audio is also kept there. With `copy` (voice_clock's socket),
        the same bytes go to Sakamoto Eyes' hub as well, without ever waiting for it: a copy that
        can't take a chunk whole is closed (the hub then times the rest by its pace).

        sock may be a list of sockets (several phones, Sakamoto Eyes' broadcast): a phone that
        ends its stream or fails is taken out of the list (logged), and the stream is cut short
        only when none is left. An empty list, with `copy`: no phone, only the hub's copy (the
        app's voice on the Mac alone; Sakamoto Eyes P2.8)."""
        wav = None
        if record:
            try:
                wav = wave.open(record, 'wb')
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(STREAM_RATE)
            except OSError as e:
                log(f'recording: {e}')
                wav = None
        try:
            return self._relay(sock, timeout, wav, copy, limit)
        finally:
            if wav:
                wav.close()
            if copy:
                copy.close()

    def _relay(self, sock, timeout, wav, copy=None, limit=None):
        socks = sock if isinstance(sock, list) else [sock]
        phones = bool(socks)        # False: the hub's copy only
        cut = None
        copy_pending = bytearray()

        def drop(s, why):
            nonlocal cut
            cut = why
            socks.remove(s)
            watched.remove(s)
            if socks:
                log(f'app-phone: one phone of several: {why}')

        out, err = self.proc.stdout.fileno(), self.proc.stderr.fileno()
        watched = [out, err] + socks
        end = time.monotonic() + timeout
        while out in watched:
            left = end - time.monotonic()
            if left <= 0:
                return f'still going after {timeout:.0f} s'
            ready, _, _ = select.select(watched, [], [], left)
            if err in ready and not self._read_status():
                watched.remove(err)
            for s in [s for s in socks if s in ready]:
                # The phone sends nothing after its answer, so this is its end of the stream.
                try:
                    if not s.recv(4096):
                        drop(s, 'the phone ended the stream (a newer message or Stop)')
                except OSError as e:
                    drop(s, f'the phone ended the stream ({e})')
            if phones and not socks:
                return cut
            if out in ready:
                chunk = os.read(out, 65536)
                if not chunk:
                    watched.remove(out)
                    continue
                if wav:
                    wav.writeframes(chunk)
                if copy:
                    # Never waited for: what the hub can't take yet waits here, up to 2 s of it.
                    copy_pending += chunk
                    try:
                        del copy_pending[:copy.send(copy_pending)]
                    except BlockingIOError:
                        pass
                    except OSError:
                        copy_pending = bytearray(COPY_MAX + 1)
                    if len(copy_pending) > COPY_MAX:
                        log('voice clock: the hub took no more of her voice')
                        copy.close()
                        copy = None
                for s in list(socks):
                    try:
                        s.sendall(chunk)
                    except socket.timeout:
                        drop(s, f'the phone took no audio for {STREAM_SEND_TIMEOUT:.0f} s')
                    except OSError as e:
                        drop(s, f'sending to the phone failed ({e})')
                if phones and not socks:
                    return cut
                self.sent += len(chunk)
                if limit is not None and self.seconds > limit:
                    return f'babble cut at {self.seconds:.1f} s (its limit {limit:.1f} s)'
        if copy and copy_pending:
            try:      # the rest of her voice for the hub, waited for a moment at most
                copy.settimeout(0.5)
                copy.sendall(copy_pending)
            except OSError:
                pass
        return None

    def last_line(self):
        lines = [line.strip() for line in self.output.decode('utf-8', 'replace').splitlines()]
        lines = [line for line in lines if line and line != 'ready']
        return lines[-1][:300] if lines else 'no output'

    def stop(self, grace=3.0):
        """Waits up to `grace` seconds for it to end, then stops it (at once when `grace` is 0);
        returns its exit status. Its last status lines are read on the way."""
        if self.proc.poll() is None and grace:
            try:
                self.proc.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                pass
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        fd = self.proc.stderr.fileno()
        while select.select([fd], [], [], 0.2)[0] and self._read_status():
            pass
        self.proc.stdout.close()
        self.proc.stderr.close()
        return self.proc.returncode


# ---- The Claude app's voice without its button (app-voice.mjs) ------------------------------
#
# Since the app's update of 2026-10-18, a reply's Read aloud button often appears only at the next
# prompt (app-read.mjs), so the button can't be pressed when the reply is done. app-voice.mjs asks
# for the same voice directly: through the app's Main Process Debugger, it opens Read aloud's own
# text-to-speech WebSocket in the claude.ai session page (a private, undocumented endpoint of
# claude.ai's, which may change or go away with any update), and writes the audio to its standard
# output as app-voice-tap --stdout does: 16-bit mono PCM at STREAM_RATE, paced as it plays, with
# "ready" on its standard error when the first audio has come, then one line saying what happened.
# So AppVoice is a Tap, and its audio goes where the tap's would: to the phones (relay), and on the
# Mac through MacPlayer (ffmpeg). Stopping the speaker stops it, and it closes the page's socket.

APP_VOICE_PORT = 9229             # the app's Main Process Debugger (as for app-read.mjs)
APP_VOICE_READY_TIMEOUT = 11      # seconds for its first audio (app-voice.mjs gives up after 8)


def app_voice_script():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app-voice.mjs')


def debugger_reachable(port=APP_VOICE_PORT, timeout=0.3):
    """True when something listens on the app's debugger port (a quick look, before any stream opens)."""
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=timeout):
            return True
    except OSError:
        return False


def app_voice_on(cfg):
    """Whether to try the app's voice without its button: app_voice not off, node found, and the
    debugger reachable. Logs why not when it was wanted."""
    if cfg.get('app_voice') is False:
        return False
    if not node_path() or not os.path.isfile(app_voice_script()):
        log('app voice: node or app-voice.mjs not found')
        return False
    if not debugger_reachable():
        log("app voice: the Claude app's debugger is off")
        return False
    return True


class AppVoice(Tap):
    """app-voice.mjs reading `text`, as a Tap: its audio on standard output, its status lines on
    standard error. In the speaker's process group, so stopping the speaker stops it (and it closes
    the page's socket on the way out)."""

    name = 'app-voice'

    def __init__(self, text, cfg=None):
        override = []
        for key, flag in (('app_voice_voice', '--voice'), ('app_voice_language', '--language')):
            value = str((cfg or {}).get(key) or '').strip()
            if value:
                override += [flag, value]
        self.proc = subprocess.Popen(
            [node_path() or 'node', app_voice_script(), '--port', str(APP_VOICE_PORT), '--rate', str(STREAM_RATE),
             '--max-seconds', str(TAP_MAX_SECONDS)] + override,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.output = b''
        self.sent = 0
        try:
            self.proc.stdin.write(text.encode('utf-8'))
        except OSError:
            pass        # it exited already: its standard error says why
        finally:
            try:
                self.proc.stdin.close()
            except OSError:
                pass

    def wait_ready(self, timeout=APP_VOICE_READY_TIMEOUT):
        return super().wait_ready(timeout)


def start_app_voice(text, who='app voice', cfg=None):
    """The app's voice reading `text`, once its first audio has come (AppVoice; cfg's
    app_voice_voice and app_voice_language, when set, override Read aloud's); None when
    app-voice.mjs failed (logged, for the button's path, or the text, to take over). The caller has
    checked app_voice_on()."""
    if not text.strip():
        return None
    try:
        voice = AppVoice(text, cfg)
    except OSError as e:
        log(f'{who}: app-voice.mjs did not start: {e}')
        return None
    if voice.wait_ready():
        return voice
    voice.stop(grace=0)
    log(f'{who}: {voice.last_line()}')
    return None


class MacPlayer:
    """ffmpeg playing the stream (16-bit mono PCM at STREAM_RATE) on the Mac's current output, fed
    through a socket pair, so Tap.relay() treats it as one more phone. No window: a command-line
    tool. In the speaker's process group, so stopping the speaker stops it."""

    def __init__(self, cfg):
        ffmpeg = cfg.get('ffmpeg') or shutil.which('ffmpeg') or next(
            (p for p in ('/opt/homebrew/bin/ffmpeg', '/usr/local/bin/ffmpeg') if os.path.exists(p)), None)
        if not ffmpeg:
            raise OSError('ffmpeg not found')
        self.sock, theirs = socket.socketpair()
        try:
            self.proc = subprocess.Popen(
                [ffmpeg, '-hide_banner', '-loglevel', 'error', '-f', 's16le', '-ar', str(STREAM_RATE),
                 '-ac', '1', '-i', 'pipe:0', '-f', 'audiotoolbox', '-'],
                stdin=theirs, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except BaseException:
            self.sock.close()
            raise
        finally:
            theirs.close()
        self.sock.settimeout(STREAM_SEND_TIMEOUT)

    def finish(self, timeout=10.0):
        """Lets it play what it has, then ends it (at once when `timeout` is 0)."""
        try:
            self.sock.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        self.sock.close()
        try:
            self.proc.wait(timeout=timeout if timeout else 0.01)
        except subprocess.TimeoutExpired:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        return self.proc.returncode


RECORDINGS = os.path.join(STATE, 'recordings')


def recording_path(text):
    """Where this reading is kept: recordings/latest.wav (with latest.txt, the response), after the
    one before moves to previous.*. Only the last two are ever kept, for checking what the app's
    voice actually said."""
    try:
        os.makedirs(RECORDINGS, exist_ok=True)
        for ext in ('wav', 'txt'):
            latest = os.path.join(RECORDINGS, f'latest.{ext}')
            if os.path.exists(latest):
                os.replace(latest, os.path.join(RECORDINGS, f'previous.{ext}'))
        with open(os.path.join(RECORDINGS, 'latest.txt'), 'w', encoding='utf-8') as f:
            f.write(time.strftime('%Y-%m-%d %H:%M:%S') + '\n\n' + text)
        return os.path.join(RECORDINGS, 'latest.wav')
    except OSError as e:
        log(f'recording: {e}')
        return None


def app_phone(cfg, raw, text, runs, mac_runs, voices, both=False, button=True, synth=None):
    """The Claude app reads the response in its own voice, streamed live to the phone, with the
    Mac silent. Whenever that can't happen before the voice begins, the phone gets the text and
    speaks it in its own voices, so something is always heard; speak.log says why.

    The voice comes from app-voice.mjs (start_app_voice: the app's text-to-speech service, asked
    directly, for `text`) when the app's debugger is on (`synth`: app_voice_on() unless given);
    failing that, from the Read aloud button, tapped (app-voice-tap and app_read). `button` False
    (output phone): no button; when the app's voice can't be had, the phones get the response as
    output phone sends it (deliver_to_phone, with the phone_mode set).

    both (output app-both): the Mac isn't muted, so the voice plays here and on the phone. Then a
    failure doesn't fall back here; it returns where things stopped, for the caller to choose:
    'before-click' (nothing pressed yet), 'not-clicked', or 'no-sound'. None when it streamed. With
    the app's voice from app-voice.mjs, the Mac plays it too (MacPlayer: ffmpeg).
    'mac' (not both): every target was Sakamoto Eyes' Mac app (`mac_fallback`) and none answered;
    the caller reads on the Mac's own speakers instead.

    A phone that wants the text (its Claude's Voice setting) declines the stream; that's kept as
    phone_voice (open_stream), so the next response doesn't try, and this one's text is sent
    (for app-both, 'before-click': the app's voice on the Mac, the text to the phone)."""
    targets = cfg.get('targets') or [None]     # None: the usual phone (reach_phone)

    def fallback(reason, stage='before-click', to=None):
        """No stream for the phones in `to` (all of them by default): for app-both, `stage`;
        else send_text()."""
        if both:
            log(f'app-both: {reason}')
            return stage
        if not button:
            to = targets if to is None else to
            log(f'phone: {reason}; sending the response to ' + ', '.join(
                target_name(t) if t else cfg.get('phone_name') or 'the phone' for t in to))
            deliver_to_phone(dict(cfg, targets=[t for t in to if t]), text, runs, mac_runs, voices)
            return None
        send_text(reason, targets if to is None else to)

    def send_text(reason, to):
        """The text to the phones in `to`, each as its `fallback` says (a phone that plays only
        the streamed voice stays silent)."""
        silent = [t for t in to if t and t.get('fallback') == 'stream_only']
        texts = [t for t in to if t not in silent]
        if silent:
            log(f'app-phone (voice route): {reason}; silent on {", ".join(map(target_name, silent))}: '
                'it plays only the streamed voice')
        if texts:
            log(f'app-phone: {reason}; sending the text to ' + ', '.join(map(target_name, texts)))
            deliver_to_phone(dict(cfg, phone_mode='text', targets=[t for t in texts if t]),
                             text, runs, mac_runs, voices)

    token = cfg.get('phone_token', '')
    if not token:
        log('app-phone: not paired (speak.py pair CODE)')
        return 'before-click' if both else None
    synth = app_voice_on(cfg) if synth is None else synth
    path = tap_path(cfg) if button else None
    if not path and not synth:
        return fallback('app-voice-tap is not built (run mac/build.sh)' if button
                        else "the Claude app's voice is off (its debugger, or app_voice)")
    started = time.monotonic()
    header = stream_header(token, text)
    streams, no_answer, want_text, failures = [], [], [], []
    for target in targets:
        # The usual phone is found again if it moved; a routed one is tried only where it is.
        opened = reach_phone(lambda address: open_stream(address, header), target)
        if not opened:
            failures.append(f'{target_name(target)} did not answer (unreachable)')
            continue
        sock, ack = opened
        if ack is None:
            sock.close()
            no_answer.append(target)
        elif not ack.get('ok'):
            sock.close()
            if ack.get('want') == 'text':
                want_text.append(target)
            else:
                failures.append(f'{target_name(target)} refused the stream ({ack.get("error")})')
        else:
            streams.append((target, sock))
    if not streams:
        if not both and not no_answer and not want_text and all(t and t.get('mac_fallback') for t in targets):
            # Sakamoto Eyes' Mac app, in the Mac's own room, refused or isn't running: the Mac's
            # own speakers rather than silence (speak() reads there).
            log("app-phone: the Mac app didn't answer; the Mac's own speakers")
            return 'mac'
        if no_answer:
            return fallback("the phone didn't answer the stream (is its app 0.3.0 or later?)", to=no_answer)
        if want_text:
            return fallback('the phone wants the text, not the stream (its Claude\'s Voice setting)', to=want_text)
        log('app-phone: ' + '; '.join(failures) + ('' if both else '; nothing read aloud'))
        return 'before-click' if both else None
    for failure in failures:
        log(f'app-phone: {failure}')
    # Some phones stream: the others get the text now, as their settings say.
    if no_answer:
        send_text("the phone didn't answer the stream", no_answer)
    if want_text:     # their own choice: the text, whatever their fallback
        log('app-phone: ' + ', '.join(map(target_name, want_text)) + ' wants the text; sending it')
        deliver_to_phone(dict(cfg, phone_mode='text', targets=[t for t in want_text if t]), text, runs, mac_runs,
                         voices)
    socks = [sock for _, sock in streams]
    streamed = [target for target, _ in streams]

    def close_all():
        for sock in socks:
            sock.close()

    who = 'app-both' if both else 'app-phone' if button else 'phone'
    voice = start_app_voice(text, who, cfg) if synth else None
    player = None
    if voice and both:
        try:
            player = MacPlayer(cfg)     # the app's voice on the Mac too
        except OSError as e:
            log(f'app-both: no player on the Mac ({e}); the button instead')
            voice.stop(grace=0)
            voice = None
    if voice:
        tap = voice
    elif not path:
        close_all()
        return fallback("the Claude app's voice did not start" if not button
                        else 'app-voice-tap is not built (run mac/build.sh)', to=streamed)
    else:
        try:
            tap = Tap(path, mute=not both)
        except OSError as e:
            close_all()
            return fallback(f'app-voice-tap did not start: {e}', to=streamed)
    tool = getattr(tap, 'name', 'app-voice-tap')
    # The phones still streaming, and the Mac's player (relay takes out the ones that end).
    live = list(socks) + ([player.sock] if player else [])
    try:
        if not voice:
            if not tap.wait_ready():
                tap.stop(grace=0)
                close_all()
                return fallback(f'app-voice-tap did not start: {tap.last_line()}', to=streamed)
            if not app_read(raw, delay=max(0.0, APP_READ_DELAY - (time.monotonic() - started))):
                tap.stop(grace=0)
                close_all()
                return fallback("the Claude app's debugger is off, or its Read aloud button wasn't found",
                                'not-clicked', to=streamed)
        names = [target_name(t) if t else cfg.get('phone_name') or 'the phone' for t in streamed]
        cut = tap.relay(live if len(live) > 1 else live[0], timeout=TAP_MAX_SECONDS + TAP_WAIT_START + 30,
                        record=recording_path(raw), copy=voice_clock(cfg, raw, mac=both, phones=names),
                        limit=babble_limit(raw, cfg))
        status = tap.stop(grace=0 if cut else 3.0)
    except BaseException:
        tap.stop(grace=0)
        close_all()
        if player:
            player.finish(0)
        raise
    if player and player.sock in live:
        live.remove(player.sock)
    if cut:
        close_all()
        if player:
            player.finish(0)
        log(f'{who}: {cut}, after {tap.seconds:.1f} s; {tool}: {tap.last_line()}')
    elif status == TAP_NO_SOUND:
        close_all()
        if player:
            player.finish(0)
        return fallback(f'no sound from the Claude app ({tap.last_line()})', 'no-sound', to=streamed)
    else:
        for sock in socks:
            if sock in live:
                end_stream(sock)
            else:
                sock.close()
        if player:
            player.finish()
        phones = '' if len(socks) == 1 else f' ({len(live)} of {len(socks)} phones)'
        mac = ' and the Mac' if player else ''
        if status == 0:
            log(f'{who}: {tap.seconds:.1f} s to the phone{phones}{mac}; {tool}: {tap.last_line()}')
        else:
            log(f'{who}: {tool} stopped with status {status}: {tap.last_line()}')


def app_voice_here(cfg, raw, text):
    """The Claude app's voice for `text` on the Mac alone, without its button (app-voice.mjs,
    played by MacPlayer). Returns None when it can't start (logged why: the caller presses the
    button instead, app_read_here), else a function that plays it to its end (the speaker stays
    alive meanwhile, as for `say`). Under Sakamoto Eyes, the hub gets a copy as it plays (P2.8)."""
    if not text.strip() or not app_voice_on(cfg):
        return None
    voice = start_app_voice(text, 'app (Mac)', cfg)
    if not voice:
        return None
    try:
        player = MacPlayer(cfg)
    except OSError as e:
        log(f'app (Mac): no player ({e}); the button instead')
        voice.stop(grace=0)
        return None

    def follow():
        try:
            cut = voice.relay(player.sock, timeout=TAP_MAX_SECONDS + TAP_WAIT_START + 30, record=recording_path(raw),
                              copy=voice_clock(cfg, raw, mac=True), limit=babble_limit(raw, cfg))
            status = voice.stop(grace=0 if cut else 3.0)
        except BaseException:
            voice.stop(grace=0)
            player.finish(0)
            raise
        player.finish(0 if cut else 10.0)
        log(f'app (Mac): {voice.seconds:.1f} s' + (f' ({cut})' if cut else '' if status == 0 else f'; status {status}')
            + f'; app-voice: {voice.last_line()}')
    return follow


def app_here(cfg, raw, text):
    """The Claude app's voice on the Mac alone: without its button when it can (app_voice_here),
    else by pressing it (app_read_here). None when neither started; else the function to follow it."""
    return app_voice_here(cfg, raw, text) or app_read_here(cfg, raw)


def app_read_here(cfg, raw, delay=APP_READ_DELAY):
    """The Claude app reads the response on the Mac alone (output app, or app-both's voice here
    when the phone gets the text). Returns None when it didn't click (app_read), else a function
    that follows the reading to its end: call it once whatever should start alongside has
    started (the text to a phone).

    Under Sakamoto Eyes (its hub's her-voice.sock: P2.8), the hub hears of it, so the phones that
    would hear the Mac don't listen meanwhile: app-voice-tap, unmuted, sends it a copy of what the
    Mac plays (its real end is the sound's end); without the tool, a note with no audio, held
    open for the reading's estimated length. The speaker stays alive while it follows. Without a
    hub, as before: only the click."""
    if not hub_socket(cfg):
        return (lambda: None) if app_read(raw, delay) else None
    started = time.monotonic()
    path = tap_path(cfg)
    tap = None
    if path:
        try:
            tap = Tap(path, mute=False)
            if not tap.wait_ready():
                log(f'app (Mac): app-voice-tap did not start: {tap.last_line()}')
                tap.stop(grace=0)
                tap = None
        except OSError as e:
            log(f'app (Mac): app-voice-tap did not start: {e}')
            tap = None
    try:
        clicked = app_read(raw, delay=max(0.0, delay - (time.monotonic() - started)))
    except BaseException:
        if tap:
            tap.stop(grace=0)
        raise
    if not clicked:
        if tap:
            tap.stop(grace=0)
        return None
    if not tap:
        note = voice_clock(cfg, raw, mac=True, audio=False)

        def follow_note():
            if note:
                time.sleep(max(0.0, reading_seconds(raw) - READ_LEAD))
                note.close()
        return follow_note

    def follow():
        try:
            cut = tap.relay([], timeout=TAP_MAX_SECONDS + TAP_WAIT_START + 30, record=recording_path(raw),
                            copy=voice_clock(cfg, raw, mac=True))
            status = tap.stop(grace=0 if cut else 3.0)
        except BaseException:
            tap.stop(grace=0)
            raise
        log(f'app (Mac): {tap.seconds:.1f} s for the hub'
            + (f' ({cut})' if cut else '' if status == 0 else f'; app-voice-tap status {status}')
            + f'; app-voice-tap: {tap.last_line()}')
    return follow


def mac_says(cfg, raw, chunks, voices):
    """The Mac's own voices speak the chunks (`say`); under Sakamoto Eyes the hub hears of it
    for as long as they speak (a note with no audio, P2.8), so the phones that would hear the
    Mac don't listen meanwhile."""
    note = voice_clock(cfg, raw, mac=True, audio=False)
    try:
        for lang, chunk in chunks:
            subprocess.run(say_command(cfg, voices, lang) + [chunk])
    finally:
        if note:
            note.close()


class LazyVoices:
    """The installed voices, looked up (`say -v ?`, about half a second) in a background thread
    started now, so the Read aloud click doesn't wait for it; only the Mac's own voices need the
    answer, and asking for it blocks until it is in. Acts as a read-only set."""

    def __init__(self):
        self._voices = None
        self._thread = threading.Thread(target=self._look, daemon=True)
        self._thread.start()

    def _look(self):
        try:
            self._voices = installed_voices()
        except Exception as e:     # a failed lookup means no known voices, not a failed response
            log(f'voices: {e}')
            self._voices = set()

    def _set(self):
        self._thread.join()
        return self._voices

    def __contains__(self, item):
        return item in self._set()

    def __iter__(self):
        return iter(self._set())

    def __len__(self):
        return len(self._set())


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


def speak(path, prompted=True, turn=None):
    with open(PIDFILE, 'w') as f:
        f.write(str(os.getpgrp()))
    try:
        with open(path, encoding='utf-8') as f:
            text = f.read()
    finally:
        os.remove(path)
    raw = text
    turn = turn or ('typed' if prompted else 'notice')
    cfg = announcement(config()) if turn == 'announce' else owner_only(routed(config(), turn))
    if cfg.get('silent_in') or cfg.get('silent'):
        # John, 2026-10-17 15:24: a muted room hears her nowhere; its own screens show the reply.
        if cfg.get('silent_in'):
            rooms = cfg.get('silent_rooms') or [cfg['silent_in']]
            shown = [show_silently(cfg, room, raw) for room in rooms]
            log(f'voice route ({turn}): {", ".join(rooms)} {"is" if len(rooms) == 1 else "are"} muted; silent everywhere'
                + ('; shown there' if all(shown) else ''))
        else:
            log(f'voice route ({turn}): no room it may play in; silent')
        try:
            os.remove(PIDFILE)
        except OSError:
            pass
        return
    if cfg.get('targets') and cfg.get('output') in PHONE_OUTPUTS:
        log(f'voice route ({turn}): ' + ', '.join(map(target_name, cfg['targets'])))
    elif cfg.get('on_mac'):
        log(f'voice route ({turn}): the Mac ({cfg["output"]})')
    voices = LazyVoices()
    limit = int(cfg.get('max_chars') or 0)
    if limit and len(text) > limit:
        text = text[:limit].rsplit(' ', 1)[0] + '. The rest is on screen.'
    text, chunks, phone_runs = prepare(speakable(text), cfg)
    output = cfg.get('output') if cfg.get('output') in OUTPUTS else 'mac'
    if not prompted and output.startswith('app'):
        # After a notice the response may share a block with the one before; app-read presses the
        # button only when this response starts its block, so the app's voice is still tried.
        log('app: a response without a new prompt; the app reads it only if it starts its block')
    follow = None       # the app's voice on the Mac alone, followed to its end (app_here)
    if output == 'app':
        follow = app_here(cfg, raw, text)
        output = None if follow else 'mac'   # the app's own voice, else the Mac's
    elif output == 'app-both':
        # The app's voice here and streamed to the phone; failing that, as much of it as can be had.
        if cfg.get('phone_voice') == 'text':
            log("app-both: the phone wants the text; the app's voice here, the text there, no stream")
            stage = 'before-click'
        else:
            stage = app_phone(cfg, raw, text, phone_runs, chunks, voices, both=True) if chunks else 'before-click'
        if stage == 'before-click':     # the app's voice here, the text to the phone
            follow = app_here(cfg, raw, text)
            output = 'phone' if follow else 'both'
        else:                           # the app didn't speak: the Mac's voices and the text
            output = 'both' if stage else None
    elif output == 'app-phone':
        if chunks and cfg.get('phone_voice') == 'text':
            log('app-phone: the phone wants the text; sending it, no stream')
            deliver_to_phone(dict(cfg, phone_mode='text'), text, phone_runs, chunks, voices)
        elif chunks and app_phone(cfg, raw, text, phone_runs, chunks, voices) == 'mac':
            # The Mac app didn't answer: the app's voice on the Mac itself, else the Mac's.
            follow = app_here(cfg, raw, text)
            output = None if follow else 'mac'
        if output == 'app-phone':
            output = None       # the app's voice on the phone, else text there (app_phone)
    elif output == 'phone' and chunks and cfg.get('phone_voice') != 'text' and cfg.get('phone_token') \
            and app_voice_on(cfg):
        # Her own voice (the Claude app's, app-voice.mjs) streamed to the phone while the app's
        # debugger is on; else the response as output phone sends it (app_phone, button=False).
        if app_phone(cfg, raw, text, phone_runs, chunks, voices, button=False, synth=True) == 'mac':
            # The Mac app didn't answer: her voice on the Mac itself (never the button: this is
            # output phone), else the Mac's own voices.
            follow = app_voice_here(cfg, raw, text)
            output = None if follow else 'mac'
        else:
            output = None
    phone = None
    if chunks and output in ('phone', 'both'):
        # Alongside the Mac's own speech, so both start together.
        phone = threading.Thread(target=deliver_to_phone, args=(cfg, text, phone_runs, chunks, voices))
        phone.start()
    if output in ('mac', 'both') and chunks:
        mac_says(cfg, raw, chunks, voices)
    if follow:
        follow()
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
        turn = args[args.index('--turn') + 1] if '--turn' in args[:-1] else None
        speak(args[1], prompted='--unprompted' not in args, turn=turn)
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
            # From the UserPromptSubmit hook, stdin holds the prompt. Claude Code delivers notices
            # (a background task finishing, say) as prompts too; those neither count as a prompt
            # from you nor silence the voice (nor does a cron job's scheduled prompt).
            prompt = hook_prompt()
            if is_notice(prompt):
                log(f'prompt: a notice ({notice_tag(prompt)}); the voice carries on')
                return 0
            touch(PROMPTED)
            if prompt:
                note_prompt(prompt)     # a 👂 line or typed, for where the reply goes (phone_route)
            if heard_rooms(prompt):
                # A 👂 line from Sakamoto Eyes. Its hub silences her itself when you talk over her
                # (barge-in, 'hush') and holds lines while her voice plays, so a heard line that
                # arrives here was queued while she was still writing: stopping now would kill the
                # reading of the reply it followed before it starts (2026-10-16).
                log('prompt: a heard line; the hub handles barge-in, the voice carries on')
                return 0
            stop_speaker()
            stop_phone(cfg)
        elif cmd == 'hush':
            # Barge-in: Sakamoto Eyes' hub heard you talk over her. Silences her like stop (the
            # Mac's speaker, the phone, and the app-reading note), without counting as a prompt.
            stop_speaker()
            stop_phone(cfg)
            log('barge-in')
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
                'app-both': "the Mac and the phone, in the Claude app's own voice, streamed live (the "
                            "phone's own voices, from the text, when that can't start)",
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
        elif cmd == 'announce' and ' '.join(args[1:]).strip():
            # Hub-wide: every phone the hub lists, whoever's session this is (speak(), turn 'announce').
            launch(' '.join(args[1:]), prompted=False, turn='announce')
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
    if text and nothing_to_say(text):
        # "08:31 …": she had nothing to say. Speaking it would only cut off a reading in progress.
        log('response: nothing to say; the voice carries on')
        touch(RESPONDED)    # still a response: Sakamoto Eyes opens a follow-up window on it
        return 0
    prompted = not os.path.exists(PROMPTED) or not os.path.exists(RESPONDED) or \
        os.path.getmtime(PROMPTED) >= os.path.getmtime(RESPONDED)
    touch(RESPONDED)
    if text:
        launch(text, prompted, turn_kind(prompted))
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
