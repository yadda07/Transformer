# -*- coding: utf-8 -*-
"""
Design lint gate for Transformer plugin (UIUX-010).

Run: python -m tests.audit_design_lint
Or:  python tests/audit_design_lint.py

Returns exit code 0 if clean, 1 if violations found.
"""

import re
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

FORBIDDEN_PATTERNS = [
    (re.compile(r'color:\s*#[0-9a-fA-F]'), "Hardcoded hex color"),
    (re.compile(r'background-color:\s*#[0-9a-fA-F]'), "Hardcoded hex background-color"),
    (re.compile(r'background:\s*#[0-9a-fA-F]'), "Hardcoded hex background"),
    (re.compile(r'rgba?\s*\('), "Hardcoded rgb/rgba color"),
    (re.compile(r'setTitleBarWidget\s*\('), "Custom dock title bar"),
    (re.compile(r'from\s+PyQt[56]\b'), "Direct PyQt5/PyQt6 import"),
    (re.compile(r'import\s+PyQt[56]\b'), "Direct PyQt5/PyQt6 import"),
]

SCAN_EXTENSIONS = {'.py', '.ui', '.qss', '.css'}

WHITELIST_FILES = {
    'audit_design_lint.py',
}

WHITELIST_PATTERNS_IN_CONTEXT = [
    re.compile(r'palette\s*\('),
]


def is_whitelisted_line(line: str) -> bool:
    for pat in WHITELIST_PATTERNS_IN_CONTEXT:
        if pat.search(line):
            return True
    return False


def scan_file(filepath: Path) -> list:
    violations = []
    try:
        text = filepath.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return violations

    for line_num, line in enumerate(text.splitlines(), start=1):
        if is_whitelisted_line(line):
            continue
        for pattern, description in FORBIDDEN_PATTERNS:
            if pattern.search(line):
                rel = filepath.relative_to(PLUGIN_ROOT)
                violations.append((str(rel), line_num, description, line.strip()))
    return violations


def main():
    all_violations = []

    for ext in SCAN_EXTENSIONS:
        for filepath in PLUGIN_ROOT.rglob(f'*{ext}'):
            if filepath.name in WHITELIST_FILES:
                continue
            if '__pycache__' in str(filepath):
                continue
            all_violations.extend(scan_file(filepath))

    if not all_violations:
        print(f"DESIGN LINT: PASS (0 violations)")
        return 0

    print(f"DESIGN LINT: FAIL ({len(all_violations)} violations)\n")
    for rel_path, line_num, desc, line_text in all_violations:
        print(f"  {rel_path}:{line_num}  [{desc}]")
        print(f"    {line_text[:120]}")
        print()

    return 1


if __name__ == '__main__':
    sys.exit(main())
