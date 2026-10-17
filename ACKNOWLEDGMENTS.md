# Third-party notices

Sakamoto Voice (the Claude Code plugin, `app-voice-tap`, and the Sakamoto Voice iPhone and Watch
apps) is MIT-licensed, © 2026 John Mifsud, Pragmaphilia Labs (see [LICENSE](LICENSE)). This file
lists the software and material made by others that it ships or relies on. Audited 2026-10-18.

## What ships

**Nothing from third parties is bundled.** There are no vendored libraries, no Swift packages
beyond this repository's own (`SakamotoVoiceKit` is local, and `app-voice-tap` depends only on
it), no npm packages, no Python packages, no fonts, no sounds, and no images other than the
iPhone app's icon layers (`ios/SakamotoVoice/AppIcon.icon/Assets/`, our own art).

| Component | What it is | License | Where it comes from |
|---|---|---|---|
| `plugin/scripts/speak.py` | Python 3 **standard library only** (`base64, json, os, pty, re, select, shutil, signal, socket, subprocess, sys, tempfile, threading, time, unicodedata, wave`) | n/a; runs on the Python 3 the user already has (PSF License) | the user's Mac |
| `plugin/scripts/app-read.mjs`, `app-read-match.mjs` | Node.js **built-ins only**; talks to the Claude desktop app over the Chrome DevTools protocol | n/a; runs on the user's own Node.js (MIT) | the user's Mac |
| macOS `say` and its voices | speech synthesis on the Mac | Apple's OS license | the user's Mac (not redistributed) |
| Apple frameworks (AVFoundation, Core Audio, Network, WatchConnectivity, SwiftUI, …) | the Swift code's system dependencies | Apple's SDK license | the SDK (not redistributed) |
| Claude Code and the Claude desktop app | what the plugin works with | Anthropic's terms | the user's own installation; "Claude" and "Claude Code" are Anthropic's names, used only to say what this works with (see README) |

## Reserved

If a third-party library is ever added (for example an audio library in `app-voice-tap`), add its
row above, keep its license text in a `licenses/` folder here, and keep its notice with every copy
shipped.
