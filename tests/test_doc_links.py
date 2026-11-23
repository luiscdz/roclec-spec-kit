"""Relative Markdown links and heading anchors of the top-level documentation resolve."""
from __future__ import annotations

from pathlib import Path
import re
import unittest
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
DOCS = ("README.md", "docs/c1.md", "docs/c2.md", "docs/c3.md", "docs/flujo-roclec.md",
        "docs/strategy/plan-flujo-agentico-2026-11-17.md")
LINK = re.compile(r"(?<!\!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
FENCE = re.compile(r"^\s*(```|~~~)")


def lines_outside_fences(path):
    fenced = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if FENCE.match(line):
            fenced = not fenced
        elif not fenced:
            yield line


def slug(heading):
    text = heading.strip().lower()
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text).replace("`", "").replace("*", "")
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def anchors(path):
    seen, result = {}, set()
    for line in lines_outside_fences(path):
        match = re.match(r"#{1,6}\s+(.*?)\s*#*\s*$", line)
        if match:
            base = slug(match.group(1))
            count = seen.get(base, 0)
            seen[base] = count + 1
            result.add(base if count == 0 else f"{base}-{count}")
    return result


class DocLinkTest(unittest.TestCase):
    def test_relative_links_and_anchors_resolve(self):
        broken = []
        for doc in DOCS:
            source = ROOT / doc
            for line in lines_outside_fences(source):
                for target in LINK.findall(line):
                    if re.match(r"[a-z][a-z0-9+.-]*:", target):
                        continue  # External URL or mailto.
                    path, _, anchor = target.partition("#")
                    destination = (source.parent / unquote(path)).resolve() if path else source
                    if not destination.exists():
                        broken.append(f"{doc}: {target} (missing file)")
                    elif anchor and destination.suffix == ".md" and destination.is_file() \
                            and unquote(anchor).lower() not in anchors(destination):
                        broken.append(f"{doc}: {target} (no such heading)")
        self.assertEqual(broken, [])


if __name__ == "__main__":
    unittest.main()
