"""The warm search helper: keeps the meaning model loaded so a search takes a fraction of a second."""
from __future__ import annotations

import dataclasses
import fcntl
import hashlib
import json
import os
import socket
import subprocess
import threading
import time
from pathlib import Path

from ..vault import Vault
from .store import KbError, kb_dir

SOCKET = "serve.sock"
LOCK = "serve.lock"
CONNECT_TIMEOUT = 1.0
REPLY_TIMEOUT = 5.0
IDLE_SECONDS = 1800
MAX_SOCKET_PATH = 100  # macOS allows about 104 bytes in a socket path
MAX_REQUEST = 1_000_000
FILTERS = ("company", "fund", "doc_type", "after", "before")


def _default_embedder(vault: Vault):
    from . import embed

    return embed.get(vault)


# Tests replace this with a stand-in; the helper never loads the real model in unit tests.
EMBEDDER_FACTORY = _default_embedder


class Probe:
    """Wraps an embedder and notes when the meaning model could not be used."""

    def __init__(self, embedder):
        self._inner = embedder
        self.failed = False

    @property
    def model(self):
        return getattr(self._inner, "model", "")

    def embed(self, texts):
        try:
            return self._inner.embed(texts)
        except KbError:
            self.failed = True
            raise


def socket_path(vault: Vault) -> Path:
    path = kb_dir(vault) / SOCKET
    if len(str(path).encode("utf-8")) <= MAX_SOCKET_PATH:
        return path
    digest = hashlib.sha256(str(vault.root).encode("utf-8")).hexdigest()[:8]
    # Not the temp folder: it differs from one process to the next, and the helper and its callers must agree.
    folder = os.environ.get("BRON_KB_SOCKET_DIR") or os.path.join(os.path.expanduser("~"), "Library", "Caches", "Bron")
    return Path(folder) / f"kb-{digest}.sock"


def _ours(path: Path) -> bool:
    """True when the socket file exists and belongs to this user."""
    try:
        return os.lstat(path).st_uid == os.getuid()
    except OSError:
        return False


def _try(path: Path, request: dict) -> tuple[dict | None, bool]:
    """(reply, nobody_listening). A helper that connects but doesn't answer in time gives (None, False)."""
    if not os.path.lexists(path):
        return None, True
    if not _ours(path):
        return None, False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.settimeout(CONNECT_TIMEOUT)
            try:
                conn.connect(str(path))
            except (ConnectionRefusedError, FileNotFoundError):
                return None, True
            conn.settimeout(REPLY_TIMEOUT)
            conn.sendall(json.dumps(request).encode("utf-8"))
            conn.shutdown(socket.SHUT_WR)
            chunks = []
            while True:
                data = conn.recv(65536)
                if not data:
                    break
                chunks.append(data)
        reply = json.loads(b"".join(chunks).decode("utf-8"))
        return (reply if isinstance(reply, dict) else None), False
    except (OSError, ValueError, RecursionError):
        return None, False


def _ask(path: Path, request: dict) -> dict | None:
    return _try(path, request)[0]


def ping(vault: Vault) -> bool:
    return bool((_ask(socket_path(vault), {"ping": True, "vault": str(vault.root)}) or {}).get("pong"))


def _version(vault: Vault) -> str:
    try:
        return (vault.core / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _answer(vault: Vault, embedder, request: dict) -> dict:
    from . import search

    if request.get("vault") != str(vault.root):
        return {"error": "wrong vault"}
    if request.get("ping"):
        return {"pong": True}
    probe = Probe(embedder)
    try:
        hits = search.search(vault, str(request.get("query", "")), embedder=probe,
                             limit=int(request.get("limit", 8)), **{k: str(request.get(k) or "") for k in FILTERS})
    except KbError as exc:
        return {"error": str(exc)}
    except Exception as exc:  # the helper must stay up whatever one search does
        return {"error": f"The search failed ({type(exc).__name__})."}
    return {"hits": [dataclasses.asdict(h) for h in hits], "keyword_only": probe.failed}


def _read_request(conn) -> dict | None:
    raw = b""
    try:
        while len(raw) < MAX_REQUEST:
            data = conn.recv(65536)
            if not data:
                break
            raw += data
        request = json.loads(raw.decode("utf-8"))
    except Exception:  # unreadable, oversized or absurdly nested
        return None
    return request if isinstance(request, dict) else None


def serve(vault: Vault, *, idle: float = IDLE_SECONDS, stop: threading.Event | None = None) -> None:
    folder = kb_dir(vault)
    folder.mkdir(parents=True, exist_ok=True)
    lock = open(folder / LOCK, "a+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        return  # another helper owns this vault
    path = socket_path(vault)
    server = None
    mine = None
    try:
        if os.path.lexists(path):
            if not _ours(path):
                print(f"The search helper's socket {path} belongs to another user; not starting.")
                return
            path.unlink()  # we hold the lock, so this is a leftover
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if path.parent != folder and path.parent.stat().st_uid == os.getuid():
                os.chmod(path.parent, 0o700)  # a folder made earlier with looser permissions
            server.bind(str(path))
        except OSError as exc:
            print(f"The search helper couldn't start: its socket {path} can't be used ({exc.strerror or type(exc).__name__}).")
            return
        mine = os.stat(path).st_ino
        os.chmod(path, 0o600)
        server.listen(4)
        poll = max(0.02, min(0.2, idle / 4))
        server.settimeout(poll)
        started = _version(vault)
        embedder = EMBEDDER_FACTORY(vault)
        warm = threading.Event()

        def warm_up():
            try:
                embedder.embed(["warm up"])  # load the model now, so the first real search is fast
            except Exception as exc:  # keyword search still works
                print(f"The meaning model didn't load ({type(exc).__name__}); serving keyword search only.")
            finally:
                warm.set()

        threading.Thread(target=warm_up, daemon=True).start()
        last = time.monotonic()
        while time.monotonic() - last < idle and not (stop and stop.is_set()):
            if _version(vault) != started:
                return  # Bron was updated: a new helper starts with the new code
            try:
                conn, _ = server.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with conn:
                conn.settimeout(5.0)
                request = _read_request(conn)
                if request is None:
                    reply = {"error": "bad request"}
                elif request.get("vault") == str(vault.root) and not request.get("ping") and not warm.is_set():
                    reply = {"busy": "warming up"}
                else:
                    reply = _answer(vault, embedder, request)
                try:
                    conn.sendall(json.dumps(reply).encode("utf-8"))
                except OSError:
                    pass
            if request and not request.get("ping") and "busy" not in reply:
                last = time.monotonic()
    finally:
        if server is not None:
            server.close()
        try:
            if mine is not None and os.stat(path).st_ino == mine:
                path.unlink()
        except OSError:
            pass
        lock.close()


def spawn(vault: Vault, *, popen=subprocess.Popen) -> bool:
    if os.environ.get("BRON_MEMORY_JOB"):
        return False
    from ..background import spawn_detached

    return spawn_detached(vault, ["kb", "serve"], "kb.log", popen=popen)


def query(vault: Vault, request: dict, *, start: bool = True, timeout: float = 5.0, popen=subprocess.Popen) -> dict | None:
    """Ask the warm helper. None means it isn't ready (not running, warming up, hung, or another vault's)."""
    request = {**request, "vault": str(vault.root)}

    path = socket_path(vault)
    reply, absent = _try(path, request)
    if reply is not None and (reply.get("busy") or reply.get("error") == "wrong vault"):
        return None
    if reply is not None or not absent or not start or not spawn(vault, popen=popen):
        return reply  # answered, or a helper is there but busy or hung: the caller searches itself
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(0.1)
        if ping(vault):
            reply = _ask(path, request)
            return None if reply and (reply.get("busy") or reply.get("error") == "wrong vault") else reply
    return None
