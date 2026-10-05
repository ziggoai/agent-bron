const { claudeCompletionRange, completionRange, CompletionLayout } = require('./completion-layout');
const { TranscriptStyle } = require('./transcript-style');
const { BackgroundTasks } = require('./background-tasks');

// Read the rendered screen, so split escape sequences never become UI state.
function inspectScreen(provider, lines, cursor) {
  const result = { top: 0, bottom: 0, mode: '', ready: false, busy: false };
  // A session started as an agent shows its name in the border: "──── bron ─".
  const rule = text => /^\s*(?:[─━-]{8,}|[─━-]+ History \d+\/\d+ [─━-]+|[─━-]{8,} [^─━\s][^─━]{0,40} [─━-]+)\s*$/u.test(text || '');
  if (provider === 'claude') {
    for (let row = lines.length - 2; row >= 1; row--) {
      if (!rule(lines[row])) continue;
      let start = row - 1;
      while (start >= 0 && !rule(lines[start])) start--;
      if (start < 0 || !rule(lines[start]) || !/^\s*[❯!](?:\s|$)/u.test(lines[start + 1] || '')) continue;
      // Background task rows are free text ("Confirming…", "Select…"), not dialog hints.
      const below = lines.slice(row + 1);
      const tasks = below.findIndex(line => /^\s*[⏺●•◯○]\s+main\s*$/u.test(line));
      const footer = (tasks < 0 ? below : below.slice(0, tasks)).join(' ').trim();
      const suggestions = claudeCompletionRange(lines, start + 1, row)
        || /^\s+(?:[+*◇]\s+\S|(?:\/|…)\S+\s{2,}\S)/u.test(lines[row + 1] || '');
      // The cursor visits result rows while Claude redraws; the ruled prompt stays the editor.
      if (suggestions) {
        result.bottom = lines.length - start; result.ready = true; break;
      }
      // Other footer text may belong to a dialog.
      const streaming = /\besc to interrupt\b/i.test(footer);
      const inputHint = /(?:paste again to expand|! for shell mode)/i.test(footer);
      if ((!streaming && !inputHint && (cursor < start + 1 || cursor >= row)) || /(?:enter to|esc to (?!interrupt\b)|confirm|yes|no,|select)/i.test(footer)) continue;
      if (footer && !streaming && !inputHint && !/(?:shift\+tab|\? for shortcuts|agents|context|tokens|auto mode|manual mode|plan mode|accept edits|bypass permissions)/i.test(footer)) continue;
      if (/Ctrl\+Y to paste deleted text/i.test(lines[start - 1] || '')) start--;
      if (/^\s*●?\s*(?:low|medium|high|max)\s*·\s*\/effort\s*$/i.test(lines[start - 1] || '')) start--;
      result.bottom = lines.length - start;
      result.ready = true;
      result.mode = footer.match(/(?:auto mode|manual mode|plan mode|accept edits|bypass permissions)(?:\s+on)?/i)?.[0] || '';
      if (!result.mode && !inputHint) result.mode = 'Mode';
      break;
    }
  } else if (provider === 'codex') {
    // The prompt has its own row; choice menus use › beside a numbered option.
    for (let row = lines.length - 1; row >= 0; row--) {
      if (!/^\s*›/.test(lines[row]) || /^\s*›\s*\d+[.)]/.test(lines[row])) continue;
      const following = lines.slice(row + 1);
      if (following.some(line => /^\s*[•●⏺›]/u.test(line))) continue;
      const footer = following.join(' ');
      if (!/(?:context left|for shortcuts|for agents|·\s*(?:~|\/)|(?:gpt|GPT|o\d)-)/.test(footer)) continue;
      if (/(?:enter (?:to |select|default)|esc (?:to (?!interrupt\b)|back)|confirm|allow once|select a)/i.test(footer)) continue;
      let start = row;
      // Codex draws a blank row above its prompt background.
      if (start > 0 && !lines[start - 1].trim()) start--;
      result.bottom = lines.length - start;
      result.ready = true;
      break;
    }
  }
  // Both CLIs print this hint only while a response is running.
  result.busy = result.ready && lines.some(line => /\besc to interrupt\b/i.test(line));
  // Never crop past the conversation or a native dialog.
  result.top = Math.min(result.top, lines.length - result.bottom);
  return result;
}

// "auto mode on" → { label: "Auto mode", kind: "auto" } for the composer's mode pill.
function modeLabel(mode) {
  const text = String(mode || '').trim().replace(/\s+on$/i, '');
  const kind = (text.match(/^(auto|manual|plan|accept|bypass)\b/i)?.[1] || 'other').toLowerCase();
  return { label: text ? text[0].toUpperCase() + text.slice(1) : '', kind };
}

class TerminalPresentation {
  constructor(session, container, onChange) {
    this.session = session; this.container = container; this.onChange = onChange;
    this.native = false; this.sawDialog = false; this.disposed = false;
    this.state = {top:0, bottom:0, mode:'', ready:false, busy:false, native:false};
    const terminal = session.terminal;
    this.completions = new CompletionLayout(session, container);
    this.backgroundTasks = new BackgroundTasks(session, container);
    this.listeners = [terminal.onWriteParsed(() => this.update()), terminal.onRender(() => this.update(true)), terminal.onScroll(() => this.scheduleUpdate()), terminal.onResize(() => this.scheduleUpdate())];
    session.onForeground = () => this.update();
    this.update();
    this.transcriptStyle = new TranscriptStyle(session, () => this.state.native);
  }
  scheduleUpdate() {
    const win = this.container.ownerDocument.defaultView;
    if (this.timer) return;
    this.timer = win.setTimeout(() => { this.timer = null; this.update(); }, 100);
  }
  setNative(value) {
    if (this.native === value) return;
    this.native = value;
    this.sawDialog = value && !this.state.ready;
    this.update();
  }
  update(rendered = false) {
    if (this.disposed) return;
    const terminal = this.session.terminal, buffer = terminal.buffer.active;
    const lines = Array.from({ length: terminal.rows }, (_,row) => buffer.getLine(buffer.baseY + row)?.translateToString(true) || '');
    let candidate;
    if (this.session.launchProvider === 'shell' && this.session.atShell) {
      this.session.provider = 'shell';
      candidate = { top: 0, bottom: 0, mode: '', ready: !!terminal.modes.bracketedPasteMode && buffer.type !== 'alternate', busy: false };
    } else if (this.session.launchProvider === 'shell') {
      const claude = inspectScreen('claude', lines, buffer.cursorY);
      const codex = inspectScreen('codex', lines, buffer.cursorY);
      if (claude.ready) { this.session.provider = 'claude'; candidate = claude; }
      else if (codex.ready) { this.session.provider = 'codex'; candidate = codex; }
    }
    candidate ??= inspectScreen(this.session.provider, lines, buffer.cursorY);
    const win = this.container.ownerDocument.defaultView;
    const now = win.performance?.now() ?? Date.now();
    let state = candidate, pending = false;
    if (!candidate.ready && !this.native && !this.state.native && this.lastReady) {
      this.unknownSince ??= now;
      if (now - this.unknownSince < 180) {
        // Keep the previous crop during split redraws; block sends until confirmed.
        state = { ...this.lastReady, ready: false };
        pending = true;
        this.scheduleUpdate();
      }
    } else { this.unknownSince = null; }
    if (candidate.ready) this.lastReady = candidate;
    if (!state.ready && !pending) this.sawDialog = true;
    if (state.ready && this.sawDialog) { this.native = false; this.sawDialog = false; }
    // Unknown screens belong to native controls. Never place our input below them.
    const native = this.native || (!state.ready && !pending);
    this.backgroundTasks.render(lines, { ...state, native });
    const range = !native && buffer.viewportY === buffer.baseY ? (pending ? this.lastCompletion : completionRange(this.session.provider, lines, state)) : null;
    if (!pending) this.lastCompletion = range;
    if ((rendered && !pending) || native) this.completions.render(range);
    const cropRows = range ? Math.max(state.bottom, terminal.rows - range.start) : state.bottom;
    const screen = this.session.host.shadowRoot.querySelector('.xterm-screen');
    const cell = screen?.getBoundingClientRect().height / terminal.rows || 0;
    if (!cell || !this.container.clientHeight) return;
    const atBottom = buffer.viewportY === buffer.baseY;
    const top = !native && atBottom ? state.top * cell : 0;
    // The live prompt remains in the viewport for the first few scrollback rows.
    // Move its boundary with the buffer instead of exposing it as soon as we scroll.
    const visibleCropRows = Math.max(0, cropRows - Math.max(0, buffer.baseY - buffer.viewportY));
    let bottom = !native && visibleCropRows ? Math.max(0, this.session.host.clientHeight - (terminal.rows - visibleCropRows) * cell + 1) : 0;
    // Parsed writes can lead the DOM, especially during synchronized output.
    // Cover both prompt positions until xterm has rendered the new one.
    if (native || !atBottom || rendered) this.paintedBottom = bottom;
    else bottom = Math.max(bottom, this.paintedBottom ?? bottom);
    this.paintedBottom ??= bottom;
    this.state = { ...state, native, provider: this.session.provider };
    if (native) this.notify();
    const clip = `inset(${top}px 0 ${bottom}px 0)`;
    if (this.clip !== clip) { this.clip = clip; this.session.host.style.clipPath = clip; }
    const transform = `translateY(${-top}px)`;
    if (this.transform !== transform) { this.transform = transform; this.session.host.style.transform = transform; }
    // Reclaim the banner space without resizing the PTY on every animation frame.
    const padding = Math.round((top + (state.bottom ? Math.min(state.bottom, 5) * cell : 0)) * 100) / 100;
    const reclaim = native || !atBottom ? 0 : padding;
    if (this.reclaim !== reclaim) {
      this.reclaim = reclaim;
      this.container.parentElement.style.marginBottom = `${-reclaim}px`;
      this.scheduleFit();
    }
    if (!native) this.notify();
  }
  notify() {
    const key = JSON.stringify([this.state.native, this.state.ready, this.state.mode, this.state.busy, this.state.provider]);
    if (this.uiKey !== key) { this.uiKey = key; this.onChange(this.state); }
  }
  scheduleFit() {
    if (this.frame) return;
    this.frame = this.container.ownerDocument.defaultView.requestAnimationFrame(() => {
      this.frame = null;
      if (!this.disposed) { this.session.fit(); this.scheduleUpdate(); }
    });
  }
  dispose() {
    this.disposed = true; this.container.ownerDocument.defaultView.clearTimeout(this.timer); this.listeners.forEach(listener => listener.dispose());
    this.session.onForeground = null;
    if (this.frame) this.container.ownerDocument.defaultView.cancelAnimationFrame(this.frame);
    this.session.host.style.clipPath = ''; this.session.host.style.transform = '';
    this.container.parentElement.style.marginBottom = '';
    this.completions.dispose();
    this.backgroundTasks.dispose();
    this.transcriptStyle?.dispose();
  }
}
module.exports = { inspectScreen, modeLabel, TerminalPresentation };
