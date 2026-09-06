#!/usr/bin/env python3
"""Regression test: validates that all INSERT INTO generations statements have matching column, placeholder, and value counts.

This test parses backend_v2.py to extract every INSERT INTO generations statement
and verifies:
  - The number of column names equals the number of ? placeholders + NULL literals.

If any INSERT has a mismatch, this test fails — catching the bug that previously
caused "column count != value count" runtime errors.

Usage:
    python v2/tests/test_insert_validation.py [--source PATH]

Defaults to /Users/ricknichols/LocalImageStudio/v2/backend_v2.py.
"""

import argparse
import re
import sys


def count_columns(columns_text: str) -> int:
    """Count top-level column identifiers in a parenthesized list."""
    depth = 0
    count = 0
    current_token: str | None = None

    for ch in columns_text:
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        elif depth == 0 and ch in (' ', '\t', '\n', '\r'):
            if current_token is not None:
                token = current_token.strip()
                if token and not token.startswith('//'):
                    count += 1
                current_token = None
        else:
            if current_token is None:
                current_token = ''
            current_token += ch

    # Don't forget the last token
    if current_token is not None:
        token = current_token.strip()
        if token and not token.startswith('//'):
            count += 1

    return count


def extract_insert_blocks(source: str) -> list[tuple[str, int]]:
    """Extract all INSERT INTO generations blocks with their line numbers."""
    results = []
    lines = source.split('\n')

    i = 0
    while i < len(lines):
        line = lines[i]
        if re.search(r'INSERT INTO generations\s*\(', line, re.IGNORECASE):
            # Found start of INSERT — collect until we find the closing ),
            block_lines = []
            paren_depth = 0
            started_columns = False

            while i < len(lines):
                block_lines.append(lines[i])
                for ch in lines[i]:
                    if ch == '(':
                        paren_depth += 1
                        started_columns = True
                    elif ch == ')':
                        paren_depth -= 1

                if started_columns and paren_depth <= 0:
                    break
                i += 1

            block_text = '\n'.join(block_lines)
            results.append((block_text, i - len(block_lines) + 1))

        i += 1

    return results


def validate_insert(block: str, line_num: int) -> list[str]:
    """Validate a single INSERT block. Returns list of errors (empty = pass)."""
    errors = []

    # Extract columns: text between first '(' after 'INSERT INTO generations'
    col_match = re.search(
        r'INSERT INTO\s+\w+\s*\((.*?)\)\s*VALUES',
        block, re.DOTALL | re.IGNORECASE
    )
    if not col_match:
        errors.append(f"Line {line_num}: Could not parse column list")
        return errors

    columns_text = col_match.group(1)
    column_count = count_columns(columns_text)

    # Extract values: text between 'VALUES (' and the closing ')' of the SQL string
    val_match = re.search(
        r'VALUES\s*\((.*?)\)',
        block, re.DOTALL | re.IGNORECASE
    )
    if not val_match:
        errors.append(f"Line {line_num}: Could not parse VALUES clause")
        return errors

    values_text = val_match.group(1)
    placeholder_count = values_text.count('?')
    null_literal_count = len(re.findall(r'\bNULL\b', values_text))

    total_slots = placeholder_count + null_literal_count

    if column_count != total_slots:
        errors.append(
            f"Line {line_num}: Column count ({column_count}) != "
            f"placeholder+NULL count ({total_slots}) "
            f"(?={placeholder_count}, NULL={null_literal_count})"
        )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate INSERT INTO generations column/placeholder/value counts"
    )
    parser.add_argument(
        "--source",
        default="/Users/ricknichols/LocalImageStudio/v2/backend_v2.py",
        help="Path to backend_v2.py to validate"
    )
    args = parser.parse_args()

    try:
        with open(args.source, 'r') as f:
            source = f.read()
    except FileNotFoundError:
        print(f"ERROR: Source file not found: {args.source}")
        return 1

    blocks = extract_insert_blocks(source)

    if not blocks:
        print("WARNING: No INSERT INTO generations statements found")
        return 0

    all_errors = []
    print(f"Found {len(blocks)} INSERT INTO generations statement(s)\n")

    for i, (block, line_num) in enumerate(blocks, 1):
        # Determine block type by scanning for keywords
        is_upscale = 'upscale_source_width' in block or 'SeedVR2' in block
        label = "Upscale" if is_upscale else f"Block {i}"

        print(f"--- {label} (source line ~{line_num}) ---")
        errors = validate_insert(block, line_num)

        if errors:
            for err in errors:
                print(f"  ✗ {err}")
            all_errors.extend(errors)
        else:
            # Print summary
            col_match = re.search(
                r'INSERT INTO\s+\w+\s*\((.*?)\)\s*VALUES',
                block, re.DOTALL | re.IGNORECASE
            )
            val_match = re.search(
                r'VALUES\s*\((.*?)\)',
                block, re.DOTALL | re.IGNORECASE
            )
            if col_match and val_match:
                cols = count_columns(col_match.group(1))
                vals_text = val_match.group(1)
                qmarks = vals_text.count('?')
                nulls = len(re.findall(r'\bNULL\b', vals_text))
                print(f"  ✓ {cols} columns = {qmarks} ? + {nulls} NULL")

        print()

    if all_errors:
        print(f"FAILED: {len(all_errors)} validation error(s)")
        return 1

    print("ALL INSERT STATEMENTS VALID")
    return 0


if __name__ == "__main__":
    sys.exit(main())
