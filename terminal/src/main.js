const { Plugin, ItemView, Modal, FuzzySuggestModal, PluginSettingTab, Setting, Menu, Notice, setIcon } = require('obsidian');
const path = require('node:path');
const { webUtils } = require('electron');
const { installFileDrop } = require('./file-drop');
const { TerminalService, validateDirectory } = require('./terminal-service');
const { PROVIDERS, ComposerService, composeMessage, bufferDraft } = require('./composer-service');
const { TerminalPresentation, modeLabel } = require('./terminal-presentation');
const { TerminalInput, readEditor } = require('./terminal-input');

const PROVIDER_ICONS = { claude: require('../assets/claude.svg'), codex: require('../assets/codex.svg') };

const VIEW = 'bron-terminal';
const DEFAULTS = { provider: 'shell', shellPath: '', codexPath: '', claudePath: '' };

function iconButton(parent, icon, label, action, cls = '') {
  const button = parent.createEl('button', { cls: 'dt-icon ' + cls, attr: { type: 'button', 'aria-label': label, title: label } });
  setIcon(button, icon);
  button.addEventListener('click', action);
  return button;
}

class FolderModal extends Modal {
  constructor(app, cwd, select) { super(app); this.cwd = cwd; this.select = select; }
  onOpen() {
    this.titleEl.setText('Choose working folder');
    const form = this.contentEl.createEl('form');
    const label = form.createEl('label', { text: 'Folder path', attr: { for: 'dt-folder-path' } });
    label.addClass('dt-folder-label');
    const input = form.createEl('input', { type: 'text', value: this.cwd, cls: 'dt-folder-input', attr: { id: 'dt-folder-path', spellcheck: 'false' } });
    const errorEl = form.createDiv({ cls: 'dt-folder-error', attr: { role: 'alert' } });
    form.createEl('button', { text: 'Use folder', cls: 'mod-cta', attr: { type: 'submit' } });
    form.addEventListener('submit', async event => {
      event.preventDefault();
      try { const cwd = await validateDirectory(input.value.trim()); this.select(cwd); this.close(); }
      catch (error) { errorEl.setText(error.message); }
    });
    input.focus(); input.select();
  }
}

class FilePicker extends FuzzySuggestModal {
  constructor(app, select) { super(app); this.select = select; this.setPlaceholder('Attach a file from this vault…'); }
  getItems() { return this.app.vault.getFiles(); }
  getItemText(file) { return file.path; }
  onChooseItem(file) { this.select(file); }
}

class BronTerminalView extends ItemView {
  constructor(leaf, plugin) {
    super(leaf);
    this.plugin = plugin;
    this.provider = PROVIDERS[plugin.settings.provider] ? plugin.settings.provider : 'shell';
    this.cwd = this.app.vault.adapter.getBasePath();
    this.draft = '';
    this.attachments = [];
    this.composer = new ComposerService();
    this.phase = 'idle';
    this.closed = false;
  }
  getViewType() { return VIEW; }
  getDisplayText() { return PROVIDERS[this.session?.provider || this.provider].label; }
  getIcon() { return 'terminal-square'; }
  getState() { return { provider: this.provider, cwd: this.cwd, draft: this.input?.value ?? this.draft, attachments: this.attachments }; }
  async setState(state, result) {
    if (this.phase === 'idle') {
      this.provider = PROVIDERS[state.provider] ? state.provider : this.provider;
      this.cwd = typeof state.cwd === 'string' && path.isAbsolute(state.cwd) ? state.cwd : this.cwd;
      this.draft = typeof state.draft === 'string' ? state.draft : '';
      this.attachments = Array.isArray(state.attachments) ? state.attachments.filter(a => typeof a?.path === 'string' && typeof a?.name === 'string').slice(0, 12) : [];
      if (this.input) { this.input.value = this.draft; this.renderAttachments(); this.sync(); this.resizeInput(); }
    }
    await super.setState(state, result);
    this.leaf.updateHeader();
  }
  async onOpen() {
    this.closed = false;
    this.contentEl.empty(); this.contentEl.addClass('dt-view');
    this.root = this.contentEl.createDiv('dt-shell');
    this.body = this.root.createDiv('dt-body');
    this.terminalEl = this.body.createDiv('dt-terminal');
    this.terminalEl.hidden = true;
    this.dock = this.root.createDiv('dt-dock');
    this.card = this.dock.createDiv('dt-composer');
    this.chips = this.card.createDiv('dt-attachments');
    this.input = this.card.createEl('textarea', {
      cls: 'dt-input',
      attr: { placeholder: 'Enter a command, such as claude -c or codex resume…', 'aria-label': 'Terminal command or message', rows: '2', spellcheck: 'true' },
    });
    this.input.value = this.draft;
    this.input.addEventListener('focus', () => this.presentation?.setNative(false));
    this.input.addEventListener('input', () => {
      this.resizeInput(); this.sync(); this.saveLayout();
      this.syncTerminalInput();
    });
    this.input.addEventListener('keydown', event => {
      if (event.isComposing) return;
      const nativeKey = { Tab: '\t', ArrowUp: '\x1b[A', ArrowDown: '\x1b[B', Escape: '\x1b' }[event.key];
      const atEdge = !this.input.value.includes('\n') || (event.key === 'ArrowUp' ? this.input.selectionStart === 0 : this.input.selectionEnd === this.input.value.length);
      if (this.session?.provider !== 'shell' && nativeKey && !bufferDraft(this.input.value) && !event.shiftKey && !event.metaKey && !event.ctrlKey && atEdge && this.presentation?.state.ready) {
        event.preventDefault();
        if (event.key === 'Escape' && this.terminalInput?.pending) this.terminalInput.key(nativeKey);
        else if (this.syncTerminalInput()) this.terminalInput?.key(nativeKey);
        return;
      }
      if (event.ctrlKey && !event.metaKey && event.key.toLowerCase() === 'c' && this.input.selectionStart === this.input.selectionEnd && this.session) {
        event.preventDefault(); this.interrupt(); return;
      }
      if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); this.submit(); }
      if (event.key === 'Escape' && this.session) { event.preventDefault(); this.session.write('\x1b'); }
      if (event.key === 'Tab' && event.shiftKey && (this.session?.provider || this.provider) === 'claude' && this.presentation?.state?.ready) { event.preventDefault(); this.cycleMode(); }
    });
    const footer = this.card.createDiv('dt-composer-footer');
    iconButton(footer, 'plus', 'Attach a file or choose a working folder', event => this.attachmentMenu(event));
    this.createAgentPicker(footer);
    this.createModeButton(footer);
    footer.createSpan('dt-footer-spacer');
    this.status = footer.createSpan({ cls: 'dt-status', attr: { role: 'status', 'aria-live': 'polite' } });
    this.focusButton = iconButton(footer, 'terminal', 'Show terminal controls for menus and approvals', () => this.showTerminal());
    this.stopButton = iconButton(footer, 'square', 'Stop the response (Ctrl+C)', () => this.interrupt(), 'dt-stop');
    this.sendButton = iconButton(footer, 'arrow-up', 'Start session', () => this.submit(), 'dt-send');
    this.setupSessionControls();
    this.errorEl = this.dock.createDiv({ cls: 'dt-error', attr: { role: 'alert' } });
    const win = this.contentEl.ownerDocument.defaultView;
    this.observer = new win.ResizeObserver(() => { this.session?.fit(); });
    this.observer.observe(this.terminalEl);
    this.registerEvent(this.app.workspace.on('css-change', () => this.refreshTheme()));
    this.registerEvent(this.app.workspace.on('layout-change', () => this.session?.fit()));
    this.registerInterval(win.setInterval(() => {
      if (this.phase === 'running' && !this.session?.isAlive()) {
        this.phase = 'ended'; this.errorEl.setText('The terminal connection closed. Start a new session to continue.'); this.sync();
      }
    }, 1500));
    this.renderAttachments(); this.sync();
    installFileDrop(this, file => webUtils.getPathForFile(file));
    this.input.focus();
  }
  providerIcon(id) {
    if (id === 'shell') { const icon = this.contentEl.ownerDocument.createElement('span'); setIcon(icon, 'terminal-square'); return icon; }
    const doc = new this.contentEl.ownerDocument.defaultView.DOMParser().parseFromString(PROVIDER_ICONS[id], 'image/svg+xml');
    const svg = this.contentEl.ownerDocument.importNode(doc.documentElement, true);
    svg.setAttribute('aria-hidden', 'true'); svg.setAttribute('focusable', 'false');
    return svg;
  }
  // One control for the agent and its model; the model list itself stays in the CLI.
  createAgentPicker(footer) {
    this.agentButton = footer.createEl('button', { cls: 'dt-agent', attr: { type: 'button', 'aria-haspopup': 'menu' } });
    this.agentLogo = this.agentButton.createSpan('dt-agent-logo');
    this.agentLabel = this.agentButton.createSpan('dt-agent-label');
    setIcon(this.agentButton.createSpan('dt-agent-chevron'), 'chevron-down');
    this.agentButton.addEventListener('click', () => this.agentMenu());
    this.renderAgent();
  }
  renderAgent() {
    const provider = this.session?.provider || this.provider;
    const label = PROVIDERS[provider].label;
    if (this.agentButton.dataset.provider !== provider) {
      this.agentButton.dataset.provider = provider;
      this.agentLogo.replaceChildren(this.providerIcon(provider));
      this.agentLabel.setText(label);
    }
    const title = label + '. Choose a terminal or agent';
    this.agentButton.setAttribute('aria-label', title); this.agentButton.title = title;
  }
  agentMenu() {
    const rect = this.agentButton.getBoundingClientRect();
    this.buildAgentMenu().showAtPosition({ x: rect.left, y: rect.bottom }, this.contentEl.ownerDocument);
  }
  buildAgentMenu() {
    const locked = ['starting', 'running'].includes(this.phase);
    const current = this.session?.provider || this.provider;
    const menu = new Menu();
    for (const [id, provider] of Object.entries(PROVIDERS)) {
      // A running session keeps its agent; the other one opens beside it.
      const title = locked && id !== current ? 'Open ' + provider.label + ' in a new tab' : provider.label;
      menu.addItem(item => item.setTitle(title).setChecked(id === current).onClick(() => this.chooseProvider(id)));
    }
    menu.addSeparator();
    menu.addItem(item => item.setTitle('Change model…').setIcon('cpu')
      .setDisabled(this.phase !== 'running' || this.session?.provider === 'shell' || this.composer.sending).onClick(() => this.openModelMenu()));
    return menu;
  }
  chooseProvider(id) {
    if (id === (this.session?.provider || this.provider)) return;
    if (['starting', 'running'].includes(this.phase)) { this.plugin.open(id); return; }
    this.provider = id; this.plugin.settings.provider = id;
    this.plugin.saveSettings(); this.sync(); this.saveLayout(); this.leaf.updateHeader(); this.input.focus();
  }
  createModeButton(footer) {
    this.modeButton = footer.createEl('button', { cls: 'dt-mode', attr: { type: 'button' } });
    this.modeButton.createSpan('dt-mode-dot');
    this.modeLabel = this.modeButton.createSpan('dt-mode-label');
    this.modeButton.hidden = true;
    this.modeButton.addEventListener('click', () => this.cycleMode());
  }
  setMode(mode) {
    const { label, kind } = modeLabel(mode);
    this.modeButton.dataset.mode = kind;
    this.modeLabel.setText(label);
    const title = 'Claude Code mode: ' + label + '. Click or press Shift+Tab to change';
    this.modeButton.setAttribute('aria-label', title); this.modeButton.title = title;
  }
  setupSessionControls() {
    this.sessionControls?.remove();
    // Shown only while native terminal controls replace the composer.
    this.sessionControls = this.card.createDiv('dt-session-controls');
    this.hint = this.sessionControls.createDiv({ cls: 'dt-hint', text: 'Finish in the terminal, then return to your message' });
    this.returnButton = this.sessionControls.createEl('button', { cls: 'dt-return', text: 'Back to message' });
    this.returnButton.addEventListener('click', () => this.returnToComposer());
  }
  attachPresentation() {
    this.presentation?.dispose();
    this.presentation = new TerminalPresentation(this.session, this.terminalEl, state => this.updatePresentation(state));
  }
  syncTerminalInput() {
    if (this.session?.provider === 'shell') return false;
    if (this.phase !== 'running' || this.startingWithPrompt || this.composer.sending || !this.presentation?.state.ready || this.presentation.state.native) return false;
    if (bufferDraft(this.input.value)) return false;
    try { return this.terminalInput?.sync(this.input.value) ?? false; }
    catch (error) { this.errorEl.setText(error.message); return false; }
  }
  updatePresentation(state) {
    if (!this.modeButton) return;
    this.renderAgent();
    const provider = this.session?.provider || this.provider;
    this.input.placeholder = provider === 'shell' ? 'Enter a command, such as claude -c or codex resume…' : 'Message ' + PROVIDERS[provider].label + '…';
    if (this.renderedProvider !== provider) { this.renderedProvider = provider; this.leaf.updateHeader(); }
    const entering = this.card.dataset.native !== 'true' && state?.native;
    const returning = this.card.dataset.native === 'true' && !state?.native;
    this.card.dataset.native = String(!!state?.native);
    if (state?.mode) this.setMode(state.mode);
    this.modeButton.hidden = this.phase !== 'running' || (this.session?.provider || this.provider) !== 'claude' || !this.modeLabel.textContent;
    this.modeButton.disabled = !state?.ready || this.composer.sending;
    this.sessionControls.hidden = !state?.native;
    // Stop takes the send button's place while a response runs and the draft is empty.
    const busy = this.phase === 'running' && !!state?.busy;
    this.stopButton.hidden = !busy;
    this.sendButton.hidden = busy && !this.input.value.trim();
    this.stopButton.classList.toggle('dt-primary', this.sendButton.hidden);
    if (entering) this.session?.focus();
    this.input.hidden = !!state?.native;
    if (returning && this.nativeEdited && this.session?.provider !== 'shell' && !this.terminalInput?.pending && !this.composer.sending && !this.startingWithPrompt) this.terminalInput?.adopt();
    if (returning) this.nativeEdited = false;
    if (returning) this.input.focus();
    if (state?.ready && !state.native) this.syncTerminalInput();
  }
  returnToComposer() {
    if (this.session?.atShell && this.nativeEdited) {
      // A native shell line cannot be inferred from an arbitrary user prompt.
      // Cancel that unsubmitted line before accepting a new composer command.
      this.session.write('\x03'); this.nativeEdited = false;
    }
    this.presentation?.setNative(false);
    if (this.presentation?.state.native) { this.session?.write("\x1b"); return; }
    this.input.focus();
  }
  cycleMode() {
    if (!this.session?.isAlive() || !this.presentation?.state?.ready || this.composer.sending) return;
    try { this.session.write('\x1b[Z'); this.input.focus(); }
    catch (error) { this.errorEl.setText(error.message); }
  }
  showTerminal() { this.presentation?.setNative(true); this.session?.focus(); }
  saveLayout() { this.app.workspace.requestSaveLayout(); }
  resizeInput() { this.input.style.height = 'auto'; this.input.style.height = Math.min(this.input.scrollHeight, 200) + 'px'; }
  sync() {
    const running = this.phase === 'running';
    const starting = this.phase === 'starting';
    this.renderAgent();
    const shell = (this.session?.provider || this.provider) === 'shell';
    this.input.placeholder = shell ? 'Enter a command, such as claude -c or codex resume…' : 'Message ' + PROVIDERS[this.session?.provider || this.provider].label + '…';
    this.status.setText(starting ? 'Starting…' : this.phase === 'ended' ? 'Session ended' : '');
    this.status.dataset.phase = this.phase;
    this.updatePresentation(this.presentation?.state);
    this.focusButton.hidden = !running;
    this.sendButton.disabled = starting || this.startingWithPrompt || this.composer.sending || (running && !this.input.value.trim());
    this.input.disabled = !!this.startingWithPrompt;
    const label = running || this.input.value.trim() ? 'Send message (Enter) · Shift+Enter for a new line' : 'Start ' + PROVIDERS[this.provider].label + ' (Enter)';
    this.sendButton.setAttribute('aria-label', label); this.sendButton.title = label;
    setIcon(this.sendButton, running || this.input.value.trim() ? 'arrow-up' : 'play');
    this.root.dataset.phase = this.phase;
  }
  async submit() {
    if (this.phase === 'starting' || this.startingWithPrompt || this.composer.sending || this.closed) return;
    this.errorEl.empty();
    if (this.phase !== 'running') return this.start(false, true);
    if (this.terminalInput?.pending) return;
    if (this.presentation && !this.presentation.state?.ready) {
      this.errorEl.setText('Finish the prompt in terminal controls before sending a message.');
      this.showTerminal(); return;
    }
    const draft = this.input.value;
    if (!draft.trim()) return;
    const attachments = [...this.attachments];
    if (this.session.provider === 'shell') {
      if (attachments.length) { this.errorEl.setText('Use file paths in shell commands, or start an agent to send attachments.'); return; }
      try {
        const pending = this.composer.send(this.session, draft); this.sync(); await pending;
        if (!this.closed && this.input.value === draft) this.input.value = '';
        this.resizeInput(); this.saveLayout();
      } catch (error) { if (!this.closed) this.errorEl.setText(error.message); }
      finally { if (!this.closed) { this.sync(); if (!this.presentation?.state.native) this.input.focus(); } }
      return;
    }
    if (!attachments.length && this.terminalInput && !bufferDraft(draft)) {
      try { if (this.syncTerminalInput()) this.terminalInput.key('\r'); }
      catch (error) { this.errorEl.setText(error.message); }
      return;
    }
    try {
      // Validate before changing the native editor or clearing any draft.
      composeMessage(draft, attachments);
      if (this.terminalInput && !this.terminalInput.sync('')) return;
      const pending = this.composer.send(this.session, draft, attachments);
      this.sync();
      await pending;
      if (this.closed) return;
      if (this.input.value === draft) this.input.value = '';
      this.attachments = this.attachments.filter(a => !attachments.includes(a));
      this.renderAttachments(); this.resizeInput(); this.saveLayout();
    } catch (error) { if (!this.closed) this.errorEl.setText(error.message); }
    finally { if (!this.closed) { this.sync(); if (!this.presentation?.state.native) this.input.focus(); } }
  }
  async start(resume = false, sendDraft = false) {
    if (this.closed || this.phase === 'starting' || this.phase === 'running') return;
    this.errorEl.empty();
    const draft = this.input.value;
    const attachments = [...this.attachments];
    let initialPrompt = '';
    try { if (sendDraft && draft.trim()) initialPrompt = composeMessage(draft, attachments); }
    catch (error) { this.errorEl.setText(error.message); return; }
    // Large argv values exceed macOS exec limits. Paste after the editor is ready.
    const pasteInitial = this.provider === 'shell' || Buffer.byteLength(initialPrompt, 'utf8') > 64 * 1024;
    if (this.provider === 'shell' && attachments.length) { this.errorEl.setText('Start an agent to send attachments, or use file paths in a shell command.'); return; }
    this.startingWithPrompt = !!initialPrompt;
    this.presentation?.dispose(); this.presentation = null;
    this.terminalInput?.dispose(); this.terminalInput = null;
    this.setMode('');
    this.session?.dispose(); this.session = null;
    this.terminalEl.empty();
    this.phase = 'starting'; this.sync();
    this.terminalEl.hidden = false;
    try {
      const session = await this.plugin.terminals.create({
        provider: this.provider, cwd: this.cwd, container: this.terminalEl, resume, initialPrompt: pasteInitial ? '' : initialPrompt,
        onExit: code => { if (!this.closed) { this.phase = 'ended'; if (code && initialPrompt && !this.input.value) { this.input.value = draft; this.attachments = attachments; this.renderAttachments(); this.saveLayout(); } this.sync(); this.errorEl.setText('Session ended' + (code ? ' with code ' + code : '') + '. Start again or open a new tab.'); } },
        onError: message => { if (!this.closed) this.errorEl.setText(message); },
      });
      if (this.closed) { session.dispose(); return; }
      this.session = session;
      this.terminalInput = new TerminalInput(session, value => {
        if (this.closed) return;
        this.input.value = value; this.resizeInput(); this.saveLayout(); this.sync();
      }, message => { if (!this.closed) { this.errorEl.setText(message); this.showTerminal(); } });
      session.submit = text => {
        if (session.provider === 'shell') session.write('\r');
        else if (!this.terminalInput.submitPasted(text)) throw new Error('The terminal is still handling the previous input.');
      };
      session.host?.addEventListener('keydown', event => {
        if (!event.metaKey && !(event.ctrlKey && event.key === 'c' && session.terminal.hasSelection())) {
          if (this.presentation?.state.ready) this.nativeEdited = true;
          this.presentation?.setNative(true);
        }
      }, true);
      session.host?.addEventListener('paste', () => { this.nativeEdited = true; this.presentation?.setNative(true); }, true);
      this.attachPresentation();
      if (this.phase === 'starting') this.phase = 'running';
      this.sync(); this.session.fit(); if (!this.presentation?.state.native) this.input.focus();
      // Initial text is a CLI argument, so login and trust menus cannot consume it as keystrokes.
      if (initialPrompt) {
        if (pasteInitial) {
          try {
            const generation = this.composer.generation;
            const deadline = Date.now() + 15000;
            while (!this.presentation?.state.ready || !session.terminal.modes.bracketedPasteMode) {
              if (this.closed || !session.isAlive()) throw new Error('Session ended. Your full draft is still here.');
              if (generation !== this.composer.generation) throw new Error('Send cancelled. Your full draft is still here.');
              if (Date.now() >= deadline) throw new Error('Finish setup in the terminal, then send your message. Your full draft is still here.');
              await new Promise(resolve => setTimeout(resolve, 100));
            }
            await this.composer.send(session, draft, attachments);
          } catch (error) { if (!this.closed) this.errorEl.setText(error.message); return; }
        }
        if (this.input.value === draft) this.input.value = '';
        this.attachments = this.attachments.filter(a => !attachments.includes(a));
        this.renderAttachments(); this.resizeInput(); this.saveLayout(); this.sync(); if (!this.presentation?.state.native) this.input.focus();
      }
    } catch (error) {
      if (this.closed) return;
      this.presentation?.dispose(); this.presentation = null; this.terminalInput?.dispose(); this.terminalInput = null; this.session?.dispose(); this.session = null;
      this.phase = 'idle'; this.terminalEl.hidden = true;
      this.errorEl.setText(error.message); this.sync();
    } finally { this.startingWithPrompt = false; if (!this.closed) this.sync(); this.syncTerminalInput(); }
  }
  interrupt() { this.composer.cancel(); try { if (!this.terminalInput?.key('\x03')) this.session?.write('\x03'); this.input.focus(); } catch (error) { this.errorEl.setText(error.message); } }
  async openModelMenu() {
    if (!this.session?.isAlive() || this.session.provider === 'shell' || this.composer.sending || this.terminalInput?.pending) return;
    if (!this.presentation?.state?.ready) { this.showTerminal(); return; }
    try {
      if (!this.terminalInput?.sync('')) return;
      const session = this.session;
      const pending = this.composer.send({ isAlive: () => session.isAlive(), paste: text => session.paste(text), write: text => session.write(text) }, '/model');
      this.sync(); await pending; this.showTerminal();
    }
    catch (error) { this.errorEl.setText(error.message); }
    finally { if (!this.closed) this.sync(); }
  }
  chooseFolder() {
    if (['running', 'starting'].includes(this.phase)) return;
    new FolderModal(this.app, this.cwd, cwd => { this.cwd = cwd; this.sync(); this.saveLayout(); }).open();
  }
  chooseFile() { new FilePicker(this.app, file => this.attachFile(file)).open(); }
  attachFile(file) {
    if (!file) { new Notice('Open a note or choose a file to attach.'); return; }
    const fullPath = path.join(this.app.vault.adapter.getBasePath(), file.path);
    if (this.attachments.some(a => a.path === fullPath)) return;
    if (this.attachments.length >= 12) { new Notice('You can attach up to 12 files per message.'); return; }
    this.attachments.push({ name: file.name, path: fullPath });
    this.renderAttachments(); this.saveLayout(); this.input.focus();
  }
  attachmentMenu(event) {
    const menu = new Menu();
    menu.addItem(item => item.setTitle('Choose a vault file').setIcon('paperclip').onClick(() => this.chooseFile()));
    menu.addItem(item => item.setTitle('Attach current note').setIcon('file-text').onClick(() => this.attachFile(this.app.workspace.getActiveFile())));
    menu.addSeparator();
    menu.addItem(item => item.setTitle('New session in a new tab').setIcon('plus').onClick(() => this.plugin.open(this.provider)));
    menu.addItem(item => item.setTitle('Resume a saved session').setIcon('history').setDisabled(this.provider === 'shell' || ['running', 'starting'].includes(this.phase)).onClick(() => this.start(true)));
    menu.addItem(item => item.setTitle('Choose working folder…').setIcon('folder').setDisabled(['running', 'starting'].includes(this.phase)).onClick(() => this.chooseFolder()));
    menu.showAtMouseEvent(event);
  }
  renderAttachments() {
    this.chips.empty(); this.chips.hidden = !this.attachments.length;
    for (const attachment of this.attachments) {
      const chip = this.chips.createDiv({ cls: 'dt-chip', attr: { title: attachment.path } });
      setIcon(chip.createSpan(), 'file-text'); chip.createSpan({ text: attachment.name });
      iconButton(chip, 'x', 'Remove ' + attachment.name, () => {
        this.attachments = this.attachments.filter(a => a !== attachment); this.renderAttachments(); this.saveLayout();
      });
    }
  }
  refreshTheme() { if (this.session?.isAlive()) this.plugin.terminals.applyTheme(this.session, this.terminalEl); }
  async onClose() {
    this.disposeFileDrop?.();
    this.closed = true; this.composer.cancel(); this.observer?.disconnect(); this.terminalInput?.dispose(); this.presentation?.dispose(); this.session?.dispose(); this.contentEl.empty();
  }
}

class BronTerminalSettings extends PluginSettingTab {
  constructor(app, plugin) { super(app, plugin); this.plugin = plugin; }
  display() {
    this.containerEl.empty();
    this.containerEl.createEl('p', { text: 'Bron Terminal includes its own local terminal backend. The default Terminal opens your login shell. Run any command, including claude -c and codex resume. Shell environment and CLI authentication settings are preserved.' });
    for (const [id, provider] of Object.entries(PROVIDERS)) {
      new Setting(this.containerEl).setName(provider.label + ' executable').setDesc('Optional absolute path. Leave empty to detect automatically.').addText(text => text.setPlaceholder('/absolute/path/to/' + provider.command).setValue(this.plugin.settings[id + 'Path']).onChange(async value => { this.plugin.settings[id + 'Path'] = value.trim(); await this.plugin.saveSettings(); }));
    }
    this.containerEl.createEl('p', { text: 'Closing a Bron Terminal tab ends its process. Use the history button to open the agent’s saved-session picker. Running processes do not survive an Obsidian restart.' });
  }
}

module.exports = class BronTerminalPlugin extends Plugin {
  async onload() {
    this.settings = { ...DEFAULTS, ...await this.loadData() };
    if (!PROVIDERS[this.settings.provider]) this.settings.provider = 'shell';
    this.terminals = new TerminalService(this.settings, path.join(this.app.vault.adapter.getBasePath(), this.manifest.dir));
    this.registerView(VIEW, leaf => new BronTerminalView(leaf, this));
    this.addRibbonIcon('square-terminal', 'Open Bron Terminal', () => this.open());
    this.addCommand({ id: 'open', name: 'Open Bron Terminal', callback: () => this.open() });
    for (const [provider, info] of Object.entries(PROVIDERS)) this.addCommand({ id: 'open-' + provider, name: 'Open ' + info.label, callback: () => this.open(provider) });
    this.addSettingTab(new BronTerminalSettings(this.app, this));
  }
  async open(provider = 'shell') {
    const leaf = this.app.workspace.getLeaf('tab');
    await leaf.setViewState({ type: VIEW, active: true, state: { provider } });
    this.app.workspace.setActiveLeaf(leaf, { focus: true });
  }
  async saveSettings() { await this.saveData(this.settings); }
  onunload() { this.terminals?.dispose(); }
};

// Expose the view class for the in-app integration checks.
module.exports.View = BronTerminalView;
