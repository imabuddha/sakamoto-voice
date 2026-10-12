# Sakamoto Voice

Sakamoto Voice reads Claude Code's replies aloud. When a response finishes, it speaks it on your
Mac with macOS `say`, on an iPhone running the small **Sakamoto Voice** app (an old iPhone on a
stand in another room works well), or on both. Japanese is read in a Japanese voice and everything
else in your default voice, and a response can switch voices with simple markers. Experimental
modes have the Claude desktop app read the response in its own voice, on the Mac or streamed live
to the phone.

It exists so you can hear what Claude says without watching the screen: while you're cooking,
tidying, or across the room from the Mac, or when reading the screen is tiring or hard. It is a
small accessibility aid as much as a convenience.

It has four parts:

- `plugin/`: the Claude Code plugin (Stop and UserPromptSubmit hooks, in Python, with no packages
  to install);
- `bin/sakamoto`: a command for switching it on and off, choosing where it speaks, and pairing;
- `ios/`: the iPhone app (SwiftUI) and `SakamotoVoiceKit`, its tested core;
- `mac/AppVoiceTap`: `app-voice-tap`, a capture tool for the experimental phone mode.

## Requirements

- **A Mac** with macOS 15 or later.
- **Claude Code** (the `claude` CLI; its hooks also run in the Claude desktop app's Code sessions).
- **Python 3** (`python3`; the one with Xcode's Command Line Tools is fine). No packages needed.
- For the **iPhone app**: an iPhone with iOS 18 or later, Xcode 26 or later (the icon is an Icon
  Composer document), [XcodeGen](https://github.com/yonaskolb/XcodeGen) (`brew install xcodegen`),
  and an Apple Developer account to sign it (a free one works, with a shorter-lived profile).
- For the **experimental app modes**: the Claude desktop app and Node.js 22 or later (`node`).
  `output app-phone` also needs `app-voice-tap`, built with Xcode's Swift toolchain.

## Install

From a fresh clone (the path below is wherever you cloned it):

    git clone https://github.com/imabuddha/sakamoto-voice.git
    claude plugin marketplace add /path/to/sakamoto-voice
    claude plugin install sakamoto-voice@pragmaphilia-local

Then run `/reload-plugins` in an open Claude Code session, or start a new one. The next finished
response is read aloud on the Mac.

The `sakamoto` command (`bin/sakamoto`) runs `plugin/scripts/speak.py` with the same arguments. To
have it in every Terminal, link it into a folder on your PATH, for example `~/.local/bin`:

    mkdir -p ~/.local/bin
    ln -s /path/to/sakamoto-voice/bin/sakamoto ~/.local/bin/sakamoto

Then:

    sakamoto test        # a sample line
    sakamoto stop        # silence the current response (on the phone too)
    sakamoto off         # mute until "sakamoto on"
    sakamoto status      # the settings
    sakamoto             # all the commands

(Without the link, `python3 /path/to/sakamoto-voice/plugin/scripts/speak.py test` and so on do the
same.)

## How it works

A **Stop hook** (`plugin/hooks/hooks.json`) runs `plugin/scripts/speak.py` when a response finishes.
It takes the response's text (the hook's `last_assistant_message`, or the transcript's final text in
older Claude Code versions), makes it speakable (code blocks omitted, links read by their words,
Markdown marks, tables, and emoji dropped, ⌘⌥⌃⇧ read as key names), and hands it to a detached
speaker, so the hook returns at once and never holds up Claude Code. The speaker says it on the
Mac, sends it to the phone, or both. A new response interrupts one still being spoken, on the Mac
and on the phone, and sending a new message silences it (a UserPromptSubmit hook runs
`speak.py stop`). Subagents don't speak (they end with SubagentStop, not Stop).

### Voices and voice markers

Japanese script (kana, kanji, full-width forms) always goes to the Japanese voice. Other text goes
to the **default voice**, which each place that speaks picks for itself:

- **On the Mac** (and in audio rendered for the phone), `default_lang`: `"auto"` (the default) is
  the macOS system language's voice (`voice_en` unless the system language is Japanese), `"en"` is
  `voice_en`, and `"ja"` has `voice_ja` (Kyoko) read everything, English included.
- **On the phone**, its own setting, Default Voice for Other Text: English (the default) or
  Japanese. The Mac sends such text tagged `"default"` so the phone applies its setting; the
  Preview button and text that arrives without runs follow it too.

A response can switch voices with markers, for comedic or teaching effect:

| Marker | Effect |
| --- | --- |
| `〔en〕` | the English voice (`voice_en`) from here |
| `〔ja〕` | the Japanese voice (`voice_ja`) from here |

A marker lasts until the next marker or the end of its paragraph (a blank line); then the default
voice resumes. Markers hold on the phone too, whatever its setting. Japanese script inside an
`〔en〕` stretch is still read in the Japanese voice. Markers are never spoken or shown on the
phone; unknown ones, such as `〔xx〕`, are dropped and change nothing (a marker is the brackets
around 1 to 10 ASCII letters or hyphens, so Japanese in the same brackets, such as `〔注〕`, is
ordinary text). For example:

    〔ja〕Kyoko reads this line. 〔en〕And the English voice reads this one.

    This paragraph is the default voice's again.

To have Claude use markers, ask it to (for example, in your `CLAUDE.md`).

## Settings

Settings live in `~/.config/sakamoto-voice/config.json`, created on first use. `sakamoto status`
prints them; most are set by the commands below, and the rest you can edit by hand.

| Setting | Values |
| --- | --- |
| `enabled` | `true` or `false` (`sakamoto on`, `sakamoto off`) |
| `voice_en`, `voice_ja` | the Mac's voices, by name, as `say -v '?'` lists them; empty `voice_en` uses the system voice (Spoken Content's System Voice, which can be a Siri voice); `voice_ja` is `"Kyoko"` by default |
| `default_lang` | `"auto"`, `"en"`, or `"ja"` (above) |
| `rate` | words per minute (`say -r`); 0 keeps the voice's own pace |
| `device` | an audio output for `say -a`, such as a paired Bluetooth speaker (`say -a '?'` lists them); empty uses the current output |
| `max_chars` | a longer response is cut there, with a note that the rest is on screen (6000) |
| `output` | `"mac"` (the default), `"phone"`, `"both"`, `"app"`, `"app-both"`, or `"app-phone"` (`sakamoto output ...`; the last three are experimental, below; `app-both` is the Claude app's voice on the Mac and streamed to the phone, as `app-phone` does but without muting the Mac) |
| `phone_mode` | `"text"` (the default; the phone speaks in its own voices) or `"audio"` (rendered on the Mac with `say -o` in `voice_en`, `voice_ja`, and `rate`, and played on the phone; `sakamoto phone-mode ...`) |
| `phone_token` | the phone's pairing code (`sakamoto pair` sets it) |
| `phone`, `phone_name` | the phone's `host:port` and Bonjour name, found and kept automatically |
| `phone_remote` | another address for the phone, tried first, such as its Tailscale address (`"100.x.y.z:47811"`), so it's reached away from home too; when it fails, the local network as usual (empty by default) |
| `phone_voice` | what the phone last said it wants for the Claude app's voice, `"stream"` or `"text"`, kept automatically from its every answer (empty until it has answered; a phone app older than 1.0 counts as `"stream"`); see "The phone has the last word" below |
| `app_voice_tap` | where `app-voice-tap` is, for `app-phone`, when it's not in `~/.local/bin` or on the PATH |
| `dev_path` | for working on the plugin (see Development) |

Better voices: System Settings → Accessibility → Spoken Content → System voice → Manage Voices;
download, for example, Zoe or Ava (Premium) and Kyoko (Enhanced), then put their names, exactly as
`say -v '?'` lists them, in the config. A voice that isn't installed falls back to the system voice.

Failures in the detached speaker are silent but logged to `~/.config/sakamoto-voice/speak.log`
(which starts over past 64 KB, keeping the previous one as `speak.log.1`).

## The iPhone app

Apple doesn't allow third-party AirPlay receivers, so the phone runs its own small app, Sakamoto
Voice (`ios/`), and the Mac sends it each response over the local network. The app:

- **Listens** on the local network (TCP, advertised with Bonjour as `_sakamotovoice._tcp`, port
  47811 when it's free). Each connection carries one JSON message, which the app answers with a
  JSON ack, or a live audio stream: a JSON header line, answered at once, then raw 16-bit PCM until
  the Mac closes it. Every ack to a message with the right pairing code also says what the phone
  wants for the Claude app's voice, `"voice": "stream"` or `"voice": "text"`, and a stream's header
  that arrives while it wants the text is declined, which isn't an error:
  `{"ok": false, "want": "text", "voice": "text", ...}` with no `error`, after which the Mac sends
  the text. The protocol is described in
  `ios/SakamotoVoiceKit/Sources/SakamotoVoiceKit/Message.swift`.
- **Pairs** with a 6-digit code it shows (New Code makes another, which unpairs the Mac). Messages
  without the code are refused; ten wrong codes in a minute lock it for a minute.
- **Speaks text** with the iPhone's own voices: Japanese script and `〔ja〕` text in the Japanese
  one, `〔en〕` text in the English one, and the rest in the default voice that Settings' "Default
  Voice for Other Text" picks (English by default). The voices are by default Moira (Irish English,
  the best quality installed) and Kyoko. Settings has a voice picker for each, a rate slider, and
  Preview. Siri voices aren't available to apps; Enhanced and Premium voices can be downloaded in
  the iPhone's Settings → Accessibility → Spoken Content → Voices.
- **Plays audio** the Mac rendered, so the phone can speak in the Mac's voices, including a Siri
  system voice (`phone_mode` `audio`).
- **Plays live streams**: the Claude app's own voice as it reads aloud on the Mac
  (`output app-phone`, below), through a quarter-second jitter buffer, with "Streaming" in the
  status bar and the response's text on screen once the voice begins. Repeat plays the last stream
  again. A new message, Stop on the phone, or a new prompt on the Mac ends a stream.
- **Chooses Claude's voice or the text**, to save mobile data (a stream is about 48 KB/s, roughly
  170 MB an hour). Settings' "Claude's Voice" offers **Claude's Voice** (always take the stream),
  **Text on Cellular** (the default: the stream on Wi-Fi, the text on cellular data or another
  network iOS counts as expensive, such as a Personal Hotspot), and **Text Only**. With the text,
  the phone reads it in its own voices. Its footer says which network the phone is on and what
  the Mac is told.
- **Shows** the last five messages, newest first and large, older ones below in a lighter style;
  each new message scrolls back to the top so its beginning is in view. One slim bar at the top
  holds the status (a dot for listening or speaking, and Awake, marked with Miss Sakamoto's 👩🏻‍🔬 avatar) and small Stop, Repeat, and Settings
  buttons, so the text gets nearly the whole screen, sideways on a stand or upright.
- **Stays awake** (on by default): with "Stay Awake in the Background" on, it loops a near-silent
  sound, which keeps iOS from suspending it, so it keeps listening with the screen locked or another
  app in front. This costs battery; keep the phone on its charger. "Only Between These Times" limits
  it to a daily span (for example 07:00 to 23:00); outside it, and with staying awake off, the app
  speaks only while it's open, and after the end time it has to be opened again to wake it. Calls
  and alarms interrupt it; it restarts when they end. Other apps' music plays on alongside it.
- **Keeps the screen on** while it's open (on by default; for the stand).

It runs on iOS 18 and later, so older phones such as the iPhone XS can serve as speakers.

### Build and install it with your own team

Once per phone:

1. Connect the phone to the Mac with a cable (or, after that, pair it for Wi-Fi in Xcode's Devices
   and Simulators window), unlock it, and tap Trust.
2. Turn on Developer Mode on the phone (Settings → Privacy & Security → Developer Mode; it appears
   after the phone has been connected to Xcode) and restart it when asked.

Once per clone, set up signing:

1. Put your Apple Development team's ID (developer.apple.com/account → Membership details, or
   Xcode → Settings → Accounts) in `ios/Config/Signing.local.xcconfig`, which git ignores:

       DEVELOPMENT_TEAM = ABCDE12345

2. Give the app a bundle ID of your own: in `ios/project.yml`, change `PRODUCT_BUNDLE_IDENTIFIER`
   (`com.pragmaphilia.SakamotoVoice`) and `bundleIdPrefix` to your own reverse-DNS name. Bundle IDs
   are unique across all teams, so the one in the repository can't be registered by yours.

Then build and install it:

    cd /path/to/sakamoto-voice/ios
    scripts/build.sh install              # or: scripts/build.sh install "Example iPhone"

The script generates the Xcode project (XcodeGen), builds a Release app signed with your team
(registering the phone with the team if it's new), and installs it with `devicectl`. Without a team
it stops and says where to put one. Alternatively, run `xcodegen generate` in `ios/`, open
`ios/SakamotoVoice.xcodeproj`, pick the phone, and Run. A development-signed app runs for a year
with a paid team's profile (a free account's lasts 7 days), then needs installing again.

### Pair the Mac with the phone

Open Sakamoto Voice on the phone (allow Local Network access when asked) and read its code, then:

    sakamoto pair 123456
    sakamoto output phone        # or "both", or back to "mac"
    sakamoto phone-test          # a sample line on the phone, now

`pair` finds the phone with Bonjour (macOS's `dns-sd`; no Python packages needed) and remembers its
address; when a send fails, the speaker looks for it again. With two phones running the app, each
with its own code, the one whose code was given is the one paired.

### The icon

The app's icon is its own character, Bleep: a boxy coral outline with two round eyes, an antenna,
two short legs, and its mouth open in song, one arm reaching toward three teal sound-wave arcs,
drawn as glowing vector lines on a dark indigo fill. It is an Icon Composer document,
`ios/SakamotoVoice/AppIcon.icon`: an `icon.json` with the fill (a darker one for the dark
appearance) and two transparent 1024×1024 layers, `Assets/creature.png` in front of
`Assets/waves.png`. On iOS 26 the system lights the layers with depth, in the default, dark, tinted,
and clear appearances; for iOS 18, Xcode flattens it into ordinary icon images. Both layers are
drawn by a script, which you can edit and run (offscreen; needs Pillow and NumPy):

    python3 ios/scripts/make-icon.py --preview icon.png    # rewrites AppIcon.icon; --preview is optional

`--preview` also writes the composed icon, flat, with rounded corners, for a look.

## Experimental: the Claude app's own voice

> **Read this first.** These two modes work through the Claude desktop app's **Main Process
> Debugger**, a developer feature. While it is on, any program running on your Mac can run code
> inside the Claude app, which holds your signed-in Claude account. Use them only if you accept
> that trade, and turn the debugger off when you don't need it.

The Claude desktop app reads a response aloud in its own voice when you press the response's
**Read aloud** button, and it offers no supported way to press it from outside: no AppleScript, no
App Intents, no URL action, no keyboard shortcut, nothing in the accessibility tree, and nothing in
the Claude Code plugin API. The one way in is the app's own debugging feature: with
**Developer → Enable Main Process Debugger** on (the Developer menu appears after Help →
Troubleshooting → Enable Developer Mode), a Node inspector listens on `127.0.0.1:9229`, and
`plugin/scripts/app-read.mjs` asks the app, through it, to click the Read aloud button of the
response that just finished, on the focused Code session's page. It finds that response by its
opening text (letters and digits only, so formatting doesn't matter), waits up to 8 s for the page
to draw its button, and marks each button it presses, so an earlier response is never read by
mistake. A button reads its whole block, and a reply that follows a notice rather than a new
message can share a block with the reply before it; when the response starts well into its block,
the button isn't pressed, and the Mac's or the phone's voices read just the new response. In the
same way, a response that comes without a new prompt from you (after a notice, such as a background
task finishing) skips the app's voice: the app would read the response before it too. Each
press is logged in `speak.log`. When the debugger isn't on (it switches off whenever
the app restarts) or the click fails, the Mac's own voice (`voice_en`, `voice_ja`) speaks instead,
and `speak.log` says why. This relies on the app's current page structure, so an app update can
break it; the fallback then speaks instead.

**The risk, plainly:** while the debugger is on, any program running on the Mac can connect to that
port and run code inside the Claude app, which holds your signed-in Claude account. The port is on
localhost only, so nothing off the Mac reaches it, but a malicious local program would have an open
door. Turn the debugger on only when you want this, and judge the trade for yourself. Claude
Code's own safety check flagged this as creating a remote-code-execution surface, which is fair.
This mode exists because no supported route does; we've asked Anthropic for one.

### `output app`: on the Mac

    sakamoto output app          # the app's voice when its debugger is on, else the Mac's

### `output app-phone`: streamed to the phone

For when you're away from the Mac: the same voice, streamed live to the phone, with the Mac's
speakers silent. With `output app-phone`, the speaker (still detached; the hook never waits):

1. connects to the phone (finding it again if it moved) and sends the stream's header, carrying
   the response's text for its screen; the phone accepts it at once (or refuses a wrong code);
2. starts `app-voice-tap --stdout` (`mac/AppVoiceTap`), which taps the Claude app's audio with a
   Core Audio **process tap**: every process running from inside `/Applications/Claude.app` (its
   audio comes from a helper process) or with the bundle ID `com.anthropic.claudefordesktop` or
   `...claudefordesktop.helper` (on macOS 26 and later the tap also names those bundle IDs, so a
   helper that starts later is tapped from its first sound). The tap is *muted when tapped*: while
   it's read, the Claude app is silent on the Mac. Only the Claude app is captured; other apps
   play on as usual;
3. presses Read aloud, as `output app` does (the same debugger; the same risk, below);
4. `app-voice-tap` writes the voice to its standard output as 16-bit mono PCM at 24 kHz (about
   48 KB/s), leaving out the silence before and after it, until the app has been quiet for 2.5 s
   (or 15 minutes have passed), and exits; the speaker passes it on to the phone over the stream's
   one TCP connection as it comes, and the phone plays it as it arrives.

**Why the work is split.** `app-voice-tap` only captures; `speak.py` owns the network. The tool
re-launches itself as its own "responsible" process, so that System Audio Recording is its own
permission (below); but then macOS's **Local Network** privacy blocks its connections to the
phone ("No route to host"), even with app-voice-tap allowed under Local Network in System
Settings. `speak.py`, which the Claude app runs, may already reach the phone, so it opens the
stream and sends the audio, and the tool needs no network permission at all.

Whenever the voice can't start, the phone gets the response as **text** instead and reads it in
its own voices, so you always hear something: when the app's debugger is off or the click fails,
when `app-voice-tap` isn't built or can't start (the permission is off, say), when the phone's app
is older than 0.3.0 (it doesn't answer a stream), or when no sound comes from the app within 10 s.
When the phone can't be reached at all, or refuses the pairing code, nothing is read aloud (the
Mac stays silent). A phone that stops taking audio for 5 s is given up on. `speak.log` says what
happened, each time.

**The phone has the last word.** Only the Mac opens connections, so the phone says what it wants
(its Claude's Voice setting, above, and its network at that moment) in every answer it gives, to
pings, stops, and text as well as streams, and the Mac keeps the latest as `phone_voice`. While
that is `"text"`, `app-phone` sends the phone the text and starts no tap, and `app-both` has the
Claude app read on the Mac alone (unmuted; the Mac's own voices when the debugger is off) and sends
the phone the text. While it's `"stream"`, or not known yet, both stream as above; when the phone
then declines the stream (it has just moved to cellular data, say), the Mac remembers that and
sends the text instead, and `app-both` still presses Read aloud for the Mac. So a change on the
phone reaches the Mac with its next answer, and coming back to Wi-Fi, one response may still
arrive as text before the stream resumes. Each choice is logged in `speak.log`. A phone app older
than 1.0 never says, and is streamed to as before.

On cellular data with a VPN such as Tailscale, the phone's network path runs over the VPN's tunnel
interface rather than the cellular one. iOS is meant to give a tunnel the type and the cost of the
interface it runs over (its delegate), so the path should still count as cellular and expensive, and "Text on
Cellular" should still ask for the text; this follows from how Network.framework reports paths
(`isExpensive`, `usesInterfaceType(.cellular)`) and hasn't yet been checked on a phone. The
footer in Settings shows what the phone sees.

A new prompt stops the stream (and tells the phone to stop), and a new response replaces it:
stopping the speaker stops `app-voice-tap` with it, which removes its tap (the tool also stops by
itself when nobody reads its audio any more). One catch: the Claude app's own reading isn't stopped (nothing here can press its stop button), and once
the tap is gone its mute is too, so the rest of a long reading interrupted that way is heard on the
Mac.

**Set it up once**, at the Mac, after pairing the phone:

    mac/build.sh                 # builds bin/app-voice-tap, signs it, links ~/.local/bin/app-voice-tap
    app-voice-tap --check        # asks macOS for the permission (answer its prompt)
    sakamoto output app-phone

`mac/build.sh` needs only the Swift toolchain (Xcode); run it again after changing the tool.

**The permission.** Capturing another app's audio needs macOS's **System Audio Recording**
permission. `app-voice-tap --check` asks for it: macOS shows a prompt for **app-voice-tap**, with
the reason "Sakamoto Voice Tap captures the Claude app's voice as it reads a response aloud and
sends it to the Sakamoto Voice app on your iPhone"; choose **Allow**. It's then listed, and can be
turned off again, in **System Settings → Privacy & Security → Screen & System Audio Recording**,
under **System Audio Recording Only**. (`app-voice-tap` re-launches itself as its own "responsible"
process, so the permission is its own, not that of whichever app started it; should macOS name
Claude or Terminal instead, allowing that works too.) `mac/build.sh` signs the tool with the first
Apple Development certificate in your keychain, when there is one, so the permission survives
rebuilds; signed ad hoc, macOS asks again after each rebuild. Until it's allowed, the phone gets
the text.

The risk note above applies unchanged: this mode uses the same debugger. The tap itself opens
nothing and, as `speak.py` runs it, connects nowhere: the speaker connects out to the paired phone,
with its pairing code.

To look at it live:

    app-voice-tap --list         # Core Audio's processes: C for the Claude app's (tapped), P for playing now
    cd ios/SakamotoVoiceKit && swift run voice-listen 123456 --save ~/Desktop/streams
                                 # a stand-in phone on the Mac that keeps each stream as a WAV
    app-voice-tap --to 127.0.0.1:47811 --token 123456 --mute --verbose
                                 # by hand: prints "ready"; then press Read aloud in the app
    app-voice-tap --stdout --mute --verbose > ~/Desktop/voice.pcm
                                 # as speak.py runs it: the raw audio to a file, the rest on screen

`--to` (the tool connecting to the phone itself) is kept for trying it by hand like this, on
the Mac's own loopback address; to a phone on the network, Local Network privacy blocks it (see
above) unless `--no-disclaim` makes the app that started it (Terminal, say) responsible, which
then needs the System Audio Recording permission itself.

## Privacy

Everything stays on your Mac and your local network. There is no telemetry, no account, and no
server: the plugin speaks with macOS `say`, finds the phone with Bonjour, and sends responses
straight to it; the phone app only listens on the local network and never connects out. The app
modes talk only to the Claude app on `127.0.0.1`. Files are kept in
`~/.config/sakamoto-voice/`: the settings, and `speak.log`, which records what happened (errors,
the phone's address, and, in the app modes, the first few letters of each response it matched).

One thing to know: messages to the phone travel over your local network **unencrypted**, guarded
only by the pairing code, so someone else on the same network could read what's being spoken. Use
it on a network you trust.

## Development

The tests, all headless (nothing is launched and no audio is captured):

    python3 -m unittest discover -s plugin/tests        # the plugin
    swift test --package-path ios/SakamotoVoiceKit       # the phone app's core, on the Mac
    mac/build.sh test                                    # app-voice-tap's core

    cd ios
    scripts/build.sh test       # SakamotoVoiceKit's tests on an iOS simulator
    scripts/build.sh sim        # a simulator build (no team needed)
    scripts/build.sh device     # a signed build for any iPhone, to check signing

`scripts/build.sh` uses the Xcode that `xcode-select` picks (or `$DEVELOPER_DIR`), and the
`SIMULATOR` environment variable names the simulator for `test` (iPhone 17 by default).

**Working on the plugin:** Claude Code runs an installed plugin from its own cached copy, so an edit
in the checkout normally needs `claude plugin marketplace update`, `claude plugin update`, and a
restart before it's heard. To skip that while you work, point the installed copy at your checkout,
in `~/.config/sakamoto-voice/config.json`:

    "dev_path": "/path/to/sakamoto-voice/plugin"

The cached `speak.py` then hands over to the checkout's at once, so edits to the scripts take effect
with the next response. Changes to `hooks.json` still need the update and the restart. Leave
`dev_path` empty (the default) for normal use.

`ios/project.yml` is the source of the Xcode project (generated and git-ignored); signing is in
`ios/Config/Signing.xcconfig`, with your team in the git-ignored `Signing.local.xcconfig` beside it.
The app's version (`MARKETING_VERSION` in `project.yml`) follows the plugin's, except for changes on
one side only: both are 1.0 (the phone chooses Claude's voice or the text, and the Mac follows), the
app as build 8. The app's pure parts (protocol, pairing, language runs, schedule, keep-alive
sound, the Claude's Voice choice, and streams' framing and jitter buffer) and its receiver are in the `SakamotoVoiceKit`
package, which `app-voice-tap` uses too, and which also has `voice-listen`, a stand-in phone on the
Mac that prints what arrives (and, with `--save DIR`, keeps streams as WAV files):

    cd ios/SakamotoVoiceKit && swift run voice-listen 123456
    cd ios/SakamotoVoiceKit && swift run voice-listen 123456 --text   # as a phone that wants the text

(macOS's Local Network privacy may keep other machines, and the Mac's own non-loopback addresses,
from reaching it; for a local try, set `"phone": "127.0.0.1:47811"` in the config.)

## Ideas

- A small background Mac app that sends the speech to an AirPlay speaker or a HomePod.
- Ducking other audio while speaking; a reminder notification at the phone schedule's start time;
  falling back to the Mac when the phone doesn't answer.

## License and affiliation

MIT; see [LICENSE](LICENSE). A Pragmaphilia Labs project.

Sakamoto Voice is an independent project. It is not affiliated with, endorsed by, or supported by
Anthropic. "Claude" and "Claude Code" are Anthropic's names for its products, used here only to say
what this works with.
