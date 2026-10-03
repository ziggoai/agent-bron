const { spawn } = require('node:child_process');
const { EventEmitter } = require('node:events');
const { setTimeout } = require('node:timers');
const MAX_FRAME = 2 * 1024 * 1024;

function encodeFrame(type, data = Buffer.alloc(0)) {
  data = Buffer.isBuffer(data) ? data : Buffer.from(data);
  if (data.length > MAX_FRAME) throw new Error('Terminal input is too large.');
  const frame = Buffer.allocUnsafe(5 + data.length);
  frame[0] = type.charCodeAt(0); frame.writeUInt32BE(data.length, 1); data.copy(frame, 5);
  return frame;
}
class FrameDecoder {
  constructor(receive) { this.buffer = Buffer.alloc(0); this.receive = receive; }
  push(chunk) {
    this.buffer = Buffer.concat([this.buffer, chunk]);
    while (this.buffer.length >= 5) {
      const length = this.buffer.readUInt32BE(1);
      if (length > MAX_FRAME) throw new Error('Invalid PTY frame length.');
      if (this.buffer.length < length + 5) return;
      const type = String.fromCharCode(this.buffer[0]), data = this.buffer.subarray(5, 5 + length);
      this.buffer = this.buffer.subarray(length + 5);
      this.receive(type, data);
    }
  }
}
class PtyProcess extends EventEmitter {
  constructor({ helper, executable, args, cwd, env, cols, rows }) {
    super();
    this.alive = false; this.ended = false;
    this.child = spawn(helper, [cwd, String(cols), String(rows), executable, ...args], { env, stdio: ['pipe', 'pipe', 'pipe'] });
    const decoder = new FrameDecoder((type, data) => {
      if ((['S', 'X'].includes(type) && data.length !== 4) || (type === 'F' && (data.length < 4 || data.length > 260))) throw new Error('Invalid PTY control frame.');
      if (type === 'S') { this.pid = data.readUInt32BE(0); this.alive = true; this.emit('ready'); }
      else if (type === 'F') { this.foreground = data.readUInt32BE(0); this.foregroundName = data.subarray(4).toString(); this.emit('foreground', this.foreground); }
      else if (type === 'D') this.emit('data', new Uint8Array(data));
      else if (type === 'X') this.finish(data.readUInt32BE(0));
      else if (type === 'E') this.emit('failure', new Error(data.toString()));
    });
    this.child.stdout.on('data', data => { try { decoder.push(data); } catch (error) { this.emit('failure', error); this.dispose(); } });
    this.child.stderr.on('data', data => this.emit('diagnostic', data.toString()));
    this.child.on('error', error => { this.emit('failure', error); this.finish(1); });
    this.child.on('close', code => this.finish(code ?? 1));
    this.child.stdin.on('error', error => { if (!this.ended) this.emit('failure', error); });
  }
  finish(code) { if (this.ended) return; this.ended = true; this.alive = false; this.emit('exit', code); }
  send(type, bytes) { if (this.ended || this.disposed || this.child.stdin.destroyed) throw new Error('The session has ended.'); this.child.stdin.write(encodeFrame(type, bytes)); }
  write(text) { this.send('I', Buffer.from(text)); }
  resize(cols, rows) { if (this.ended) return; const size = Buffer.alloc(8); size.writeUInt32BE(cols, 0); size.writeUInt32BE(rows, 4); this.send('R', size); }
  dispose() {
    if (this.disposed) return;
    this.disposed = true;
    this.child.stdout.resume();
    if (!this.child.stdin.destroyed) this.child.stdin.end();
    this.alive = false;
    const child = this.child;
    const timer = setTimeout(() => { if (child.exitCode === null && !child.signalCode) child.kill('SIGTERM'); }, 500);
    timer.unref();
  }
}
module.exports = { PtyProcess, FrameDecoder, encodeFrame };
