"""Extract a single application's version entry for GitHub release notes."""
import argparse
from pathlib import Path
import re


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--changelog", type=Path, default=Path("CHANGELOG.md"))
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    text = arguments.changelog.read_text(encoding="utf-8")
    heading = re.search(r"^## \[" + re.escape(arguments.version) + r"\][^\n]*$", text, re.MULTILINE)
    if heading is None:
        parser.error(f"Missing changelog entry for {arguments.version}")
    remainder = text[heading.end():]
    next_heading = re.search(r"^## ", remainder, re.MULTILINE)
    notes = remainder[:next_heading.start()] if next_heading else remainder
    if not notes.strip():
        parser.error(f"Empty changelog entry for {arguments.version}")
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(f"# FDH {arguments.version}\n\n{notes.strip()}\n", encoding="utf-8")


if __name__ == "__main__":
    main()
