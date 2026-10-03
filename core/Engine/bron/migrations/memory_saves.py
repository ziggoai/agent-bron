"""0.6.0: agents save and forget memory without asking first.

Agent.md files written before 0.6.0 say to show every change in System/ and wait for a yes. The memory
sentence goes right after that rule, only where the rule is still exactly as Bron wrote it; a file the
user reworded is left alone. Plain text replacement on the raw file, so frontmatter and line endings stay.
"""
from __future__ import annotations

import re

from ..agent_setup import MEMORY_EXCEPTION
from ..loader import Config
from ..setup import Change

SUMMARY = "Agents save what you tell them to remember without asking first."
# Bron's own Agent.md (0.5.0 template) and every agent created with the standard instructions before 0.6.0.
OLD_SENTENCES = (
    "The one exception: when the user tells you their name, role and company, save them straight away with "
    "`.bron/bin/bron settings set` and say so.",
    "Never change anything in `System/` without showing the user the change first and getting a yes.",
)


def add_exception(text: str) -> str:
    """The text with the memory sentence after the old rule, or unchanged when there's nothing to do."""
    if MEMORY_EXCEPTION in text:
        return text
    for old in OLD_SENTENCES:
        # Only where the sentence still ends its line: a line the user added to is theirs.
        text, found = re.subn(re.escape(old) + r"(?=\r?\n|\Z)", lambda m: f"{m.group(0)} {MEMORY_EXCEPTION}", text, count=1)
        if found:
            return text
    return text


def build(cfg: Config) -> Change:
    root = cfg.vault.root
    writes: dict[str, str] = {}
    names: list[str] = []
    folders = [cfg.vault.agents_dir, cfg.vault.system / "Archive" / "Agents"]
    for path in sorted(p for folder in folders if folder.is_dir() for p in folder.glob("*/Agent.md")):
        try:
            raw = path.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # a file Bron can't read is left as it is
        new = add_exception(raw)
        if new != raw:
            writes[path.relative_to(root).as_posix()] = new
            names.append(path.parent.name)
    if not writes:
        return Change(done="")  # nothing to say
    who = ", ".join(names)
    return Change(summary=[f"Let {who} save what you tell them to remember without asking first."], writes=writes,
                  done=f"{SUMMARY} (Updated: {who}.)")
