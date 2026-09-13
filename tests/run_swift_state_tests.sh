#!/bin/zsh
set -euo pipefail
SOURCE_ROOT="${0:A:h:h}"
TEST_BUILD_DIR="$(mktemp -d /private/tmp/lis-state-tests.XXXXXX)"
trap 'rm -rf "$TEST_BUILD_DIR"' EXIT
ARCH="$(uname -m)"
SWIFTC="${LIS_SWIFTC:-/usr/bin/swiftc}"
"$SWIFTC" -parse-as-library -swift-version 5 -target "$ARCH-apple-macos13.0" \
  -module-cache-path "$TEST_BUILD_DIR/cache" \
  -framework AppKit -framework SwiftUI -framework UniformTypeIdentifiers \
  "$SOURCE_ROOT/macos/Localization.swift" \
  "$SOURCE_ROOT/macos/Models.swift" \
  "$SOURCE_ROOT/macos/BackendController.swift" \
  "$SOURCE_ROOT/macos/StudioStore.swift" \
  "$SOURCE_ROOT/macos/ContentView.swift" \
  "$SOURCE_ROOT/tests/StudioStateTests.swift" \
  -o "$TEST_BUILD_DIR/StudioStateTests"
"$TEST_BUILD_DIR/StudioStateTests"
