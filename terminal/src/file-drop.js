const fs = require('node:fs');
const path = require('node:path');
const { fileURLToPath } = require('node:url');

function droppedPaths(transfer, { vaultRoot, vaultName, dragged, filePath, resolveLink }) {
  const candidates = [];
  const addVault = file => { if (typeof file?.path === 'string') candidates.push(path.join(vaultRoot, file.path)); };
  if (['file', 'folder', 'link'].includes(dragged?.type)) addVault(dragged.file);
  if (dragged?.type === 'files') (dragged.files || []).forEach(addVault);
  for (const file of Array.from(transfer?.files || [])) {
    try { const fullPath = filePath(file); if (fullPath) candidates.push(fullPath); } catch { /* Try the URI payload if the desktop cannot resolve a file. */ }
  }
  for (const type of ['text/uri-list', 'text/plain']) {
    for (let token of (transfer?.getData(type) || '').split(/\r?\n/)) {
      token = token.trim();
      if (!token || token.startsWith('#')) continue;
      try {
        if (token.startsWith('file://')) candidates.push(fileURLToPath(token));
        else if (token.startsWith('obsidian://')) {
          const url = new URL(token), vault = url.searchParams.get('vault'), file = url.searchParams.get('file');
          if ((!vault || vault === vaultName) && file) addVault(resolveLink(file));
        } else if (path.isAbsolute(token)) candidates.push(token);
        else {
          const link = token.match(/^!?\[\[([^\]|]+)(?:\|[^\]]*)?\]\]$/)?.[1] || token;
          addVault(resolveLink(link));
        }
      } catch { /* Ignore malformed links and keep the other files. */ }
    }
  }
  return [...new Set(candidates.filter(p => typeof p === 'string' && path.isAbsolute(p)).map(p => path.normalize(p)))];
}

function mergeAttachments(existing, paths, stat = fs.statSync) {
  const attachments = [...existing], rejected = [];
  for (const fullPath of paths) {
    if (attachments.some(a => a.path === fullPath)) continue;
    try {
      const info = stat(fullPath);
      if (!info.isFile() && !info.isDirectory()) throw Error('Unsupported file');
      if (attachments.length >= 12) { rejected.push(fullPath); continue; }
      attachments.push({ name: path.basename(fullPath), path: fullPath });
    } catch { rejected.push(fullPath); }
  }
  return { attachments, rejected };
}

function installFileDrop(view, getPathForFile) {
  view.disposeFileDrop?.();
  const root = view.root, doc = root.ownerDocument, listeners = [];
  let depth = 0;
  const reset = () => { depth = 0; root.classList.remove('dt-dragging'); };
  const context = () => ({
    vaultRoot: view.app.vault.adapter.getBasePath(), vaultName: view.app.vault.getName(),
    dragged: view.app.dragManager?.draggable,
    filePath: file => file.path || getPathForFile(file),
    resolveLink: link => view.app.vault.getAbstractFileByPath(link) || view.app.metadataCache.getFirstLinkpathDest(link, ''),
  });
  const accepts = event => {
    const types = Array.from(event.dataTransfer?.types || []);
    return types.includes('Files') || types.includes('text/uri-list') || !!context().dragged?.file || context().dragged?.type === 'files';
  };
  const on = (el, type, handler) => { el.addEventListener(type, handler, true); listeners.push(() => el.removeEventListener(type, handler, true)); };
  on(root, 'dragenter', event => { if (!accepts(event)) return; event.preventDefault(); event.stopPropagation(); depth++; root.classList.add('dt-dragging'); });
  on(root, 'dragover', event => { if (!accepts(event)) return; event.preventDefault(); event.stopPropagation(); event.dataTransfer.dropEffect = 'copy'; root.classList.add('dt-dragging'); });
  on(root, 'dragleave', event => { if (--depth <= 0 || !root.contains(event.relatedTarget)) reset(); });
  on(root, 'drop', event => {
    const paths = droppedPaths(event.dataTransfer, context()), handled = accepts(event) || paths.length;
    reset();
    if (!handled) return;
    event.preventDefault(); event.stopPropagation();
    const result = mergeAttachments(view.attachments, paths);
    view.attachments = result.attachments;
    view.renderAttachments(); view.saveLayout();
    view.errorEl.setText(!paths.length ? 'Could not find a local file in this drop.' : result.rejected.length ? 'Some files could not be attached. Check that they exist and that you have fewer than 12 attachments.' : '');
    if (!view.presentation?.state.native) view.input.focus();
  });
  on(doc, 'dragend', reset);
  view.disposeFileDrop = () => { listeners.forEach(remove => remove()); reset(); };
  return view.disposeFileDrop;
}
module.exports = { droppedPaths, mergeAttachments, installFileDrop };
