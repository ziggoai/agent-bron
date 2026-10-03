// Claude's task footer lives below its editor. Read the live buffer, not the
// scrolled DOM, so activity remains current while browsing earlier messages.
function backgroundTaskLines(provider, lines, state) {
  if (provider !== 'claude' || !state.ready || state.native || !state.bottom) return [];
  const footer = lines.slice(lines.length - state.bottom);
  const start = footer.findIndex(line => /^\s*[⏺●•◯○]\s+main\s*$/u.test(line));
  if (start < 0) return [];
  const tasks = footer.slice(start);
  if (!tasks.slice(1).some(line => /^\s*[⏺●•◯○]\s+\S/u.test(line))) return [];
  while (tasks.length && !tasks[tasks.length - 1].trim()) tasks.pop();
  return tasks.map(line => line.replace(/^ {1,2}/, ''));
}

class BackgroundTasks {
  constructor(session, container) {
    this.session = session;
    const dock = container.parentElement?.nextElementSibling;
    if (!dock?.classList.contains('dt-dock')) return;
    this.panel = container.ownerDocument.createElement('div');
    this.panel.className = 'dt-background-tasks';
    this.panel.hidden = true;
    this.panel.setAttribute('role', 'region');
    this.panel.setAttribute('aria-label', 'Claude Code background tasks');
    dock.prepend(this.panel);
  }
  render(lines, state) {
    if (!this.panel) return;
    const text = backgroundTaskLines(this.session.provider, lines, state).join('\n');
    if (this.panel.textContent !== text) this.panel.textContent = text;
    this.panel.hidden = !text;
  }
  dispose() { this.panel?.remove(); }
}

module.exports = { backgroundTaskLines, BackgroundTasks };
