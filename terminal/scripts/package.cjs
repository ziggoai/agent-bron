// Produce the exact standalone payload consumed by the framework installer.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {execFileSync} = require('node:child_process');
const root = path.resolve(__dirname, '..');
const target = path.resolve(root, '../core/Plugins/bron-terminal');
const files = ['main.js', 'manifest.json', 'styles.css', 'THIRD-PARTY-NOTICES.txt', 'bin/pty-host-darwin'];
fs.mkdirSync(target, {recursive: true});
const hashes = {};
for (const file of files) {
  const data = fs.readFileSync(path.join(root, file));
  const dest = path.join(target, file);
  fs.mkdirSync(path.dirname(dest), {recursive: true});
  fs.writeFileSync(dest, data);
  fs.chmodSync(dest, file.startsWith('bin/') ? 0o755 : 0o644);
  hashes[file] = crypto.createHash('sha256').update(data).digest('hex');
}
// Digest of every build input, so the shipped copy can be proven to match this source.
function walk(dir) {
  return fs.readdirSync(dir, {withFileTypes: true}).flatMap(entry => {
    const full = path.join(dir, entry.name);
    return entry.isDirectory() ? walk(full) : [full];
  });
}
const inputs = [
  ...walk(path.join(root, 'src')),
  ...walk(path.join(root, 'assets')),
  ...['native/pty-host.c', 'styles.css', 'manifest.json', 'package-lock.json', 'scripts/build.cjs'].map(f => path.join(root, f)),
].map(f => path.relative(root, f).split(path.sep).join('/')).sort();
const digest = crypto.createHash('sha256');
for (const rel of inputs) {
  digest.update(rel + '\0' + crypto.createHash('sha256').update(fs.readFileSync(path.join(root, rel))).digest('hex') + '\n');
}
const manifestVersion = JSON.parse(fs.readFileSync(path.join(root, 'manifest.json'), 'utf8')).version;
const packageVersion = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8')).version;
fs.writeFileSync(path.join(target, 'build-info.json'), JSON.stringify({
  manifestVersion, packageVersion, inputDigest: digest.digest('hex'), inputs,
}, null, 2) + '\n');
fs.writeFileSync(path.join(target, 'checksums.json'), JSON.stringify(hashes, null, 2) + '\n');
const dist = path.join(root, 'dist');
fs.mkdirSync(dist, {recursive:true});
execFileSync('python3', [path.resolve(root, '../scripts/package-terminal.py'), target, dist], {stdio:'inherit'});
