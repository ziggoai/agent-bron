"""Publishing skills. Each CLI reads skills from its own folder, so Bron copies them there."""
from __future__ import annotations

from . import frontmatter as fm
from .loader import Config


def skill_files(cfg: Config, dest: str) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for name, skill in sorted(cfg.skills.items()):
        for path in sorted(skill.folder.rglob("*")):
            rel = path.relative_to(skill.folder)
            if path.is_dir() or any(part.startswith(".") for part in rel.parts):
                continue
            data = path.read_bytes()
            if skill.rewrite and rel.as_posix() == "SKILL.md":
                doc = fm.parse(data.decode("utf-8"))
                doc.meta["name"] = skill.name
                doc.meta["description"] = skill.description
                data = fm.dump(doc).encode("utf-8")
            out[f"{dest}/{name}/{rel.as_posix()}"] = data
    return out
