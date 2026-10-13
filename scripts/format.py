"""Format Python source; pass --check for a read-only check."""

import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / ".runtime/formatter"))
try:
    import black
    import isort
except ImportError:
    raise SystemExit(
        "Install first: python -m pip install --target .runtime/formatter -r requirements-dev.txt"
    )


def main():
    import tomllib

    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["tool"]
    mode = black.Mode(
        line_length=config["black"]["line-length"], target_versions={black.TargetVersion.PY311}
    )
    check = "--check" in sys.argv
    changed = 0
    paths = sorted(
        p
        for folder in ("services", "scripts", "tests", "examples")
        for p in (root / folder).rglob("*.py")
    )
    for path in paths:
        original = path.read_text(encoding="utf-8")
        sorted_source = isort.code(original, **config["isort"])
        try:
            formatted = black.format_file_contents(sorted_source, fast=False, mode=mode)
        except black.NothingChanged:
            formatted = sorted_source
        if original == formatted:
            continue
        changed += 1
        print(("Would format: " if check else "Formatted: ") + str(path.relative_to(root)))
        if not check:
            path.write_text(formatted, encoding="utf-8")
    print(f"Checked {len(paths)} Python files; {changed} changed.")
    return 1 if check and changed else 0


if __name__ == "__main__":
    raise SystemExit(main())
