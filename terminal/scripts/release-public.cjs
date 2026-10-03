// Signing credentials are stored in the macOS keychain, never in the project.
const path = require('node:path');
const fs = require('node:fs');
const {execFileSync} = require('node:child_process');
const root = path.resolve(__dirname, '..');
const identity = process.env.BRON_SIGN_IDENTITY;
const profile = process.env.BRON_NOTARY_PROFILE;
if (!identity || identity === '-' || !profile) {
  throw new Error('Public release requires BRON_SIGN_IDENTITY (Developer ID Application) and BRON_NOTARY_PROFILE (notarytool keychain profile). No public release was produced.');
}
execFileSync('npm', ['run', 'package'], {cwd:root, stdio:'inherit'});
const binary = path.join(root, 'bin/pty-host-darwin');
execFileSync('/usr/bin/codesign', ['--verify', '--strict', binary], {stdio:'inherit'});
const {spawnSync} = require('node:child_process');
const signature = spawnSync('/usr/bin/codesign', ['--display', '--verbose=4', binary], {encoding:'utf8'});
if (signature.status !== 0 || !signature.stderr.includes('Authority=Developer ID Application:') || !signature.stderr.includes('runtime')) {
  throw new Error('Public release requires a Developer ID Application signature with hardened runtime.');
}
const version = JSON.parse(fs.readFileSync(path.join(root,'manifest.json'),'utf8')).version;
const archive = path.join(root,'dist',`bron-terminal-${version}-macos.zip`);
const result = JSON.parse(execFileSync('/usr/bin/xcrun', ['notarytool','submit',archive,'--keychain-profile',profile,'--wait','--output-format','json'], {encoding:'utf8',timeout:1800000}));
fs.writeFileSync(path.join(root,'dist',`notarization-${version}.json`), JSON.stringify(result,null,2)+'\n');
if (result.status !== 'Accepted') throw new Error('Apple did not accept the release. Inspect the notarization result; do not publish this archive.');
const publicDir = path.join(root, 'dist/public');
fs.mkdirSync(publicDir, {recursive:true});
const approved = path.join(publicDir, path.basename(archive));
fs.copyFileSync(archive, approved);
fs.writeFileSync(path.join(publicDir, `notarization-${version}.json`), JSON.stringify(result,null,2)+'\n');
console.log('Apple accepted the public release: ' + approved);
