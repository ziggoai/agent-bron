"""The shipped plugin payload must stay in step with the terminal/ source."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TERMINAL = ROOT / 'terminal'
PAYLOAD = ROOT / 'core/Plugins/bron-terminal'
SINGLE_INPUTS = ['native/pty-host.c', 'styles.css', 'manifest.json', 'package-lock.json', 'scripts/build.cjs']


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def input_digest():
    rels = [p.relative_to(TERMINAL).as_posix() for d in ('src', 'assets') for p in (TERMINAL / d).rglob('*') if p.is_file()]
    rels = sorted(rels + SINGLE_INPUTS)
    digest = hashlib.sha256()
    for rel in rels:
        digest.update(f'{rel}\0{sha(TERMINAL / rel)}\n'.encode())
    return digest.hexdigest()


def test_payload_manifest_is_byte_equal_to_source():
    assert (PAYLOAD / 'manifest.json').read_bytes() == (TERMINAL / 'manifest.json').read_bytes()


def test_package_version_matches_manifest():
    manifest = json.loads((TERMINAL / 'manifest.json').read_text())['version']
    assert json.loads((TERMINAL / 'package.json').read_text())['version'] == manifest


def test_payload_styles_match_source():
    assert (PAYLOAD / 'styles.css').read_bytes() == (TERMINAL / 'styles.css').read_bytes()


def test_build_info_matches_source_inputs():
    info = json.loads((PAYLOAD / 'build-info.json').read_text())
    manifest = json.loads((TERMINAL / 'manifest.json').read_text())['version']
    assert info['manifestVersion'] == manifest
    assert info['packageVersion'] == manifest
    assert info['inputDigest'] == input_digest(), 'terminal/ changed since the payload was built: run npm run package --prefix terminal'


def test_checksums_match_payload_files_and_exclude_build_info():
    checksums = json.loads((PAYLOAD / 'checksums.json').read_text())
    assert 'build-info.json' not in checksums
    for name, expected in checksums.items():
        assert sha(PAYLOAD / name) == expected, name
