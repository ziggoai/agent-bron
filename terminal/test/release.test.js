const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const {spawnSync} = require('node:child_process');

test('public releases fail before building or uploading when signing credentials are absent', () => {
  const env={...process.env};delete env.BRON_SIGN_IDENTITY;delete env.BRON_NOTARY_PROFILE;
  const result=spawnSync(process.execPath,[path.join(__dirname,'../scripts/release-public.cjs')],{env,encoding:'utf8'});
  assert.notEqual(result.status,0);
  assert.match(result.stderr,/Public release requires/);
  assert.equal(result.stdout,'');
});
