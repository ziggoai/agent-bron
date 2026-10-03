"""Zip the standalone plugin with executable permissions and no local settings."""
from pathlib import Path
import json
import sys
import zipfile

source, output = map(Path, sys.argv[1:])
version = json.loads((source / 'manifest.json').read_text())['version']
archive = output / f'bron-terminal-{version}-macos.zip'
files = [*json.loads((source / 'checksums.json').read_text()), 'checksums.json']
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as package:
    for name in files:
        info = zipfile.ZipInfo(f'bron-terminal/{name}', (2026, 10, 2, 0, 0, 0))
        info.create_system = 3
        info.external_attr = (0o100755 if name.startswith('bin/') else 0o100644) << 16
        info.compress_type = zipfile.ZIP_DEFLATED
        package.writestr(info, (source / name).read_bytes())
print(archive)
