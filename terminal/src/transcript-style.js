function isToolAction(text) {
  return /^\s*[⏺●]\s+(?:Bash|Read|Write|Edit|Update|Search|Glob|Grep|WebFetch|WebSearch|Task|Agent|ToolSearch)\(/u.test(text)
    || /^\s*[•●]\s+(?:Ran|Running|Explored|Edited|Added|Deleted|Updated)\b/u.test(text)
    || /^\s*[└├⎿]\s+(?:Read|Search|List|Write|Edit|Update|Bash)\b/u.test(text)
    || /^\s*(?:Read|Wrote|Edited|Searched)\s+\d+\s+files?\b/u.test(text);
}

const STYLES = `
.xterm-rows > [data-dt-action] { background-color: var(--dt-tool-background); }
.xterm-rows > [data-dt-action] > span:not([class*="xterm-fg-"]):not([style*="color:"]),
.xterm-rows > [data-dt-action] > span.xterm-fg-0:not([style*="color:"]) { color: var(--dt-tool-color); }
`;

class TranscriptStyle {
  constructor(session, isNative = () => false) {
    this.session = session; this.isNative = isNative;
    const shadow = session.host.shadowRoot;
    this.style = session.host.ownerDocument.createElement('style');
    this.style.textContent = STYLES; shadow.appendChild(this.style);
    this.listener = session.terminal.onRender(() => this.render());
    this.render();
  }
  render() {
    const host = this.session.host, dark = host.ownerDocument.body.classList.contains('theme-dark');
    host.style.setProperty('--dt-tool-color', dark ? '#8ab4f8' : '#2862b3');
    host.style.setProperty('--dt-tool-background', dark ? '#8ab4f812' : '#2862b30c');
    const rows = host.shadowRoot.querySelector('.xterm-rows');
    if (!rows) return;
    for (const row of rows.children) {
      const action = !this.isNative() && isToolAction(row.textContent);
      if (action) row.setAttribute('data-dt-action', '');
      else row.removeAttribute('data-dt-action');
    }
  }
  dispose() {
    this.listener.dispose(); this.style.remove();
    for (const row of this.session.host.shadowRoot.querySelectorAll('[data-dt-action]')) row.removeAttribute('data-dt-action');
  }
}
module.exports = { isToolAction, TranscriptStyle };
