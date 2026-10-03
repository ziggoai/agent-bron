const fs = require('node:fs/promises');
const { constants } = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { PROVIDERS } = require('./composer-service');

async function findExecutable(provider, override = '') {
  if (provider === 'shell') {
    const shell = override || process.env.SHELL || '/bin/zsh';
    if (!path.isAbsolute(shell)) throw new Error('The shell must be an absolute executable path.');
    try { if (!(await fs.stat(shell)).isFile()) throw new Error(); await fs.access(shell, constants.X_OK); }
    catch { throw new Error('The configured shell is not executable: ' + shell); }
    return shell;
  }
  const name = PROVIDERS[provider]?.command;
  if (!name) throw new Error('Choose Codex or Claude Code.');
  const candidates = override ? [override] : [path.join(os.homedir(), '.local/bin', name), '/opt/homebrew/bin/' + name, '/usr/local/bin/' + name, ...(process.env.PATH || '').split(path.delimiter).filter(Boolean).map(p => path.join(p, name))];
  for (const file of [...new Set(candidates)]) {
    if (!path.isAbsolute(file)) continue;
    try { if ((await fs.stat(file)).isFile()) { await fs.access(file, constants.X_OK); return file; } } catch {}
  }
  throw new Error(`${PROVIDERS[provider].label} was not found. Install and sign in to its CLI, or set its executable path in Bron Terminal settings.`);
}

async function validateDirectory(directory) {
  if (!path.isAbsolute(directory)) throw new Error('Choose an absolute folder path.');
  try { if ((await fs.stat(directory)).isDirectory()) return directory; } catch {}
  throw new Error('That folder does not exist or cannot be opened.');
}

function launchOptions(provider, executable, cwd, environment = process.env, resume = false, initialPrompt = '') {
  if (!PROVIDERS[provider]) throw new Error('Unknown provider.');
  const env = { ...environment, TERM: 'xterm-256color', COLORTERM: 'truecolor' };
  // Preserve authentication and CLI settings, as a regular terminal does.
  // Parent-session integration addresses cannot belong to this new terminal.
  for (const key of ['TERMY_AGENT_CONTEXT_URL', 'TERMY_AGENT_CONTEXT_TOKEN', 'CLAUDE_CODE_SSE_PORT', 'CLAUDE_CODE_ENTRYPOINT']) delete env[key];
  // Resolve subprocess tools when Obsidian was opened from Finder.
  env.PATH = [...new Set([path.dirname(executable), path.join(os.homedir(), '.local/bin'), '/opt/homebrew/bin', '/usr/local/bin', ...(env.PATH || '/usr/bin:/bin:/usr/sbin:/sbin').split(path.delimiter)])].join(path.delimiter);
  const args = [...(resume ? PROVIDERS[provider].resumeArgs : PROVIDERS[provider].args)];
  if (initialPrompt && provider !== 'shell') args.push('--', initialPrompt);
  return { executable, args, cwd, env };
}

class TerminalService {
  constructor(settings, pluginDir) { this.settings = settings; this.pluginDir = pluginDir; this.sessions = new Set(); this.closed = false; }
  async create({ provider, cwd, container, onExit, onError, resume = false, initialPrompt = '' }) {
    if (this.closed) throw new Error('Bron Terminal has been unloaded.');
    if (process.platform !== 'darwin') throw new Error('This release includes the macOS terminal backend.');
    const executable = await findExecutable(provider, this.settings[provider + 'Path']);
    await validateDirectory(cwd);
    const helper = path.join(this.pluginDir, 'bin/pty-host-darwin');
    try { await fs.access(helper, constants.X_OK); }
    catch { throw new Error('The Bron terminal helper is missing or not executable. Reinstall the complete plugin folder.'); }
    const { Terminal } = require('@xterm/xterm');
    const { FitAddon } = require('@xterm/addon-fit');
    const { PtyProcess } = require('./pty-process');
    const css = require('@xterm/xterm/css/xterm.css');
    const doc = container.ownerDocument;
    await doc.fonts.ready;
    if (this.closed || !container.isConnected) throw new Error('The terminal tab was closed during startup.');
    const host = doc.createElement('div'); host.className = 'dt-terminal-host';
    host.style.cssText = 'height:100%;width:100%;overflow:hidden;';
    container.appendChild(host);
    const shadow = host.attachShadow({ mode: 'open' });
    const stylesheet = doc.createElement('style');
    stylesheet.textContent = css + '\n:host { display:block; height:100%; } .dt-mount { height:100%; } .xterm { height:100%; } .xterm .xterm-viewport { background:transparent; }';
    shadow.appendChild(stylesheet);
    const mount = doc.createElement('div'); mount.className = 'dt-mount'; shadow.appendChild(mount);
    const style = doc.defaultView.getComputedStyle(container);
    const terminal = new Terminal({
      fontFamily: style.fontFamily || 'Menlo, monospace', fontSize: Math.max(10, Math.min(24, parseFloat(style.fontSize) || 13)),
      lineHeight: 1.2, cursorStyle: 'bar', cursorBlink: true, scrollback: 10000, minimumContrastRatio: 1,
      allowProposedApi: true, macOptionIsMeta: true, theme: this.theme(container),
    });
    const fitAddon = new FitAddon(); terminal.loadAddon(fitAddon);
    terminal.open(mount); fitAddon.fit();
    let alive = true, backend;
    const subscriptions = [];
    const session = {
      terminal, provider, launchProvider: provider, cwd, host,
      isAlive: () => alive && !this.closed && !!backend?.alive,
      paste: text => {
        if (!session.isAlive()) throw new Error('The session has ended.');
        if (!terminal.modes.bracketedPasteMode) throw new Error('Finish setup in the terminal before sending a message.');
        terminal.paste(text);
      },
      write: text => { if (!session.isAlive()) throw new Error('The session has ended.'); backend.write(text); },
      focus: () => terminal.focus(),
      fit: () => { if (alive && container.isConnected && container.clientWidth > 20 && container.clientHeight > 20) fitAddon.fit(); },
      dispose: () => { if (!alive && !host.isConnected) return; alive = false; subscriptions.splice(0).forEach(s => s.dispose()); backend?.dispose(); terminal.dispose(); host.remove(); this.sessions.delete(session); },
      get pid() { return backend?.pid; },
      get atShell() { return provider === 'shell' && !!backend?.pid && backend.foreground === backend.pid && backend.foregroundName === path.basename(executable); },
    };
    this.sessions.add(session);
    try {
      backend = new PtyProcess({ helper, ...launchOptions(provider, executable, cwd, process.env, resume, initialPrompt), cols: terminal.cols, rows: terminal.rows });
      subscriptions.push(terminal.onData(data => { if (session.isAlive()) backend.write(data); }));
      subscriptions.push(terminal.onBinary(data => { if (session.isAlive()) backend.send('I', Buffer.from(data, 'binary')); }));
      subscriptions.push(terminal.onResize(({cols, rows}) => backend.resize(cols, rows)));
      let queuedOutput = 0;
      backend.on('data', data => {
        if (!alive || this.closed) return;
        queuedOutput += data.byteLength;
        if (queuedOutput > 1024 * 1024) backend.child.stdout.pause();
        terminal.write(data, () => {
          queuedOutput -= data.byteLength;
          if (queuedOutput < 512 * 1024) backend.child.stdout.resume();
        });
      });
      backend.on('foreground', () => session.onForeground?.());
      backend.on('exit', code => { alive = false; onExit?.(code); });
      backend.on('failure', error => onError?.(error.message));
      await new Promise((resolve, reject) => {
        const timer = setTimeout(() => finish(new Error('The terminal did not start.')), 5000);
        const fail = error => finish(error);
        const exited = code => finish(new Error('The agent exited during startup with code ' + code + '.'));
        const ready = () => finish();
        const finish = error => { clearTimeout(timer); backend.off('ready', ready); backend.off('failure', fail); backend.off('exit', exited); error ? reject(error) : resolve(); };
        backend.once('ready', ready); backend.once('failure', fail); backend.once('exit', exited);
      });
      if (this.closed || !container.isConnected) throw new Error('The terminal tab was closed during startup.');
      if (!session.isAlive()) throw new Error('The agent exited during startup. Your draft is still here.');
      return session;
    } catch (error) { session.dispose(); throw error; }
  }
  theme(container) {
    const style = container.ownerDocument.defaultView.getComputedStyle(container);
    return { background: style.backgroundColor, foreground: style.color, cursor: style.color, cursorAccent: style.backgroundColor, selectionBackground: '#729ee455' };
  }
  applyTheme(session, container) {
    session.terminal.options.theme = this.theme(container);
    const style = container.ownerDocument.defaultView.getComputedStyle(container);
    session.terminal.options.fontFamily = style.fontFamily;
    session.terminal.options.fontSize = Math.max(10, Math.min(24, parseFloat(style.fontSize) || 13));
    session.fit();
  }
  dispose() { this.closed = true; [...this.sessions].forEach(s => s.dispose()); }
}

module.exports = { TerminalService, findExecutable, validateDirectory, launchOptions };
