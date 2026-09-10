"""Keep the English/Japanese UI catalogs complete and in sync."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SWIFT_FILES = tuple((ROOT / "macos").glob("*.swift"))
CATALOG_ROOT = ROOT / "macos" / "Resources"
ENTRY = re.compile(r'^"((?:[^"\\]|\\.)*)"\s*=\s*"((?:[^"\\]|\\.)*)"\s*;', re.MULTILINE)
STATIC_UI = re.compile(
    r'(?:Text|Button|Label|Picker|Section|DisclosureGroup)\(\s*"([^"\\]*(?:\\.[^"\\]*)*)"'
    r'|\.(?:help|accessibilityLabel|alert)\(\s*"([^"\\]*(?:\\.[^"\\]*)*)"'
)
RUNTIME_UI = re.compile(r'L10n\.(?:text|format)\(\s*"([^"\\]*(?:\\.[^"\\]*)*)"')


def catalog(language: str) -> dict[str, str]:
    text = (CATALOG_ROOT / f"{language}.lproj" / "Localizable.strings").read_text(encoding="utf-8")
    matches = ENTRY.findall(text)
    keys = [key for key, _ in matches]
    if len(keys) != len(set(keys)):
        duplicates = sorted({key for key in keys if keys.count(key) > 1})
        raise AssertionError(f"Duplicate {language} localization keys: {duplicates}")
    return dict(matches)


class LocalizationTests(unittest.TestCase):
    def test_catalogs_have_identical_nonempty_keys(self):
        english = catalog("en")
        japanese = catalog("ja")
        self.assertEqual(english.keys(), japanese.keys())
        self.assertTrue(all(english.values()))
        self.assertTrue(all(japanese.values()))
        self.assertGreater(sum(japanese[key] != english[key] for key in english), 100)

    def test_user_facing_swift_literals_are_cataloged(self):
        source = "\n".join(path.read_text(encoding="utf-8") for path in SWIFT_FILES)
        required = set(RUNTIME_UI.findall(source))
        for match in STATIC_UI.finditer(source):
            key = match.group(1) or match.group(2)
            if "\\(" not in key and not re.fullmatch(r"[a-z0-9._:/-]+", key):
                required.add(key)
        missing = sorted(required - catalog("ja").keys())
        self.assertEqual(missing, [], f"Missing Japanese UI strings: {missing}")


if __name__ == "__main__":
    unittest.main()
