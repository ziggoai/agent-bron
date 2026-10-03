const { normalizeDraft } = require('./composer-service');
const { inspectScreen } = require('./terminal-presentation');
const { completionRange } = require('./completion-layout');

function readEditor(session) {
  const t = session.terminal, b = t.buffer.active;
  const rows = Array.from({ length: t.rows }, (_, i) => b.getLine(b.baseY + i));
  const lines = rows.map(row => row?.translateToString(true) || '');
  const state = inspectScreen(session.provider, lines, b.cursorY);
  if (!state.ready) return null;
  const start = lines.findLastIndex(line => session.provider === 'claude' ? /^\s*[❯!]\s/u.test(line) : /^\s*›\s/u.test(line));
  if (start < 0 || b.cursorY < start) return null;
  const text = [];
  for (let i = start; i <= b.cursorY; i++) {
    const row = rows[i];
    if (i > start && (/^\s*[─━-]{8,}/u.test(lines[i]) || /(?:GPT-|gpt-|context left)/.test(lines[i]))) return null;
    const raw = row?.translateToString(false, 0, i === b.cursorY ? b.cursorX : undefined) || '';
    const content = i === start ? raw.replace(/^\s*[❯›!]\s?/u, '') : raw.replace(/^  /, '');
    text.push(i === b.cursorY ? content : content.trimEnd());
    if (i < b.cursorY && !rows[i + 1]?.isWrapped) text.push('\n');
  }
  const shell = session.provider === 'claude' && /^\s*!/.test(lines[start]);
  return (shell ? '!' : '') + text.join('');
}

function editSequence(previous, next) {
  const a = Array.from(previous), b = Array.from(next);
  let prefix = 0, suffix = 0;
  while (prefix < a.length && prefix < b.length && a[prefix] === b[prefix]) prefix++;
  while (suffix < a.length - prefix && suffix < b.length - prefix && a[a.length - 1 - suffix] === b[b.length - 1 - suffix]) suffix++;
  const inserted = b.slice(prefix, b.length - suffix).join('').replace(/\t/g, '\x1b[200~\t\x1b[201~').replace(/\n/g, '\x1b\r');
  return '\x1b[D'.repeat(suffix) + '\x7f'.repeat(a.length - prefix - suffix) + inserted + '\x1b[C'.repeat(suffix);
}

function sameDraft(text, before) {
  if (text === before) return true;
  // CLI word wrapping may add newlines without marking xterm rows as wrapped.
  return typeof text === 'string' && (text.includes('\n') || before.includes('\n'))
    && text.replace(/\s/g, '') === before.replace(/\s/g, '');
}

function restoreFileMentions(text, files) {
  if (typeof text !== 'string' || !text.includes('\n')) return text;
  return text.replace(/@"([^"\n]*\n[^"]*)"/g, (match, wrapped) => {
    const key = wrapped.replace(/\s/g, '');
    const file = files.find(file => !file.includes('…') && file.replace(/\s/g, '') === key);
    return file ? '@"' + file + '"' : match;
  });
}

// The native editor owns completion lists, history, and command selection.
class TerminalInput {
  constructor(session, onEdit, onError = () => {}) {
    this.session = session; this.onEdit = onEdit; this.onError = onError;
    this.value = ''; this.pending = false; this.disposed = false; this.blocked = false;
    this.listener = session.terminal.onWriteParsed(() => this.scheduleReconcile());
  }
  scheduleReconcile() {
    if (!this.pending || this.disposed) return;
    clearTimeout(this.settleTimer);
    this.settleTimer = setTimeout(() => { if (this.pending) this.reconcile(); }, 30);
  }
  sync(value) {
    value = normalizeDraft(value);
    if (this.disposed || this.blocked) return false;
    if (this.pending) { this.queued = value; return false; }
    if (!this.session.isAlive()) return false;
    if (value === this.value) return true;
    this.session.write(editSequence(this.value, value));
    this.value = value;
    return true;
  }
  // Pasted drafts and typed drafts share the same submission/acknowledgment path.
  submitPasted(text) {
    this.value = text;
    return this.key('\r', true);
  }
  key(key, pasted = false) {
    if (this.pending && (key === '\x1b' || key === '\x03')) this.reset();
    if (this.pending || this.disposed || !this.session.isAlive()) return false;
    const terminal = this.session.terminal, buffer = terminal.buffer.active;
    const lines = Array.from({ length: terminal.rows }, (_, i) => buffer.getLine(buffer.baseY + i)?.translateToString(true) || '');
    this.mentionFiles = lines.map(line => line.match(/^\s*\+\s+(.+)$/u)?.[1]).filter(Boolean);
    const state = inspectScreen(this.session.provider, lines, buffer.cursorY);
    this.submitting = key === '\r' && (pasted || !completionRange(this.session.provider, lines, state));
    this.before = this.value;
    this.queued = undefined;
    // Mutate local state only after the PTY accepted the write.
    this.session.write(key);
    this.pending = true; this.pendingKey = key; this.deadline = Date.now() + 5000;
    if (this.submitting) { this.value = ''; this.onEdit(''); }
    this.timer = setTimeout(() => this.reconcile(true), 250);
    return true;
  }
  reconcile(force = false) {
    if (this.disposed || !this.pending) return;
    const text = restoreFileMentions(readEditor(this.session), this.mentionFiles || []);
    if (!this.session.isAlive()) { this.fail('The session ended. Check the terminal before sending again.'); return; }
    if (this.pendingKey === '\r' && this.before.trim() &&
        (sameDraft(text, this.before) || (this.submitting && text?.trim()))) {
      if (Date.now() >= this.deadline) {
        this.fail('The terminal has not confirmed Enter. Check terminal controls before sending again.');
      } else if (force) {
        clearTimeout(this.timer); this.timer = setTimeout(() => this.reconcile(true), 250);
      }
      return;
    }
    if (text === this.before && !force) return;
    if (text === null && !force) return;
    clearTimeout(this.timer); clearTimeout(this.settleTimer);
    this.pending = false;
    this.value = text ?? '';
    let value = this.value;
    if (this.queued !== undefined) {
      value = this.submitting ? this.queued : this.queued === this.before ? value
        : this.queued.startsWith(this.before) ? value + this.queued.slice(this.before.length) : this.queued;
    }
    this.queued = undefined;
    this.onEdit(value);
  }
  fail(message) {
    clearTimeout(this.timer); clearTimeout(this.settleTimer);
    this.pending = false; this.blocked = true;
    this.onError(message);
  }
  adopt() {
    const text = readEditor(this.session);
    if (text === null) return false;
    // Native editing may leave the caret in the middle. Ask that editor to move
    // to its end before reading back, rather than deleting an unseen suffix.
    this.reset(); this.value = text; return this.key('\x05');
  }
  reset() { clearTimeout(this.timer); clearTimeout(this.settleTimer); this.pending = false; this.blocked = false; this.queued = undefined; this.value = ''; }
  dispose() { this.disposed = true; clearTimeout(this.timer); clearTimeout(this.settleTimer); this.listener.dispose(); }

}
module.exports = { TerminalInput, readEditor, editSequence, restoreFileMentions };
