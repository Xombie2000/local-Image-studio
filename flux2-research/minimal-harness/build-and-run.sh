#!/bin/bash
# Build and run the minimal FLUX.2 Klein 4B generation harness.
# This script compiles and executes a minimal Swift executable that:
# 1. Loads the FLUX.2-klein-4B bfloat16 model from local cache
# 2. Generates one 512x512 image with 4 steps and seed 42
# 3. Saves the output as PNG

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

# Ensure Xcode toolchain is configured for Metal
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer

# Offline flags — no network transfer
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

# Model snapshot (4B Klein, bfloat16)
MODEL_SNAPSHOT="$HOME/.cache/huggingface/hub/models--black-forest-labs--FLUX.2-klein-4B/snapshots/e7b7dc27f91deacad38e78976d1f2b499d76a294"
OUTPUT_PATH="$PROJECT_ROOT/artifacts/generated_4b_klein.png"

echo "=== Build and Run: FLUX.2 Klein 4B Minimal Harness ==="
echo "Model snapshot: $MODEL_SNAPSHOT"
echo "Output path: $OUTPUT_PATH"

# Build the harness
cd "$SCRIPT_DIR"
echo ""
echo "--- Building ---"
swift build 2>&1

# Find the executable
EXECUTABLE=".build/debug/MinimalHarnes"
if [ ! -f "$EXECUTABLE" ]; then
  echo "ERROR: Executable not found at $EXECUTABLE"
  exit 1
fi

echo ""
echo "--- Executable: $EXECUTABLE ---"
file "$EXECUTABLE"

# Run the harness
echo ""
echo "--- Running ---"
"$EXECUTABLE" 2>&1

# Verify output
if [ -f "$OUTPUT_PATH" ]; then
  echo ""
  echo "--- Output verified ---"
  ls -la "$OUTPUT_PATH"
  file "$OUTPUT_PATH"
else
  echo "ERROR: Output file not found at $OUTPUT_PATH"
  exit 1
fi

echo ""
echo "=== Complete ==="
