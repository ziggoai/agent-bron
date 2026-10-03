const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { ComposerService, normalizeMessage, composeMessage } = require('../src/composer-service');
const { findExecutable, validateDirectory, launchOptions, TerminalService } = require('../src/terminal-service');

test('multiline messages arrive as one paste before Enter', async () => {
  const events = [];
  const session = { isAlive: () => true, paste: text => events.push(['paste', text]), write: text => events.push(['write', text]) };
  const composer = new ComposerService(async () => events.push(['wait']));
  await composer.send(session, 'first line\r\nsecond line');
  assert.deepEqual(events, [['paste', 'first line\nsecond line'], ['wait'], ['write', '\r']]);
});

test('a stopped session never receives the delayed Enter', async () => {
  let alive = true;
  let enters = 0;
  const composer = new ComposerService(async () => { alive = false; });
  await assert.rejects(composer.send({ isAlive: () => alive, paste() {}, write() { enters++; } }, 'hello'), /ended/);
  assert.equal(enters, 0);
  assert.equal(composer.sending, false);
});

test('rapid double-send cannot interleave terminal input', async () => {
  let release;
  const composer = new ComposerService(() => new Promise(resolve => { release = resolve; }));
  const session = { isAlive: () => true, paste() {}, write() {} };
  const first = composer.send(session, 'first');
  await assert.rejects(composer.send(session, 'second'), /previous message/);
  release(); await first;
});

test('interrupting during paste cancels the pending Enter', async () => {
  let release;
  let enters = 0;
  const composer = new ComposerService(() => new Promise(resolve => { release = resolve; }));
  const pending = composer.send({ isAlive: () => true, paste() {}, write() { enters++; } }, 'draft');
  composer.cancel(); release();
  await assert.rejects(pending, /cancelled/);
  assert.equal(enters, 0);
});

test('pasted escape sequences and other terminal controls are rejected', () => {
  for (const value of ['\x1b[201~rm -rf test', 'abc\x03', 'abc\0', '\n\t']) assert.throws(() => normalizeMessage(value));
  assert.equal(normalizeMessage('Olá\n\t世界'), 'Olá\n\t世界');
});

test('attachments are explicit quoted paths, including spaces and newlines', () => {
  const message = composeMessage('Read this', [{ path: '/tmp/A folder/a\nb.md' }]);
  assert.match(message, /"\/tmp\/A folder\/a\\nb.md"/);
});

test('launch uses an argument array and preserves API-key environment variables', () => {
  for (const provider of ['claude', 'codex']) {
    const config = launchOptions(provider, '/tmp/cli path;literal', '/tmp/folder with spaces', { ANTHROPIC_API_KEY: 'secret', OPENAI_API_KEY: 'secret', PATH: '/bin', SAFE: 'yes' });
    assert.equal(config.executable, '/tmp/cli path;literal');
    assert.equal(config.env.ANTHROPIC_API_KEY, 'secret');
    assert.equal(config.env.OPENAI_API_KEY, 'secret');
    assert.equal(config.env.SAFE, 'yes');
    assert.equal(config.cwd, '/tmp/folder with spaces');
    assert.ok(!config.args.includes('-c'));
  }
});

test('executable and working-folder validation reject unusable paths', async () => {
  const temp = await fs.mkdtemp(path.join(os.tmpdir(), 'bron-terminal-test-'));
  try {
    const executable = path.join(temp, 'cli');
    await fs.writeFile(executable, '#!/bin/sh\nexit 0\n', { mode: 0o755 });
    assert.equal(await findExecutable('claude', executable), executable);
    assert.equal(await validateDirectory(temp), temp);
    await assert.rejects(findExecutable('claude', temp), /not found/);
    await assert.rejects(findExecutable('codex', 'relative/path'), /not found/);
    await assert.rejects(validateDirectory(executable), /does not exist/);
    await assert.rejects(validateDirectory('relative/path'), /absolute/);
  } finally { await fs.rm(temp, { recursive: true, force: true }); }
});

test('resume opens the correct native session picker for each provider', () => {
  assert.deepEqual(launchOptions('codex', '/bin/codex', '/tmp', {}, true).args, ['resume', '--no-alt-screen']);
  assert.deepEqual(launchOptions('claude', '/bin/claude', '/tmp', {}, true).args, ['--resume']);
});

test('the first draft is passed once as a positional argument, never as shell code', () => {
  const prompt = '--dangerous\n$(touch /tmp/not-created)';
  for (const provider of ['codex', 'claude']) assert.deepEqual(launchOptions(provider, '/bin/agent', '/tmp', {}, false, prompt).args.slice(-2), ['--', prompt]);
});

test('unload disposes only sessions owned by this plugin', () => {
  const service = new TerminalService({}, {});
  const disposed = [];
  service.sessions.add({ dispose: () => disposed.push('ours') });
  service.dispose();
  assert.deepEqual(disposed, ['ours']);
  assert.equal(service.closed, true);
});

test('shell startup uses the real login shell and never turns a command into an AI prompt', async () => {
  const executable=await findExecutable('shell','/bin/zsh');
  const launch=launchOptions('shell',executable,'/tmp',{PATH:'/bin',ANTHROPIC_AUTH_TOKEN:'test',TERMY_AGENT_CONTEXT_TOKEN:'stale'},false,'claude -c');
  assert.equal(launch.executable,'/bin/zsh');assert.deepEqual(launch.args,['-il']);
  assert.equal(launch.env.ANTHROPIC_AUTH_TOKEN,'test');assert.equal(launch.env.TERMY_AGENT_CONTEXT_TOKEN,undefined);
});
