function claudeCompletionRange(lines, prompt, inputEnd) {
  const query = lines.slice(prompt, inputEnd).join(' ').replace(/^\s*❯\s?/u, '').trimEnd();
  const mention = /(?:^|\s)@[^\s]*$/.test(query);
  const command = /^\//.test(query);
  if (!mention && !command) return null;
  const option = line => mention ? /^\s+[+*◇]\s+\S/u.test(line || '') : /^\s+(?:\/|…)\S+\s{2,}\S/u.test(line || '');
  const range = (start, end) => mention ? { start, end, kind: 'mentions' } : { start, end };
  if (option(lines[inputEnd + 1])) {
    const start = inputEnd + 1;
    let end = start;
    while (end + 1 < lines.length && lines[end + 1].trim()) end++;
    return range(start, end);
  }
  // Older fullscreen Claude sessions put suggestions above the input rules.
  let end = prompt - 2;
  if (end < 0 || !lines[end]?.trim()) return null;
  let start = end;
  while (start > 0 && lines[start - 1].trim() && end - start < 20) start--;
  return lines.slice(start, end + 1).some(option) ? range(start, end) : null;
}

function completionRange(provider, lines, state) {
  if (!state.ready || state.native) return null;
  const prompt = lines.findLastIndex(line => provider === 'claude' ? /^\s*❯\s/u.test(line) : /^\s*›\s/u.test(line));
  if (prompt < 0) return null;
  if (provider === 'claude') {
    const inputEnd = lines.findIndex((line, i) => i > prompt && /^\s*[─━-]{8,}\s*$/u.test(line));
    return inputEnd < 0 ? null : claudeCompletionRange(lines, prompt, inputEnd);
  }
  const query = lines[prompt].replace(/^\s*›\s?/u, '');
  if (!/^\//.test(query) && !/(?:^|\s)[$@][^\s]*$/.test(query)) return null;
  const selected = lines.findLastIndex((line, i) => i < prompt && /^\s*›\s+\S.*\s{2,}\S/.test(line) && !/^\s*›\s*\d+[.)]/.test(line));
  if (selected < 0) return null;
  let start = selected, end = prompt - 1;
  while (start > 0 && lines[start - 1].trim() && selected - start < 20) start--;
  while (end > selected && !lines[end].trim()) end--;
  return { start, end };
}

class CompletionLayout {
  constructor(session, container) {
    this.session = session;
    const doc = container.ownerDocument;
    const dock = container.parentElement?.nextElementSibling;
    if (!dock?.classList.contains('dt-dock')) return;
    this.panel = doc.createElement('div');
    this.panel.className = 'dt-suggestions'; this.panel.hidden = true;
    this.panel.dataset.provider = session.provider;
    this.panel.setAttribute('aria-hidden', 'true');
    this.panel.addEventListener('mousedown', event => { event.preventDefault(); dock.querySelector('textarea')?.focus(); });
    dock.prepend(this.panel);
    this.shadow = this.panel.attachShadow({ mode: 'open' });
  }
  render(range) {
    if (!this.panel) return;
    if (!range) { this.panel.hidden = true; this.key = null; return; }
    const source = this.session.host.shadowRoot;
    const rows = source.querySelector('.xterm-rows');
    if (!rows || rows.children.length <= range.end) return;
    const styles = [...source.querySelectorAll('style')].map(style => style.textContent).join('\n');
    const content = [...rows.children].slice(range.start, range.end + 1);
    const doc = this.panel.ownerDocument;
    if (!this.styleElement) {
      this.styleElement = doc.createElement('style');
      this.owner = doc.createElement('div');
      this.shadow.append(this.styleElement, this.owner);
    }
    if (this.styles !== styles) {
      this.styles = styles;
      this.styleElement.textContent = styles + '\n:host { height:auto!important; } .xterm { height:auto!important; padding:0; } .xterm-rows { position:static!important; } .xterm-rows>div { width:100%!important; }';
    }
    this.owner.className = source.querySelector('.xterm').className;
    const key = range.kind + rows.getAttribute('style') + content.map(row => row.outerHTML).join('');
    if (this.key !== key) {
      this.key = key;
      const copy = rows.cloneNode(false);
      for (const row of content) {
        if (this.session.provider === 'claude' && range.kind !== 'mentions' && !/^\s+(?:\/|…)\S+\s{2,}\S/u.test(row.textContent)) {
          if (copy.lastElementChild) {
            copy.lastElementChild.title += ' ' + row.textContent.trim();
            const span = copy.lastElementChild.lastElementChild;
            if (span && !span.textContent.endsWith('…')) span.textContent = span.textContent.trimEnd().replace(/.$/u, '…');
          }
          continue;
        }
        const clone = row.cloneNode(true); clone.title = row.textContent.trim(); copy.appendChild(clone);
      }
      this.owner.replaceChildren(copy);
    }
    this.panel.hidden = false;
  }
  dispose() { this.panel?.remove(); }
}
module.exports = { claudeCompletionRange, completionRange, CompletionLayout };
