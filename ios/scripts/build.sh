#!/bin/zsh
# Builds Sakamoto Voice headlessly. Products go to ios/build/ (git-ignored).
#
#     scripts/build.sh test              the unit tests on an iOS simulator (no app is launched)
#     scripts/build.sh sim               a simulator build
#     scripts/build.sh device            a signed build for any iPhone (checks signing)
#     scripts/build.sh install [phone]   build for the phone and install it (USB or Wi-Fi paired);
#                                        [phone] is its name or identifier, as
#                                        `xcrun devicectl list devices` shows; the only one if omitted
#     scripts/build.sh clean             removes ios/build/
#
# device and install sign with your Apple Development team, from ios/Config/Signing.local.xcconfig
# (DEVELOPMENT_TEAM = ABCDE12345) or the DEVELOPMENT_TEAM environment variable. It uses the Xcode
# that xcode-select picks, or $DEVELOPER_DIR; SIMULATOR names the simulator for test (iPhone 17).
set -euo pipefail

cd "${0:A:h}/.."
DERIVED=build/DerivedData
SIMULATOR=${SIMULATOR:-iPhone 17}
common=(-project SakamotoVoice.xcodeproj -scheme SakamotoVoice -derivedDataPath "$DERIVED" -jobs 6)

generate() { xcodegen generate --quiet }

# The signing team, for a build for a phone: $DEVELOPMENT_TEAM, else Config/Signing.local.xcconfig's.
team() {
  local team=${DEVELOPMENT_TEAM:-}
  if [[ -z $team && -f Config/Signing.local.xcconfig ]]; then
    team=$(sed -n 's/^[[:space:]]*DEVELOPMENT_TEAM[[:space:]]*=[[:space:]]*\([A-Za-z0-9]*\).*/\1/p' \
      Config/Signing.local.xcconfig | tail -1)
  fi
  if [[ -z $team ]]; then
    print -u2 "No signing team. Put your Apple Development team's ID in ios/Config/Signing.local.xcconfig:"
    print -u2 ""
    print -u2 "    DEVELOPMENT_TEAM = ABCDE12345"
    print -u2 ""
    print -u2 "(or set DEVELOPMENT_TEAM in the environment). Simulator builds and tests need no team."
    exit 1
  fi
  print -r -- "$team"
}

case "${1:-}" in
  test)
    generate
    xcodebuild "${common[@]}" -destination "platform=iOS Simulator,name=$SIMULATOR" test
    ;;
  sim)
    generate
    xcodebuild "${common[@]}" -destination 'generic/platform=iOS Simulator' build
    ;;
  device)
    team=$(team)
    generate
    xcodebuild "${common[@]}" -destination 'generic/platform=iOS' -allowProvisioningUpdates \
      DEVELOPMENT_TEAM="$team" build
    ;;
  install)
    team=$(team)
    generate
    # The phone's identifier (devicectl's JSON: result.devices[]), by name or identifier, or the
    # only paired iPhone.
    json=$(mktemp)
    xcrun devicectl list devices --json-output "$json" >/dev/null
    udid=$(python3 -c '
import json, sys
want = sys.argv[2]
devices = json.load(open(sys.argv[1]))["result"]["devices"]
phones = [d for d in devices if d.get("hardwareProperties", {}).get("platform") == "iOS"
          and d.get("connectionProperties", {}).get("pairingState") == "paired"]
if want:
    phones = [d for d in phones if want in (d["hardwareProperties"].get("udid"), d["identifier"],
                                            d.get("deviceProperties", {}).get("name"))]
if len(phones) != 1:
    names = ", ".join(d.get("deviceProperties", {}).get("name", "?") for d in phones) or "none"
    sys.exit("Found %d matching paired iPhones (%s); name one: scripts/build.sh install <name>"
             % (len(phones), names))
print(phones[0]["hardwareProperties"]["udid"])' "$json" "${2:-}")
    rm -f "$json"
    # Building for the phone itself lets automatic signing register it with the team.
    xcodebuild "${common[@]}" -configuration Release -destination "id=$udid" \
      -allowProvisioningUpdates -allowProvisioningDeviceRegistration DEVELOPMENT_TEAM="$team" build
    app="$DERIVED/Build/Products/Release-iphoneos/SakamotoVoice.app"
    xcrun devicectl device install app --device "$udid" "$app"
    echo "Installed. Open Sakamoto Voice on the phone and allow Local Network access."
    ;;
  clean)
    rm -rf build
    ;;
  *)
    sed -n '2,14p' "$0"
    exit 2
    ;;
esac
