const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { once } = require('node:events');
const { PtyProcess, FrameDecoder, encodeFrame } = require('../src/pty-process');
const helper = path.join(__dirname, '../bin/pty-host-darwin');
const options = { helper, cwd: '/tmp', env: process.env, cols: 80, rows: 24 };

test('frame decoder handles partial frames and split UTF-8 bytes', () => {
  const received = [];
  const decoder = new FrameDecoder((type, data) => received.push([type, data.toString()]));
  const bytes = Buffer.concat([encodeFrame('D', 'olá 世界'), encodeFrame('X', 'done')]);
  for (const byte of bytes) decoder.push(Buffer.from([byte]));
  assert.deepEqual(received, [['D', 'olá 世界'], ['X', 'done']]);
  assert.throws(() => new FrameDecoder(() => {}).push(Buffer.from([68, 255, 255, 255, 255])), /Invalid/);
});

test('bundled helper runs a program directly and delivers its exit code', { timeout: 5000 }, async () => {
  const prompt = 'line one\nline two $(literal)';
  const pty = new PtyProcess({ ...options, executable: '/usr/bin/printf', args: ['%s', prompt] });
  let output = '';
  pty.on('data', data => { output += Buffer.from(data).toString(); });
  const [code] = await once(pty, 'exit');
  assert.equal(code, 0);
  assert.equal(output.replace(/\r\n/g, '\n'), prompt);
  assert.equal(pty.alive, false);
});

test('PTY input and resizing reach the child process', { timeout: 5000 }, async () => {
  const pty = new PtyProcess({ ...options, executable: '/bin/sh', args: ['-c', 'read line; stty size; printf "GOT:%s" "$line"'] });
  let output = '';
  pty.on('data', data => { output += Buffer.from(data).toString(); });
  await once(pty, 'ready');
  pty.resize(91, 33); pty.write('hello\r');
  const [code] = await once(pty, 'exit');
  assert.equal(code, 0);
  assert.match(output, /33 91/);
  assert.match(output, /GOT:hello/);
});

test('closing the parent pipe terminates the owned process group', { timeout: 5000 }, async () => {
  const pty = new PtyProcess({ ...options, executable: '/bin/sh', args: ['-c', 'sleep 60 & wait'] });
  await once(pty, 'ready');
  const pid = pty.pid;
  const closed = once(pty.child, 'close');
  pty.dispose(); await closed;
  assert.throws(() => process.kill(pid, 0), /ESRCH/);
});

test('cleanup works when the Electron renderer exposes browser timers', { timeout: 5000 }, async () => {
  const pty = new PtyProcess({ ...options, executable: '/bin/cat', args: [] });
  await once(pty, 'ready');
  const closed = once(pty.child, 'close');
  const original = globalThis.setTimeout;
  try {
    globalThis.setTimeout = () => 123;
    assert.doesNotThrow(() => pty.dispose());
  } finally { globalThis.setTimeout = original; }
  await closed;
});

test('startup failure is reported and no shell fallback is opened', { timeout: 5000 }, async () => {
  const pty = new PtyProcess({ ...options, executable: '/not/a/real/program', args: [] });
  let output = '';
  pty.on('data', data => { output += Buffer.from(data).toString(); });
  const [code] = await once(pty, 'exit');
  assert.equal(code, 127);
  assert.match(output, /Start agent/);
  assert.throws(() => pty.write('should not run'), /ended/);
});

test('login-shell foreground jobs are reported and terminate when the tab closes', {timeout:5000}, async () => {
  const pty=new PtyProcess({...options,executable:'/bin/zsh',args:['-f']});
  try {
    await once(pty,'ready');
    pty.write('sleep 60\r');
    let job;
    const deadline=Date.now()+2000;
    while (Date.now()<deadline) {
      if (pty.foreground && pty.foreground!==pty.pid) {job=pty.foreground;break;}
      await new Promise(r=>setTimeout(r,20));
    }
    assert.ok(job,'foreground job must have its own process group');
    const closed=once(pty.child,'close');pty.dispose();await closed;
    assert.throws(()=>process.kill(job,0),/ESRCH/);
  } finally {pty.dispose();}
});

test('exec replacing a shell changes foreground identity even when the PID stays the same', {timeout:5000}, async () => {
  const pty=new PtyProcess({...options,executable:'/bin/zsh',args:['-f']});
  try {
    await once(pty,'ready');pty.write('exec /bin/cat\r');
    const deadline=Date.now()+2000;
    while (Date.now()<deadline && pty.foregroundName!=='cat') await new Promise(r=>setTimeout(r,20));
    assert.equal(pty.foreground,pty.pid);assert.equal(pty.foregroundName,'cat');
  } finally {pty.dispose();}
});
