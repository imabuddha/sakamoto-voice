# Sakamoto Voice

Sakamoto Voice reads Claude Code's replies aloud. When a response finishes, it speaks it on your
Mac with macOS `say`, on an iPhone running the small **Sakamoto Voice** app (an old iPhone on a
stand in another room works well), or on both, and the phone can pass each one on to an Apple
Watch. Japanese is read in a Japanese voice and everything
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
- `ios/`: the iPhone app and its Apple Watch app (SwiftUI) and `SakamotoVoiceKit`, their tested
  core;
- `mac/AppVoiceTap`: `app-voice-tap`, a capture tool for the experimental phone mode.

## Here's how to deal with 🍎💩

What we learned the hard way setting this up with Xcode 27.1, iOS 27, and watchOS 27. Read this
before you lose an evening to it.

**Xcode 27 won't find your Apple Watch by itself.** Older Xcodes paired a watch automatically
through its iPhone. Xcode 27 doesn't: it sees the watch, logs "supports user-driven network
pairing flows. Skipping companion proxy bootstrap pairing", and says nothing to you. The watch never
shows up in Device Hub or as a run destination (only "Any watchOS Device"), and the watch's
Developer Mode switch doesn't exist yet. Restarting things, toggling Wi-Fi, and resetting the
phone don't help. Pair it by hand:

1. Use the Xcode that has the watchOS platform installed (Settings → Components → watchOS; about
   3.8 GB), with the iPhone plugged in and unlocked and the watch unlocked on your wrist.
2. In **Device Hub** (Xcode 27's replacement for the Devices window: the Xcode menu → Open
   Developer Tool → Device Hub), click **+** → **Pair Nearby Device…** → **Apple Watch**, and leave
   that sheet open.
3. Now, on the watch, **Settings → Privacy & Security → Developer Mode** appears. Turn it on; the
   watch restarts; confirm with Turn On and your passcode.
4. On the watch again, **Settings → Privacy & Security**, at the very bottom: **Pair with** your
   Mac. Enter the PIN it shows in Device Hub. (Settings → Developer → Paired Computers only lists
   Macs; it can't pair.) The watch now appears in Device Hub.
5. If there's no PIN, or it hangs on "Waiting to Pair", turn the iPhone off completely and try
   again.

Don't remove the watch from Xcode afterward, and don't tap Don't Trust: developers report it's hard
to get back.

**Then install the watch app directly** (the phone's Watch app may still refuse a
development-signed app): build the watch scheme for the watch, which registers it with your team,
and install it with `devicectl`:

    cd ios
    xcodebuild -project SakamotoVoice.xcodeproj -scheme SakamotoVoiceWatch -configuration Release \
      -destination "id=<the watch's UDID>" -allowProvisioningUpdates \
      -allowProvisioningDeviceRegistration DEVELOPMENT_TEAM=<your team> \
      -derivedDataPath build/DerivedData build
    xcrun devicectl device install app --device <the watch's UDID> \
      build/DerivedData/Build/Products/Release-watchos/SakamotoVoiceWatch.app

(`xcrun devicectl list devices` shows the watch's UDID once it's paired; `scripts/build.sh` makes
the Xcode project; rebuild and reinstall the iPhone app too, so its embedded watch app matches.) A
first attempt can fail with "Connection invalid" until the watch is registered and awake.

**If the iPhone's Watch app won't install ANY app** (Install spins, then shows Install again, even
for Apple's own apps, while installing from the watch's own App Store works): on the iPhone,
Settings → your name → Media & Purchases → Sign Out, then sign back in. That fixed it for us;
restarts, Reset Sync Data, Automatic App Install, and Airplane Mode didn't.

**Better voices on the watch.** The watch's default voices are rough. Download Premium or Enhanced
voices on the watch under **Settings → Accessibility → Live Speech** (they're shared with apps),
then choose them in the watch app's **Voices** section (at the bottom). Until you choose, it uses
the highest-quality voice installed, from any region.

**Known limitations**

- The watch speaks only while its app is in front (watchOS gives background audio only to
  long-form audio over Bluetooth). Otherwise you get a notification with a Speak button.
- Notifications go to the watch only while the iPhone is locked.
- Claude's own voice can't be streamed to the watch; the watch reads the text in its own voices.
- On the phone and watch, the voice switches by script: Japanese text in the Japanese voice;
  numbers, times, and Latin letters in the English one.
- Streamed replies currently lose the 〔en〕/〔ja〕 markers on the way to the watch (a fix is
  planned).
- The Claude app's Read aloud, with a Japanese voice reading English, sometimes slips into a few
  seconds of unrelated Japanese at numbers; it's reported to Anthropic.

## Requirements

- **A Mac** with macOS 15 or later.
- **Claude Code** (the `claude` CLI; its hooks also run in the Claude desktop app's Code sessions).
- **Python 3** (`python3`; the one with Xcode's Command Line Tools is fine). No packages needed.
- For the **iPhone app**: an iPhone with iOS 18 or later, Xcode 26 or later (the icon is an Icon
  Composer document), [XcodeGen](https://github.com/yonaskolb/XcodeGen) (`brew install xcodegen`),
  and an Apple Developer account to sign it (a free one works, with a shorter-lived profile).
- For the **Apple Watch app** (optional): an Apple Watch with watchOS 11 or later, paired with that
  iPhone.
- For the **experimental app modes**: the Claude desktop app and Node.js 22 or later (`node`).
  The app's voice on the Mac without its button needs `ffmpeg` (`brew install ffmpeg`); the
  button's path for `output app-phone` needs `app-voice-tap`, built with Xcode's Swift toolchain.

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
    sakamoto hush        # the same, logged as a barge-in (Sakamoto Eyes runs it when you talk over her)
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
`speak.py stop`). A response that is only an ellipsis or an emoji or two, after an optional time ("08:31 …",
"08:31 🦉"), isn't spoken at all and interrupts nothing: it's how Claude says it has nothing to add, for instance
after a routine notice, and speaking it would only cut off a reading in progress. Emoji count as people
see them ("👩🏻‍🔬" is one, up to three), a reply that is only the time ("08:31"), and a reply that only changes Sakamoto Eyes' avatar ("👩🏻‍🔬🧜🏻‍♀️")
are silent too. Subagents don't
speak (they end with SubagentStop, not Stop).

While the speaker runs, `~/.config/sakamoto-voice/speaker.pid` names it. Sakamoto Eyes (a
listening companion, in development and not yet public) watches that file to know when her voice is on, and runs `speak.py hush`
when you start talking over her (barge-in): it silences her as `stop` does, without counting as a
prompt, and logs a "barge-in" line in `speak.log`.

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
| `phone_route` | for Sakamoto Eyes (several phones, one per room): the path of its hub's `voice-route.json` (empty, the default, turns it off). A reply to a line the hub heard goes only to the phone in that room, with the Mac quiet so that phone's echo canceller can work; if that phone doesn't answer, nothing is heard (never a phone in another room). When the route names the Mac instead (`"mac": true`: the line came from the Mac app's room, and from the Mac app itself or with no phone there that plays her voice), the reply plays only on the Mac, as `output`'s Mac side (`app-phone` and `app-both` as `app`, `phone` and `both` as `mac`), and no phone gets it. What Claude says unprompted (after a notice) or in reply to a typed prompt goes to the room he was last heard in when the hub knows it, else to every room that isn't silenced; with `output app-phone` and no phone listed in his room (the Mac app's room, say), it plays on the Mac app there rather than nowhere. When the hub also says where her voice may play (Sakamoto Eyes hub 0.2.35: `level`, `levels`, `mac_silent`, each phone's `silent`; hub 0.2.36: `mac_rooms`, `his_room`; counted only while its `status.json` beside the file is under a minute old), a reply to a heard line belongs to the room its 👂 label names, a late line's too (a route to another room isn't followed: with none to that room, the listed phones there and the Mac when its speakers are there), and a room whose level is Mute or Ears off hears her nowhere: a reply to a line heard there plays in no room and not on the Mac, and goes to the hub's `commands.jsonl` (created when missing) as a `silent_reply` for its sign or board there instead; a reply to a notice or to a typed prompt goes only to the room John is in when the hub knows it (nothing when that room is muted), else to every listed phone in a room that isn't muted, and to the Mac as `output` says unless its speakers are in a muted room, and is silent when nothing is left (no route is followed for these). A reply that is only emoji (or "…") with her time before or after it, or only her time sign-off, is not spoken; a bare time that isn't the time now (or up to two minutes before) is an answer, and is. Every phone needs the same pairing code. A route older than 30 minutes changes nothing. When the hub listens on `her-voice.sock` next to that file, the streamed voice is also copied there, never waiting for the hub, so it can time the emoji in a reply to the moment her voice reaches them. The hub also hears of every reading on the Mac's own speakers, as it plays (marked `mac`): the app's voice on the Mac alone through `app-voice-tap` unmuted (the speaker then follows the reading to its end), or a note with no audio while `say` speaks; its phones that would hear the Mac don't listen meanwhile, since a phone's echo canceller takes out only what it plays itself |
| `babble_factor`, `babble_margin` | the Claude app's voice streamed to the phone is cut once it runs past the larger of the reading's estimated length times `babble_factor` and that length plus `babble_margin` seconds: its Read aloud sometimes goes on "speaking" garbled babble long after the response's text ends (2 and 8 by default; 0 for either turns it off). Sakamoto Eyes' hub cuts sooner, with a fade, when it runs |
| `app_voice` | `true` (the default): while the Claude app's debugger is on, the app's voice is asked for directly, without its Read aloud button, for `app`, `app-phone`, `app-both`, and `phone` (see "Without the button" below); `false`: never (the button, and the phone's own voices for `phone`, as before) |
| `app_voice_voice`, `app_voice_language` | empty (the default): the voice and language Read aloud uses, from the account's settings (Settings > General > Voice); set, a voice ID (`ja-akarui`) or a language code (`ja`) that `app-voice.mjs` asks for instead (see "Without the button" below) |
| `app_voice_tap` | where `app-voice-tap` is, for `app-phone`, when it's not in `~/.local/bin` or on the PATH |
| `ffmpeg` | the `ffmpeg` that plays the app's voice on the Mac, when it's not on the PATH or in Homebrew's `/opt/homebrew/bin` |
| `dev_path` | for working on the plugin (see Development) |

Better voices: System Settings → Accessibility → Spoken Content → System voice → Manage Voices;
download, for example, Zoe or Ava (Premium) and Kyoko (Enhanced), then put their names, exactly as
`say -v '?'` lists them, in the config. A voice that isn't installed falls back to the system voice.

Failures in the detached speaker are silent but logged to `~/.config/sakamoto-voice/speak.log`
(which starts over past 64 KB, keeping the previous one as `speak.log.1`). Each reading in the
Claude app's voice that passes through the speaker (`app-phone`, `app-both`, and any asked for
without the button) is also kept, for checking what the Claude app's voice actually said:
`~/.config/sakamoto-voice/recordings/latest.wav`, with the response's text in `latest.txt`; the
one before moves to `previous.*`, and older ones are never kept.

## The iPhone app

Apple doesn't allow third-party AirPlay receivers, so the phone runs its own small app, Sakamoto
Voice (`ios/`), and the Mac sends it each response over the local network. The app:

- **Listens** on the local network (TCP, advertised with Bonjour as `_sakamotovoice._tcp`, port
  47811 when it's free). Each connection carries one JSON message, which the app answers with a
  JSON ack, or a live audio stream: a JSON header line (its pairing code first and the text last, so
  the phone can check the code before reading a long reply), answered at once, then raw 16-bit PCM until
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
  network iOS counts as expensive, such as a Personal Hotspot, or one in Low Data Mode), and **Text Only**. With the text,
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
- **Passes messages on to an Apple Watch** (below), when the watch app is installed.

Before the first message it shows the pairing code, how to pair, and, small at the bottom, the
installed version ("Sakamoto Voice 1.1.2 (11)"); Settings → About shows it too.

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

2. Give the app a bundle ID of your own: in `ios/project.yml`, change `APP_BUNDLE_ID`
   (`com.pragmaphilia.SakamotoVoice`; the watch app's is the same plus `.watchkitapp`) and
   `bundleIdPrefix` to your own reverse-DNS name. Bundle IDs are unique across all teams, so the
   one in the repository can't be registered by yours.

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

The app's icon is its own character, Bleep: a boxy saturated-orange outline with two round eyes, an antenna,
two short legs, and its mouth open in song, one arm reaching toward three teal sound-wave arcs,
drawn as glowing vector lines on plain black. It is an Icon Composer document,
`ios/SakamotoVoice/AppIcon.icon`: an `icon.json` with the fill (black in every
appearance) and two transparent 1024×1024 layers, `Assets/creature.png` in front of
`Assets/waves.png`. On iOS 26 the system lights the layers with depth, in the default, dark, tinted,
and clear appearances; for iOS 18, Xcode flattens it into ordinary icon images. Both layers are
drawn by a script, which you can edit and run (offscreen; needs Pillow and NumPy):

    python3 ios/scripts/make-icon.py --preview icon.png    # rewrites AppIcon.icon; --preview is optional

`--preview` also writes the composed icon, flat, with rounded corners, for a look.

## The Apple Watch app

For when the phone isn't in your pocket: taking out the recycling, say, with the phone left in the
house on its stand. The iPhone app passes each message on to **Sakamoto Voice on the watch**, which
lists it and reads it aloud in the watch's own voices. The watch can't take anything from the Mac
itself (below), so the phone relays: over Bluetooth, or the home Wi-Fi when the watch is out of
Bluetooth range, as Apple's WatchConnectivity and notification forwarding choose.

**On the phone**, Settings → Apple Watch (shown when a watch is paired) has **Mirror to Apple
Watch** (on by default; the switch appears once the watch app is installed). With it on, the app
asks once for permission to send notifications, and then, for each message it receives (text, the
Mac's audio, or the Claude app's streamed voice, by its text):

- sends it to the watch app, live while the watch app is open and in reach, else queued (watchOS
  hands queued ones over in order, as soon as the app is in front, or when it wakes the app in the
  background);
- while the phone's app isn't on screen (so a phone in hand isn't nagged), posts a notification,
  "Miss Sakamoto" with the text (without voice markers, cut at 1,000 characters), and a **Speak**
  action. Only the latest stays: each new one replaces the one before, so they don't stack up. iOS shows a notification on the watch only while the phone is **locked or its screen is
  off** and the watch is on your wrist and unlocked; with the phone's app open on its stand and Keep
  Screen On, no notification is posted, so lock the phone (or let it lock) before you walk off.

**On the watch**, the app shows the last ten messages, newest first, each with Miss Sakamoto's 👩🏻‍🔬
avatar, and a big **Speak** button that reads the selected one (the newest, or the one you tap);
while it speaks it's a Stop button. **Auto-speak while open** (on by default) reads each new
message as it arrives while the app is in front, on screen or with the wrist down (a message that
waited in the queue for more than two minutes is only listed). A notification on the watch shows
the whole message, and its **Speak** opens the app and reads it. Japanese script and `〔ja〕` text
are read in a Japanese voice and the rest in an English one; text in neither follows the phone's
"Default Voice for Other Text", at the phone's rate. The watch has its own (fewer) voices: when it
has no Japanese voice, its default voice reads Japanese too.

The Claude app's own voice isn't streamed to the watch; the watch reads the text instead (below).

### What watchOS allows

The design follows from these, checked in the watchOS 27.0 SDK headers and Apple's documentation;
those marked *untested* haven't been tried on a watch yet.

- **No listener on the watch.** watchOS lets an app use low-level networking (Network framework,
  `NWListener`, Bonjour, stream and WebSocket tasks) only while it streams long-form audio, during
  a CallKit call, or for a DeviceDiscoveryUI connection from its tvOS app; otherwise a connection
  waits with `ENETDOWN`, and BSD sockets never work. The simulator always allows it, so it proves
  nothing (TN3135). Long-form audio on watchOS needs a Bluetooth audio route (Playing Background
  Audio). So the Mac can't reach the watch, and the phone relays.
- **Audio.** Background playback needs the long-form route-sharing policy and a Bluetooth route
  (headphones or a speaker), activated with `activate(options:completionHandler:)`, which shows a
  route picker if needed (`AVAudioSession` headers; Playing Background Audio); it never uses the
  watch's own speaker. In front, Apple's guidelines say an app can play short clips; the watch app
  uses an ordinary playback session (spoken audio, the default policy) and `AVSpeechSynthesizer`,
  which should play on the watch's speaker, or on Bluetooth audio when that's connected. Apple
  doesn't document the speaker case, and developers have reported silence without headphones on
  some watches (watchOS 6), so this is *untested* until it's tried on the watch.
- **WatchConnectivity.** `sendMessage` works only while the counterpart is reachable, which for the
  phone means the watch app is running in front (or in the background at high priority, such as a
  workout), and from the phone it never wakes the watch app (it does wake the phone's app from the
  watch). `transferUserInfo` is queued, delivered in order, and continues after the sender exits;
  the frontmost watch app gets it at once, otherwise watchOS delivers it when it wakes the app, on
  a limited background budget. Apple gives no latency figures; Apple calls WatchConnectivity an
  opportunistic channel. The simulator doesn't support `transferUserInfo` (WCSession docs).
- **Notifications.** A notification goes to the phone if the phone is unlocked with its screen on;
  otherwise to the watch if it's on the wrist and unlocked; otherwise to the phone (Taking
  Advantage of Notification Forwarding). A watch app can give a notification category its own
  long-look interface (`WKNotificationScene`, watchOS 7) and shows the category's actions; an
  action with the foreground option opens the watch app, whose notification delegate gets the
  response. While the watch app is on screen or frontmost, its delegate gets the notification
  instead of an alert (`userNotificationCenter(_:willPresent:)`).
- **Staying in front.** After the wrist goes down, the app stays frontmost (it can still receive
  messages and notifications) for two minutes by default, then goes to the background. Only the
  wearer can change that, in Settings → General → Wake Screen → Return to Clock, for all apps or
  one (Taking Advantage of Frontmost App State); since watchOS 7 an app can't extend it itself.
  Whether speech plays while frontmost with the wrist down is *untested*. Extended runtime sessions
  come in four kinds, each for its own use (self care, frontmost for 10 minutes; mindfulness,
  frontmost for an hour; physical therapy, in the background for an hour; smart alarm, scheduled,
  30 minutes), and Apple says to pick one by the app's intended use, not by what it provides
  (Using Extended Runtime Sessions). None fits reading messages, so the app uses none, and no
  workout session either.
- **Why not stream Claude's voice to the watch.** The watch can't take the Mac's stream (no
  listener), and the phone could relay it only over WatchConnectivity's live messages (about 48
  KB/s of PCM), which work only while the watch app is open and in reach, on a channel Apple
  describes as opportunistic, to a speaker whose use isn't documented. That's not worth building
  until the text-and-voices version is proven on a watch.

Sources: [TN3135: Low-level networking on watchOS](https://developer.apple.com/documentation/technotes/tn3135-low-level-networking-on-watchos);
[Playing Background Audio](https://developer.apple.com/documentation/watchkit/playing-background-audio);
[AVAudioSession.RouteSharingPolicy.longFormAudio](https://developer.apple.com/documentation/avfaudio/avaudiosession/routesharingpolicy-swift.enum/longformaudio);
[Playing audio (Human Interface Guidelines)](https://developer.apple.com/design/human-interface-guidelines/playing-audio);
[WCSession](https://developer.apple.com/documentation/watchconnectivity/wcsession),
[isReachable](https://developer.apple.com/documentation/watchconnectivity/wcsession/isreachable),
[sendMessage(_:replyHandler:errorHandler:)](https://developer.apple.com/documentation/watchconnectivity/wcsession/sendmessage(_:replyhandler:errorhandler:)),
[transferUserInfo(_:)](https://developer.apple.com/documentation/watchconnectivity/wcsession/transferuserinfo(_:));
[Taking advantage of notification forwarding](https://developer.apple.com/documentation/watchos-apps/taking-advantage-of-notification-forwarding);
[Enabling and receiving notifications](https://developer.apple.com/documentation/watchos-apps/enabling-and-receiving-notifications);
[WKNotificationScene](https://developer.apple.com/documentation/swiftui/wknotificationscene);
[Taking advantage of frontmost app state](https://developer.apple.com/documentation/watchkit/taking-advantage-of-frontmost-app-state);
[Using extended runtime sessions](https://developer.apple.com/documentation/watchkit/using-extended-runtime-sessions);
the reports of silence on the watch's speaker:
[Apple Developer Forums 653732](https://developer.apple.com/forums/thread/653732),
[737250](https://developer.apple.com/forums/thread/737250).

### Install it on the watch

The watch app is built into the iPhone app (in its `Watch` folder), so `scripts/build.sh install`
installs both on the phone. Then:

1. Pair the watch with Xcode by hand and turn on its Developer Mode, as described in
   [Here's how to deal with 🍎💩](#heres-how-to-deal-with-) above (Xcode 27 no longer does it
   through the iPhone).
2. Install the watch app: in the Watch app on the iPhone, under Available Apps, or directly with
   `devicectl`, as described there (the direct way works when the phone's route won't).
3. Open Sakamoto Voice on the phone: Settings → Apple Watch → Mirror to Apple Watch is on; allow
   notifications when asked.
4. Optionally, on the watch, Settings → General → Wake Screen → Return to Clock → Sakamoto Voice:
   a longer time keeps the app in front, and Auto-speak working, after the wrist goes down.

Before walking off, lock the phone, so its notifications go to the watch.

## Experimental: the Claude app's own voice

> **Read this first.** These modes (and `output phone`, while the debugger is on: below) work
> through the Claude desktop app's **Main Process Debugger**, a developer feature. While it is on, any program running on your Mac can run code
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
opening text (letters and digits only, so formatting doesn't matter; code blocks left out on both
sides, and a few other letters, such as a code block's label, allowed among the key's), waits up to
8 s for the page to draw its button, and 6 s more when no message matched (a tool-heavy turn's page
may still be drawing). It looks every 50 ms, with the pauses taken in the app's main process: the
session page is often "hidden" to Chromium (another window in front, or the app's newer layout), and
a hidden page throttles its own timers to a second or worse, which once made the lookup hang and
time out on almost every reply. A hidden page (a locked screen, for one) also stops drawing new
replies, so the lookup first turns off the page's background throttling, which keeps it visible
until the app restarts. One more case, measured on 2026-10-18 after the app's layout update: while
background tasks (agents, monitors) run and the app's Stop button stays shown, it draws a finished
reply at once but holds back the message's toolbar, and with it Read aloud, until the next prompt
arrives, seconds to minutes later (11 of 11 times within a second of the next prompt). The lookup
sees the reply (no button yet), gives up after 2.5 s instead of 14 s, and says "reply drawn without
Read aloud" in `speak.log`; the phone's or the Mac's own voices read it. (Not yet measured: whether
a session with no background work gets the button with the reply under the new layout; before the
update it did.) It marks each button it presses, so an earlier response is never read by
mistake. A button reads its whole block, and a reply that follows a notice rather than a new
message can share a block with the reply before it; when the response starts well into its block,
the button isn't pressed, and the Mac's or the phone's voices read just the new response. That
check also covers a response that comes without a new prompt from you (after a notice, such as a
background task finishing): it gets the app's voice when it has a block of its own. Each
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

### Without the button: the app's voice, asked for directly

Since the app's update of 2026-10-18 the Read aloud button often isn't there when a reply is done
(above), so the speaker now asks for the same voice directly, and presses the button only when that
fails. `plugin/scripts/app-voice.mjs`, through the same debugger, runs a little code in the claude.ai
session page that opens **Read aloud's own text-to-speech WebSocket** (`/api/ws/text_to_speech/text_stream`
on claude.ai), with the voice, speed, and language Read aloud uses (the account's Voice settings:
`ja-akarui` in `ja` at 1.2, say), sends it the reply's speakable text (as the speaker prepared it, `max_chars` and all), and passes the
audio out: the service sends 16-bit mono PCM at 16 kHz, which the script resamples to the stream's
24 kHz and writes to its standard output, paced as it plays (a second ahead at most), just as
`app-voice-tap --stdout` writes its tap. The speaker then sends it where the tap's audio would go: to
the phones over the same stream, to Sakamoto Eyes' hub as a copy, and, on the Mac, to `ffmpeg`
(`-f audiotoolbox`, the current output; Homebrew's `ffmpeg` is assumed, a command-line tool with no
window). The first sound comes about 1.2 s after the reply, measured on 2026-10-18; no tap, no click,
and no System Audio Recording permission is needed for it.

How it gets the voice: the page's WebSocket carries the request, so the session's cookies stay
with the browser: the script never reads, copies, or logs them, and nothing about them leaves the
page. It finds the helpers the app's read-aloud engine itself uses (its URL builder, the voice and
speed store, the client platform) through the engine's module, by name, and falls back to plain
defaults (`buttery`, the speed saved in the page, `desktop_app`) when one isn't found. The voice,
speed, and language are the ones the Read aloud button passes, read the same way, from the
account's settings the page holds (its account context, found in the page's React tree):
`voice_preference` (the style chosen in Settings > General > Voice: 明るい in Japanese is
`ja-akarui`), else the store's voice; `voice_speed` (Fast is 1.2); `voice_language_code` (`ja`; none
when unset). So it always matches the button, and follows any change in Settings at the next
reading. (The page's voice store alone isn't enough: it keeps only the five English voices, so a
Japanese style left it at `buttery`, a man's voice, and no language was sent.) `app_voice_voice`
and `app_voice_language` in the config, when set, override the voice and the language. Each reading
leaves nothing behind in the page: the socket closes when the reading is done, when the speaker is
stopped (a new prompt, a new response, `hush`; the script closes it on its way out), or, should the
script die without closing it, within 8 s, when nobody has drained it; `node app-voice.mjs --stop`
closes any left open.

**What this relies on:** a private, undocumented claude.ai endpoint and the app's current code,
neither of them meant for this. Any update of the app or the site may change or remove them, and
then this stops working (the speaker falls back, below, and `speak.log` says why). It is the same
service Read aloud uses for the same text, but it is used here without the button; judge that for
yourself, as with the debugger. Turn it off with `"app_voice": false` in the config: the button
then works as before.

Where it applies, while the debugger is on:

- `output app`: on the Mac, through `ffmpeg`; failing that (no `ffmpeg`, no sound within 8 s), the
  button, as before.
- `output app-phone`: streamed to the phones; failing that, the tap and the button, as before.
- `output app-both`: streamed to the phones and played on the Mac; failing that, as before.
- `output phone`: her voice streamed to the phone instead of the phone's own voices from the
  text, unless the phone wants the text (its Claude's Voice setting); failing that, or with the
  debugger off, the phone gets the response as `output phone` always sent it (in `phone_mode`).

Try it by hand (the debugger on; it writes a WAV and touches nothing else):

    node plugin/scripts/app-voice.mjs --wav /tmp/voice.wav --text "Testing her voice."
    node plugin/scripts/app-voice.mjs --wav /tmp/voice.wav --voice ja-akarui --language ja --text "テストです。"

Its last line names the voice, language, and speed it asked for (`ja-akarui (ja) at 1.20`).

### `output app`: on the Mac

    sakamoto output app          # the app's voice when its debugger is on, else the Mac's

With the app's voice asked for directly (above), the speaker plays it to its end, so `speaker.pid`
names it meanwhile, as for the Mac's own voices, and `stop` silences it. When the button is pressed
instead, the speaker exits, so `speaker.pid` is gone while the app still reads.
For Sakamoto Eyes, `~/.config/sakamoto-voice/app-reading` then says the app is reading:
`{"started": …, "ends": …, "text": …}` (Unix times; the end estimated from the text at about 165
words a minute, or 6.5 Japanese characters a second, plus 1.5 s). The next response, `stop`, and
`hush` remove it; they can't stop the app's own reading, which Sakamoto Eyes' relay stops through
the same debugger.

### `output app-phone`: streamed to the phone

For when you're away from the Mac: the same voice, streamed live to the phone, with the Mac's
speakers silent. The speaker first asks for the voice directly (above); when that fails, it taps
the button's reading. With `output app-phone`, the speaker (still detached; the hook never waits):

1. connects to the phone (finding it again if it moved) and sends the stream's header, carrying
   the response's text for its screen; the phone accepts it at once (or refuses a wrong code);
2. starts `app-voice.mjs` (above), and once its first audio has come, skips to step 4; else
   starts `app-voice-tap --stdout` (`mac/AppVoiceTap`), which taps the Claude app's audio with a
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
is older than 0.3.0 (it doesn't answer a stream), or when no sound comes from the app within 20 s
(enough for both looks for the Read aloud button).
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
straight to it; the phone app only listens on the local network and never connects out, except
that it passes messages to its own watch app, through Apple's WatchConnectivity and local
notifications, between the paired phone and watch (the watch keeps the last ten). The app
modes talk only to the Claude app on `127.0.0.1`; when the app's voice is asked for directly
(`app_voice`), the Claude app's own claude.ai page sends the response's text to claude.ai's
text-to-speech service, as its Read aloud button would. Files are kept in
`~/.config/sakamoto-voice/`: the settings, and `speak.log`, which records what happened (errors,
the phone's address, and, in the app modes, the first few letters of each response it matched).

One thing to know: messages to the phone travel over your local network **unencrypted**, guarded
only by the pairing code, so someone else on the same network could read what's being spoken. Use
it on a network you trust.

## Development

The tests, all headless (nothing is launched, no audio is captured or played, and the Claude app's
debugger is never used: the app's voice is mocked, and its page code runs against stand-ins in node):

    python3 -m unittest discover -s plugin/tests        # the plugin
    swift test --package-path ios/SakamotoVoiceKit       # the phone app's core, on the Mac
    mac/build.sh test                                    # app-voice-tap's core

    cd ios
    scripts/build.sh test       # SakamotoVoiceKit's tests on an iOS simulator
    scripts/build.sh sim        # a simulator build, the watch app inside it (no team needed)
    scripts/build.sh watch      # the watch app alone: for its simulator, and unsigned for a watch
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
one side only: the plugin is 1.0 (the phone chooses Claude's voice or the text, and the Mac
follows), and the app 1.1, build 9 (the Apple Watch app, the phone's side alone); the watch app
always has the iPhone app's version and build. The apps' pure parts (protocol, pairing, language
runs and voice markers, schedule, keep-alive sound, the Claude's Voice choice, streams' framing
and jitter buffer, and the messages mirrored to the watch) and the phone's receiver are in the
`SakamotoVoiceKit` package (for iOS, watchOS, and macOS), which `app-voice-tap` uses too, and which
also has `voice-listen`, a stand-in phone on the
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

MIT; see [LICENSE](LICENSE). A Pragmaphilia Labs project. It bundles no third-party code; what it
relies on (Python's standard library, Node's built-ins, Apple's frameworks and voices) is listed in
[ACKNOWLEDGMENTS.md](ACKNOWLEDGMENTS.md).

Sakamoto Voice is an independent project. It is not affiliated with, endorsed by, or supported by
Anthropic. "Claude" and "Claude Code" are Anthropic's names for its products, used here only to say
what this works with.
