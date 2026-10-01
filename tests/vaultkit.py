"""Small helpers for building test vaults."""
from pathlib import Path

from bron import frontmatter as fm
from bron.vault import Vault


def write_md(path: Path, meta: dict, body: str = "") -> Path:
    fm.write(path, fm.Document(meta, body))
    return path


def set_meta(path: Path, **changes) -> None:
    doc = fm.read(path)
    doc.meta.update(changes)
    fm.write(path, doc)


def add_agent(vault: Vault, name: str, **meta) -> Path:
    data = {
        "name": name,
        "role": meta.pop("role", f"{name} role"),
        "reports_to": meta.pop("reports_to", "Bron"),
        "runs_in": meta.pop("runs_in", "any"),
        **meta,
    }
    return write_md(vault.agents_dir / name / "Agent.md", data, f"Instructions for {name}.\n")


def add_connection(vault: Vault, name: str, **meta) -> Path:
    data = {
        "name": name,
        "type": meta.pop("type", "mcp-stdio"),
        "command": meta.pop("command", "uvx"),
        "args": meta.pop("args", ["mcp-server-time"]),
        **meta,
    }
    return write_md(vault.connections_dir / f"{name}.md", data)
