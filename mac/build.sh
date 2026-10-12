#!/bin/zsh
# Builds app-voice-tap (mac/AppVoiceTap), the capture helper for `sakamoto output app-phone`:
# a release build into bin/app-voice-tap (git-ignored), signed (with an Apple Development
# certificate when the keychain has one, so macOS's permission survives rebuilds; else ad hoc),
# and linked into ~/.local/bin, where the Stop hook looks for it.
#
#     mac/build.sh             build, sign, and link (run it once, and after changing the tool)
#     mac/build.sh --no-link   build and sign only
#     mac/build.sh test        the tool's unit tests (no audio is captured)
#     mac/build.sh clean       remove the build products
set -euo pipefail

here=${0:A:h}
repo=${here:h}
package=$here/AppVoiceTap
out=$repo/bin/app-voice-tap
link=$HOME/.local/bin/app-voice-tap

case "${1:-}" in
  ""|--no-link) ;;
  test)
    swift test --package-path "$package" -j 6
    exit
    ;;
  clean)
    rm -rf "$package/.build" "$out"
    exit 0
    ;;
  *)
    sed -n '2,11p' "$0"
    exit 2
    ;;
esac

swift build --package-path "$package" -c release -j 6 --product app-voice-tap
cp "$(swift build --package-path "$package" -c release --show-bin-path)/app-voice-tap" "$out"

identity=$(security find-identity -v -p codesigning 2>/dev/null | sed -n 's/.*"\(Apple Development:[^"]*\)".*/\1/p' | head -1)
codesign --force --sign "${identity:--}" --identifier com.pragmaphilia.AppVoiceTap "$out"
echo "Built $out, signed ${identity:-ad hoc}."
if [[ -z $identity ]]; then
  echo "(Ad hoc: macOS forgets the audio permission after each rebuild; allow it again then.)"
fi

if [[ ${1:-} != --no-link ]]; then
  if [[ -L $link || ! -e $link ]]; then
    mkdir -p "${link:h}"
    ln -sf "$out" "$link"
    echo "Linked $link."
  else
    echo "Not linked: $link exists and isn't a link; the hook finds bin/app-voice-tap through the config's app_voice_tap instead."
  fi
fi
echo "Next, once, at the Mac: app-voice-tap --check   (macOS asks to allow System Audio Recording)"
