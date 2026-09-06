#!/bin/zsh
set -euo pipefail

PROJECT_DIR="${0:A:h:h}"
V2_DIR="$PROJECT_DIR/v2"
BUILD_ROOT="$V2_DIR/build"
BUILD_APP="$BUILD_ROOT/Local Image Studio.app"
CONTENTS="$BUILD_APP/Contents"
DESTINATION="$HOME/Applications/Local Image Studio.app"
V1_FALLBACK="$HOME/Applications/Local Image Studio v1.app"

rm -rf "$BUILD_ROOT"
mkdir -p "$CONTENTS/MacOS" "$CONTENTS/Resources"

/usr/bin/swiftc -parse-as-library -swift-version 5 -target arm64-apple-macos13.0 \
  -framework AppKit -framework SwiftUI -framework UniformTypeIdentifiers \
  "$V2_DIR/macos/Models.swift" \
  "$V2_DIR/macos/BackendController.swift" \
  "$V2_DIR/macos/StudioStore.swift" \
  "$V2_DIR/macos/ContentView.swift" \
  "$V2_DIR/macos/LocalImageStudioApp.swift" \
  -o "$CONTENTS/MacOS/LocalImageStudio"

cp "$V2_DIR/macos/Info.plist" "$CONTENTS/Info.plist"
cp "$PROJECT_DIR/backend.py" "$CONTENTS/Resources/backend.py"
cp "$V2_DIR/backend_v2.py" "$CONTENTS/Resources/backend_v2.py"
cp "$V2_DIR/mflux_worker.py" "$CONTENTS/Resources/mflux_worker.py"

ICONSET="$BUILD_ROOT/AppIcon.iconset"
mkdir -p "$ICONSET"
ICON_RENDER_DIR="$BUILD_ROOT/IconRender"
mkdir -p "$ICON_RENDER_DIR"
if ! /usr/bin/qlmanage -t -s 1024 -o "$ICON_RENDER_DIR" "$PROJECT_DIR/assets/AppIcon.svg" >/dev/null 2>&1; then
  print -u2 "Could not render the Local Image Studio app icon."
  exit 1
fi
ICON_SOURCE="$ICON_RENDER_DIR/AppIcon.svg.png"
if [[ ! -s "$ICON_SOURCE" ]]; then
  print -u2 "The Local Image Studio app icon render is missing."
  exit 1
fi
for SPEC in "16 icon_16x16" "32 icon_16x16@2x" "32 icon_32x32" "64 icon_32x32@2x" "128 icon_128x128" "256 icon_128x128@2x" "256 icon_256x256" "512 icon_256x256@2x" "512 icon_512x512" "1024 icon_512x512@2x"; do
  SIZE="${SPEC%% *}"; NAME="${SPEC#* }"
  /usr/bin/sips -z "$SIZE" "$SIZE" "$ICON_SOURCE" --out "$ICONSET/$NAME.png" >/dev/null
done
/usr/bin/iconutil -c icns "$ICONSET" -o "$CONTENTS/Resources/AppIcon.icns"
if [[ ! -s "$CONTENTS/Resources/AppIcon.icns" ]]; then
  print -u2 "The Local Image Studio ICNS resource is missing."
  exit 1
fi

/usr/bin/codesign --force --sign - "$BUILD_APP" >/dev/null
mkdir -p "$HOME/Applications"

if [[ -d "$DESTINATION" && ! -d "$V1_FALLBACK" ]]; then
  /usr/bin/ditto "$DESTINATION" "$V1_FALLBACK"
  print "Preserved v1 fallback: $V1_FALLBACK"
fi

if [[ -e "$DESTINATION" ]]; then
  mv "$DESTINATION" "$BUILD_ROOT/Previous.app"
fi
mv "$BUILD_APP" "$DESTINATION"
rm -rf "$BUILD_ROOT"

print "Installed SwiftUI v2: $DESTINATION"
