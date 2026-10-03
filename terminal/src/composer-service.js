const PROVIDERS = Object.freeze({
  shell: { label: 'Terminal', command: 'shell', args: ['-il'], resumeArgs: ['-il'] },
  codex: { label: 'Codex', command: 'codex', args: ['--no-alt-screen'], resumeArgs: ['resume', '--no-alt-screen'] },
  claude: { label: 'Claude Code', command: 'claude', args: [], resumeArgs: ['--resume'] },
});
const MAX_MESSAGE_BYTES = 1024 * 1024;
// Keep long drafts in the composer; the CLI may collapse them to a paste label.
function bufferDraft(value) { return Buffer.byteLength(value, 'utf8') > 4096 || /[\r\n\t]/.test(value); }

function normalizeDraft(value) {
  const text = String(value).replace(/\r\n?/g, '\n');
  // Terminal control bytes must never become keystrokes from pasted prose.
  if (/[\x00-\x08\x0b-\x1f\x7f]/.test(text)) throw new Error('Remove terminal control characters before sending.');
  if (Buffer.byteLength(text, 'utf8') > MAX_MESSAGE_BYTES) throw new Error('This message exceeds 1 MiB of text. Your full draft is still here; attach a file instead.');
  return text;
}

function normalizeMessage(value) {
  const text = normalizeDraft(value);
  if (!text.trim()) throw new Error('Write a message first.');
  return text;
}

function composeMessage(draft, attachments) {
  const text = normalizeMessage(draft);
  if (!attachments.length) return text;
  return normalizeMessage(`${text}\n\nAttached local files:\n${attachments.map(a => JSON.stringify(a.path)).join('\n')}\nRead these files if they are relevant to the request.`);
}

class ComposerService {
  constructor(wait = ms => new Promise(resolve => setTimeout(resolve, ms))) { this.wait = wait; this.sending = false; this.generation = 0; }
  cancel() { this.generation++; }
  async send(session, draft, attachments = []) {
    if (this.sending) throw new Error('The previous message is still being sent.');
    if (!session?.isAlive()) throw new Error('Start a session before sending.');
    const text = composeMessage(draft, attachments);
    const generation = this.generation;
    this.sending = true;
    try {
      // Both CLIs distinguish bracketed paste from typed Enter keys.
      session.paste(text);
      await this.wait(180);
      if (this.generation !== generation) throw new Error('Send cancelled. Your draft is still here.');
      if (!session.isAlive()) throw new Error('The session ended before the message was sent. Your draft is still here.');
      if (session.submit) session.submit(text);
      else session.write('\r');
      return { text, sent: true };
    } finally { this.sending = false; }
  }
}

module.exports = { PROVIDERS, MAX_MESSAGE_BYTES, bufferDraft, normalizeDraft, normalizeMessage, composeMessage, ComposerService };
