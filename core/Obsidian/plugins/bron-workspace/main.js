const { Plugin, Platform, setIcon, Modal, FuzzySuggestModal, Menu, Notice, TFolder, PluginSettingTab, Setting } = require('obsidian');

const USAGE_LOGOS = {"claude": "data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjQ4IiBoZWlnaHQ9IjI0OCIgdmlld0JveD0iMCAwIDI0OCAyNDgiIGZpbGw9Im5vbmUiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CjxwYXRoIGQ9Ik01Mi40Mjg1IDE2Mi44NzNMOTguNzg0NCAxMzYuODc5TDk5LjU0ODUgMTM0LjYwMkw5OC43ODQ0IDEzMy4zMzRIOTYuNDkyMUw4OC43MjM3IDEzMi44NjJMNjIuMjM0NiAxMzIuMTUzTDM5LjMxMTMgMTMxLjIwN0wxNy4wMjQ5IDEzMC4wMjZMMTEuNDIxNCAxMjguODQ0TDYuMiAxMjEuODczTDYuNzA5NCAxMTguNDQ3TDExLjQyMTQgMTE1LjI1N0wxOC4xNzEgMTE1Ljg0N0wzMy4wNzExIDExNi45MTFMNTUuNDg1IDExOC40NDdMNzEuNjU4NiAxMTkuMzkyTDk1LjcyOCAxMjEuODczSDk5LjU0ODVMMTAwLjA1OCAxMjAuMzM3TDk4Ljc4NDQgMTE5LjM5Mkw5Ny43NjU2IDExOC40NDdMNzQuNTg3NyAxMDIuNzMyTDQ5LjQ5OTUgODYuMTkwNUwzNi4zODIzIDc2LjYyTDI5LjM3NzkgNzEuNzc1N0wyNS44MTIxIDY3LjI4NThMMjQuMjgzOSA1Ny4zNjA4TDMwLjY1MTUgNTAuMjcxNkwzOS4zMTEzIDUwLjg2MjNMNDEuNDc2MyA1MS40NTMxTDUwLjI2MzYgNTguMTg3OUw2OC45ODQyIDcyLjcyMDlMOTMuNDM1NyA5MC42ODA0TDk3LjAwMTUgOTMuNjM0M0w5OC40Mzc0IDkyLjY2NTJMOTguNjU3MSA5MS45ODAxTDk3LjAwMTUgODkuMjYyNUw4My43NTcgNjUuMjc3Mkw2OS42MjEgNDAuODE5Mkw2My4yNTM0IDMwLjY1NzlMNjEuNTk3OCAyNC42MzJDNjAuOTU2NSAyMi4xMDMyIDYwLjU3OSAyMC4wMTExIDYwLjU3OSAxNy40MjQ2TDY3LjgzODEgNy40OTk2NUw3MS45MTMzIDYuMTk5OTVMODEuNzE5MyA3LjQ5OTY1TDg1Ljc5NDYgMTEuMDQ0M0w5MS45MDc0IDI0Ljk4NjVMMTAxLjcxNCA0Ni44NDUxTDExNi45OTYgNzYuNjJMMTIxLjQ1MyA4NS40ODE2TDEyMy44NzMgOTMuNjM0M0wxMjQuNzY0IDk2LjExNTVIMTI2LjI5MlY5NC42OTc2TDEyNy41NjYgNzcuOTE5N0wxMjkuODU4IDU3LjM2MDhMMTMyLjE1IDMwLjg5NDJMMTMyLjkxNSAyMy40NTA1TDEzNi42MDggMTQuNDcwOEwxNDMuOTk0IDkuNjI2NDNMMTQ5LjcyNSAxMi4zNDRMMTU0LjQzNyAxOS4wNzg4TDE1My44IDIzLjQ1MDVMMTUwLjk5OCA0MS42NDYzTDE0NS41MjIgNzAuMTIxNUwxNDEuOTU3IDg5LjI2MjVIMTQzLjk5NEwxNDYuNDE0IDg2Ljc4MTNMMTU2LjA5MyA3NC4wMjA2TDE3Mi4yNjYgNTMuNjk4TDE3OS4zOTggNDUuNjYzNUwxODcuODAzIDM2LjgwMkwxOTMuMTUyIDMyLjU0ODRIMjAzLjM0TDIxMC43MjYgNDMuNjU0OUwyMDcuNDE1IDU1LjExNTlMMTk2Ljk3MiA2OC4zNDkyTDE4OC4zMTIgNzkuNTczOUwxNzUuODk2IDk2LjIwOTVMMTY4LjE5MSAxMDkuNTg1TDE2OC44ODIgMTEwLjY4OUwxNzAuNzM4IDExMC41M0wxOTguNzU1IDEwNC41MDRMMjEzLjkxIDEwMS43ODdMMjMxLjk5NCA5OC43MTQ5TDI0MC4xNDQgMTAyLjQ5NkwyNDEuMDM2IDEwNi4zOTVMMjM3Ljg1MiAxMTQuMzExTDIxOC40OTUgMTE5LjAzN0wxOTUuODI2IDEyMy42NDVMMTYyLjA3IDEzMS41OTJMMTYxLjY5NiAxMzEuODkzTDE2Mi4xMzcgMTMyLjU0N0wxNzcuMzYgMTMzLjkyNUwxODMuODU1IDEzNC4yNzlIMTk5Ljc3NEwyMjkuNDQ3IDEzNi41MjRMMjM3LjIxNSAxNDEuNjA1TDI0MS44IDE0Ny44NjdMMjQxLjAzNiAxNTIuNzExTDIyOS4wNjUgMTU4LjczN0wyMTMuMDE5IDE1NC45NTZMMTc1LjQ1IDE0NS45NzdMMTYyLjU4NyAxNDIuNzg3SDE2MC44MDVWMTQzLjg1TDE3MS41MDIgMTU0LjM2NkwxOTEuMjQyIDE3Mi4wODlMMjE1LjgyIDE5NS4wMTFMMjE3LjA5NCAyMDAuNjgyTDIxMy45MSAyMDUuMTcyTDIxMC41OTkgMjA0LjY5OUwxODguOTQ5IDE4OC4zOTRMMTgwLjU0NCAxODEuMDY5TDE2MS42OTYgMTY1LjExOEgxNjAuNDIyVjE2Ni43NzJMMTY0Ljc1MiAxNzMuMTUyTDE4Ny44MDMgMjA3Ljc3MUwxODguOTQ5IDIxOC40MDVMMTg3LjI5NCAyMjEuODMyTDE4MS4zMDggMjIzLjk1OUwxNzQuODEzIDIyMi43NzdMMTYxLjE4NyAyMDMuNzU0TDE0Ny4zMDUgMTgyLjQ4NkwxMzYuMDk4IDE2My4zNDVMMTM0Ljc0NSAxNjQuMkwxMjguMDc1IDIzNS40MkwxMjUuMDE5IDIzOS4wODJMMTE3Ljg4NyAyNDEuOEwxMTEuOTAyIDIzNy4zMUwxMDguNzE4IDIyOS45ODRMMTExLjkwMiAyMTUuNDUyTDExNS43MjIgMTk2LjU0N0wxMTguNzc5IDE4MS41NDFMMTIxLjU4IDE2Mi44NzNMMTIzLjI5MSAxNTYuNjM2TDEyMy4xNCAxNTYuMjE5TDEyMS43NzMgMTU2LjQ0OUwxMDcuNjk5IDE3NS43NTJMODYuMzA0IDIwNC42OTlMNjkuMzY2MyAyMjIuNzc3TDY1LjI5MSAyMjQuNDMxTDU4LjI4NjcgMjIwLjc2OEw1OC45MjM1IDIxNC4yN0w2Mi44NzEzIDIwOC40OEw4Ni4zMDQgMTc4LjcwNUwxMDAuNDQgMTYwLjE1NUwxMDkuNTUxIDE0OS41MDdMMTA5LjQ2MiAxNDcuOTY3TDEwOC45NTkgMTQ3LjkyNEw0Ni42OTc3IDE4OC41MTJMMzUuNjE4MiAxODkuOTNMMzAuNzc4OCAxODUuNDRMMzEuNDE1NiAxNzguMTE1TDMzLjcwNzkgMTc1Ljc1Mkw1Mi40Mjg1IDE2Mi44NzNaIiBmaWxsPSIjRDk3NzU3Ii8+Cjwvc3ZnPgo=", "codex": "data:image/png;base64,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"};

class SectionStore {
  constructor(data, persist, changed = () => {}, makeId = () => crypto.randomUUID()) {
    this.persist = persist;
    this.changed = changed;
    this.makeId = makeId;
    this.pending = Promise.resolve();
    if (data == null) data = { version: 1, sections: [{ id: makeId(), name: 'Favorites', collapsed: false, items: [] }] };
    if (data.version !== 1 || !Array.isArray(data.sections)) throw new Error('Unsupported sidebar section data. Your saved data has not been changed.');
    const ids = new Set();
    this.data = { version: 1, usageEnabled: data.usageEnabled !== false, sections: data.sections.map(s => {
      if (!s || typeof s.id !== 'string' || !s.id || ids.has(s.id) || typeof s.name !== 'string' || !s.name.trim() || !Array.isArray(s.items) || s.items.some(p => typeof p !== 'string' || !p)) throw new Error('Invalid sidebar section data. Your saved data has not been changed.');
      ids.add(s.id);
      return { id: s.id, name: s.name, collapsed: !!s.collapsed, items: [...new Set(s.items)] };
    }) };
  }

  setUsageEnabled(enabled) { return this.commit(data => { data.usageEnabled = !!enabled; }); }

  snapshot() { return JSON.parse(JSON.stringify(this.data)); }
  section(data, id) {
    const section = data.sections.find(s => s.id === id);
    if (!section) throw new Error('This section no longer exists.');
    return section;
  }
  name(value) {
    const name = String(value).trim();
    if (!name || name.length > 60) throw new Error('Use a section name between 1 and 60 characters.');
    return name;
  }
  commit(change) {
    const operation = this.pending.then(async () => {
      const next = this.snapshot();
      const result = change(next);
      if (JSON.stringify(next) !== JSON.stringify(this.data)) {
        await this.persist(next);
        this.data = next;
        this.changed();
      }
      return result;
    });
    this.pending = operation.catch(() => {});
    return operation;
  }
  addSection(value) {
    return this.commit(data => {
      const name = this.name(value);
      if (data.sections.some(s => s.name.toLowerCase() === name.toLowerCase())) throw new Error('A section with this name already exists.');
      const id = this.makeId();
      data.sections.push({ id, name, collapsed: false, items: [] });
      return { id };
    });
  }
  renameSection(id, value) {
    return this.commit(data => {
      const name = this.name(value);
      if (data.sections.some(s => s.id !== id && s.name.toLowerCase() === name.toLowerCase())) throw new Error('A section with this name already exists.');
      this.section(data, id).name = name;
    });
  }
  removeSection(id) { return this.commit(data => { this.section(data, id); data.sections = data.sections.filter(s => s.id !== id); }); }
  toggleSection(id) { return this.commit(data => { const s = this.section(data, id); s.collapsed = !s.collapsed; }); }
  reorderSection(id, beforeId = null) {
    return this.commit(data => {
      if (id === beforeId) return;
      const s = this.section(data, id);
      if (beforeId !== null) this.section(data, beforeId);
      data.sections = data.sections.filter(s => s.id !== id);
      const index = beforeId === null ? data.sections.length : data.sections.findIndex(s => s.id === beforeId);
      data.sections.splice(index, 0, s);
    });
  }
  moveSection(id, delta) {
    return this.commit(data => {
      this.section(data, id);
      const index = data.sections.findIndex(s => s.id === id);
      const target = Math.max(0, Math.min(data.sections.length - 1, index + delta));
      const [section] = data.sections.splice(index, 1);
      data.sections.splice(target, 0, section);
    });
  }
  addItems(id, paths, beforePath = null) {
    return this.commit(data => {
      const s = this.section(data, id);
      const added = [...new Set(paths.filter(p => typeof p === 'string' && p && !s.items.includes(p)))];
      const index = beforePath === null ? s.items.length : s.items.indexOf(beforePath);
      s.items.splice(index < 0 ? s.items.length : index, 0, ...added);
      s.collapsed = false;
      return { added: added.length };
    });
  }
  removeItem(id, path) { return this.commit(data => { const s = this.section(data, id); s.items = s.items.filter(p => p !== path); }); }
  transferItem(sourceId, targetId, path, beforePath = null) {
    return this.commit(data => {
      const source = this.section(data, sourceId), target = this.section(data, targetId);
      if (!source.items.includes(path)) throw new Error('This shortcut no longer exists.');
      if (sourceId === targetId && path === beforePath) return;
      source.items = source.items.filter(p => p !== path);
      target.items = target.items.filter(p => p !== path);
      const index = beforePath === null ? target.items.length : target.items.indexOf(beforePath);
      target.items.splice(index < 0 ? target.items.length : index, 0, path);
      target.collapsed = false;
    });
  }
  moveItem(id, path, delta) {
    return this.commit(data => {
      const s = this.section(data, id), index = s.items.indexOf(path);
      if (index < 0) return;
      const target = Math.max(0, Math.min(s.items.length - 1, index + delta));
      s.items.splice(index, 1);
      s.items.splice(target, 0, path);
    });
  }
  renamePath(oldPath, newPath) {
    return this.commit(data => {
      for (const s of data.sections) s.items = [...new Set(s.items.map(p => p === oldPath ? newPath : p.startsWith(oldPath + '/') ? newPath + p.slice(oldPath.length) : p))];
    });
  }
  deletePath(path) {
    return this.commit(data => {
      for (const s of data.sections) s.items = s.items.filter(p => p !== path && !p.startsWith(path + '/'));
    });
  }
}


const ACTIONS = [
  { id: 'graph:open', label: 'Open graph view', icon: 'git-fork' },
  { id: 'termy:open-terminal', label: 'Open terminal', icon: 'terminal-square' },
  { id: 'bron-terminal:open', label: 'Open Bron Terminal', icon: 'terminal-square' },
  { id: 'command-palette:open', label: 'Open command palette', icon: 'command' },
];

class SidebarActions {
  constructor(app) {
    this.app = app;
    this.element = null;
  }

  refresh() {
    const header = document.querySelector('.mod-left-split .workspace-tabs > .workspace-tab-header-container');
    if (Platform.isMobile || this.app.customCss.theme !== 'Bron' || !header) {
      this.remove();
      return;
    }
    if (!this.element) {
      this.element = document.createElement('div');
      this.element.className = 'bron-sidebar-actions';
      this.element.setAttribute('role', 'group');
      this.element.setAttribute('aria-label', 'Workspace shortcuts');
      for (const action of ACTIONS) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'clickable-icon';
        button.dataset.command = action.id;
        button.setAttribute('aria-label', action.label);
        button.setAttribute('title', action.label);
        setIcon(button, action.icon);
        button.addEventListener('click', () => this.app.commands.executeCommandById(action.id));
        this.element.append(button);
      }
    }
    if (header.nextElementSibling !== this.element) header.after(this.element);
    const available = new Set(this.app.commands.listCommands().map(command => command.id));
    for (const button of this.element.children) button.disabled = !available.has(button.dataset.command);
    document.body.classList.add('bron-toolbar-ready');
  }

  remove() {
    this.element?.remove();
    this.element = null;
    document.body.classList.remove('bron-toolbar-ready');
  }
}



const SECTION_DRAG = 'application/x-bron-section';
const ITEM_DRAG = 'application/x-bron-shortcut';

function sectionElement(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== undefined) el.textContent = text;
  return el;
}
function sectionButton(label, icon, action, className = '') {
  const button = sectionElement('button', 'bron-section-icon-button ' + className);
  button.type = 'button';
  button.setAttribute('aria-label', label);
  button.title = label;
  setIcon(button, icon);
  button.addEventListener('click', event => { event.stopPropagation(); action(event); });
  return button;
}

class SectionNameModal extends Modal {
  constructor(app, name, save) { super(app); this.name = name; this.save = save; }
  onOpen() {
    this.titleEl.textContent = this.name ? 'Rename section' : 'New section';
    this.contentEl.classList.add('bron-section-dialog');
    const form = sectionElement('form');
    const label = sectionElement('label', '', 'Section name');
    const input = sectionElement('input');
    input.type = 'text'; input.maxLength = 60; input.placeholder = 'e.g. Projects'; input.value = this.name;
    label.append(input);
    const error = sectionElement('div', 'bron-section-error'); error.setAttribute('role', 'alert');
    const controls = sectionElement('div', 'bron-section-dialog-actions');
    const cancel = sectionElement('button', '', 'Cancel'); cancel.type = 'button'; cancel.onclick = () => this.close();
    const submit = sectionElement('button', 'mod-cta', this.name ? 'Save' : 'Create section'); submit.type = 'submit';
    controls.append(cancel, submit); form.append(label, error, controls); this.contentEl.append(form);
    form.onsubmit = async event => {
      event.preventDefault(); submit.disabled = true;
      try { await this.save(input.value); this.close(); }
      catch (e) { error.textContent = e.message; submit.disabled = false; }
    };
    window.setTimeout(() => { if (input.isConnected) { input.focus(); input.select(); } }, 50);
  }
  onClose() { this.contentEl.replaceChildren(); }
}

class SectionItemPicker extends FuzzySuggestModal {
  constructor(app, section, choose) {
    super(app); this.section = section; this.choose = choose;
    this.setPlaceholder('Add a file or folder to ' + section.name);
  }
  getItems() { return this.app.vault.getAllLoadedFiles().filter(f => f.path && f.path !== '/' && !this.section.items.includes(f.path)); }
  getItemText(file) { return file.path; }
  onChooseItem(file) { this.choose(file); }
}

class SidebarSections {
  constructor(plugin) { this.plugin = plugin; this.app = plugin.app; this.store = plugin.store; this.element = null; this.filesLabel = null; this.signature = ''; }
  run(promise) { return promise.catch(error => { new Notice('Could not save sidebar sections: ' + error.message); }); }
  createSection() { new SectionNameModal(this.app, '', name => this.store.addSection(name)).open(); }
  addItem(section) { new SectionItemPicker(this.app, section, file => this.run(this.store.addItems(section.id, [file.path]))).open(); }
  refresh() {
    const files = document.querySelector('.mod-left-split .workspace-leaf-content[data-type="file-explorer"] .nav-files-container');
    if (Platform.isMobile || this.app.customCss.theme !== 'Bron' || !files) { this.remove(); return; }
    if (!this.element) {
      this.element = sectionElement('div', 'bron-sections');
      this.element.setAttribute('role', 'region'); this.element.setAttribute('aria-label', 'Sidebar sections');
      this.filesLabel = sectionElement('div', 'bron-files-label', 'Files');
      this.signature = '';
    }
    if (this.filesLabel.nextElementSibling !== files) files.before(this.element, this.filesLabel);
    const signature = JSON.stringify(this.store.data);
    if (signature !== this.signature) { this.signature = signature; this.render(); }
    this.updateActive();
  }
  remove() { this.openMenu?.hide(); this.openMenu = null; this.element?.remove(); this.filesLabel?.remove(); this.element = null; this.filesLabel = null; this.signature = ''; }
  render() {
    const focused = this.element.contains(document.activeElement) ? document.activeElement.dataset.focusKey : null;
    const scroll = this.element.scrollTop;
    this.element.replaceChildren();
    const heading = sectionElement('div', 'bron-sections-heading');
    heading.append(sectionElement('span', '', 'Sections'));
    const add = sectionButton('Add section', 'plus', () => this.createSection()); add.dataset.focusKey = 'new'; heading.append(add);
    this.element.append(heading);
    const sections = this.store.snapshot().sections;
    if (!sections.length) {
      const empty = sectionElement('button', 'bron-section-empty', 'Create your first section');
      empty.type = 'button'; empty.onclick = () => this.createSection(); this.element.append(empty);
    }
    for (const section of sections) {
      const group = sectionElement('section', 'bron-section'); group.dataset.sectionId = section.id;
      const header = sectionElement('div', 'bron-section-header'); header.draggable = true;
      const toggle = sectionElement('button', 'bron-section-toggle'); toggle.type = 'button';
      toggle.dataset.focusKey = 'toggle:' + section.id;
      toggle.setAttribute('aria-expanded', String(!section.collapsed)); toggle.setAttribute('aria-controls', 'bron-section-' + section.id);
      const chevron = sectionElement('span', 'bron-section-chevron'); setIcon(chevron, section.collapsed ? 'chevron-right' : 'chevron-down');
      toggle.append(chevron, sectionElement('span', 'bron-section-name', section.name));
      toggle.onclick = () => this.run(this.store.toggleSection(section.id));
      const more = sectionButton('Manage ' + section.name, 'ellipsis', event => this.sectionMenu(section, event), 'bron-section-more'); more.dataset.focusKey = 'menu:' + section.id;
      header.append(toggle, more); group.append(header);
      header.addEventListener('contextmenu', event => { event.preventDefault(); this.sectionMenu(section, event); });
      header.addEventListener('dragstart', event => {
        event.stopPropagation(); event.dataTransfer.setData(SECTION_DRAG, section.id); event.dataTransfer.effectAllowed = 'move';
      });
      const items = sectionElement('div', 'bron-section-items'); items.id = 'bron-section-' + section.id; items.hidden = section.collapsed;
      for (const path of section.items) items.append(this.itemRow(section, path));
      if (!section.items.length) {
        const empty = sectionElement('button', 'bron-section-empty', 'Drop here or add a file'); empty.type = 'button';
        empty.onclick = () => this.addItem(section); items.append(empty);
      }
      group.append(items); this.bindDrop(group, section); this.element.append(group);
    }
    this.element.scrollTop = scroll;
    if (focused) [...this.element.querySelectorAll('[data-focus-key]')].find(e => e.dataset.focusKey === focused)?.focus({ preventScroll: true });
  }
  sectionMenu(section, event) {
    const menu = new Menu();
    const index = this.store.data.sections.findIndex(s => s.id === section.id);
    menu.addItem(i => i.setTitle('Add file or folder').setIcon('plus').onClick(() => this.addItem(section)));
    menu.addItem(i => i.setTitle('Rename section').setIcon('pencil').onClick(() => new SectionNameModal(this.app, section.name, name => this.store.renameSection(section.id, name)).open()));
    menu.addSeparator();
    menu.addItem(i => i.setTitle('Move up').setIcon('arrow-up').setDisabled(index === 0).onClick(() => this.run(this.store.moveSection(section.id, -1))));
    menu.addItem(i => i.setTitle('Move down').setIcon('arrow-down').setDisabled(index === this.store.data.sections.length - 1).onClick(() => this.run(this.store.moveSection(section.id, 1))));
    menu.addSeparator();
    menu.addItem(i => i.setTitle('Remove section').setIcon('trash-2').onClick(() => this.run(this.store.removeSection(section.id))));
    this.showMenu(menu, event);
  }
  showMenu(menu, event) {
    this.openMenu?.hide();
    this.openMenu = menu;
    menu.setUseNativeMenu?.(false);
    if (event.clientX || event.clientY) menu.showAtMouseEvent(event);
    else { const r = event.currentTarget.getBoundingClientRect(); menu.showAtPosition({ x: r.left, y: r.bottom }); }
  }
  itemRow(section, path) {
    const file = this.app.vault.getAbstractFileByPath(path);
    const folder = file instanceof TFolder;
    const row = sectionElement('div', 'bron-section-item' + (file ? '' : ' is-missing'));
    row.dataset.path = path; row.dataset.sectionId = section.id; row.draggable = true;
    const open = sectionElement('button', 'bron-section-open'); open.type = 'button'; open.title = path + (file ? '' : ' (not found)');
    open.dataset.focusKey = 'item:' + section.id + ':' + path;
    const label = file ? (folder ? file.name : file.basename || file.name) : path.split('/').pop();
    const icon = sectionElement('span', 'bron-section-file-icon'); icon.setAttribute('aria-hidden', 'true');
    const [symbol, color] = this.fileIcon(file, path);
    icon.style.setProperty('--bron-section-symbol', 'var(--bron-icon-' + symbol + ')');
    icon.style.setProperty('--bron-section-color', color);
    open.append(icon, sectionElement('span', 'bron-section-item-name', label));
    open.onclick = event => this.openPath(path, event);
    open.addEventListener('auxclick', event => { if (event.button === 1) { event.preventDefault(); this.openPath(path, { ctrlKey: true }); } });
    const more = sectionButton('Manage shortcut to ' + label, 'ellipsis', event => this.itemMenu(section, path, event), 'bron-section-more'); more.dataset.focusKey = 'item-menu:' + section.id + ':' + path;
    row.append(open, more);
    row.addEventListener('contextmenu', event => { event.preventDefault(); this.itemMenu(section, path, event); });
    row.addEventListener('dragstart', event => {
      event.stopPropagation(); event.dataTransfer.setData(ITEM_DRAG, JSON.stringify({ sectionId: section.id, path })); event.dataTransfer.effectAllowed = 'move';
    });
    this.bindDrop(row, section, path);
    return row;
  }
  fileIcon(file, path) {
    if (file instanceof TFolder) return ['folder', 'var(--bron-folder)'];
    const ext = path.split('.').pop().toLowerCase();
    const icons = {
      md:['note','blue'],canvas:['canvas','purple'],base:['database','cyan'],pdf:['pdf','red'],
      xlsx:['spreadsheet','green'],xls:['spreadsheet','green'],csv:['table','green'],tsv:['table','green'],
      docx:['document','blue'],doc:['document','blue'],txt:['text','muted'],pptx:['presentation','orange'],
      png:['image','purple'],jpg:['image','purple'],jpeg:['image','purple'],webp:['image','purple'],gif:['image','purple'],svg:['vector','pink'],
      mp3:['audio','pink'],wav:['audio','pink'],mp4:['video','purple'],mov:['video','purple'],
      js:['javascript','yellow'],ts:['typescript','blue'],py:['python','cyan'],css:['stylesheet','blue'],
      json:['config','orange'],yaml:['config','orange'],yml:['config','orange'],zip:['archive','yellow'],epub:['book','orange'],
    };
    const [symbol, color] = icons[ext] || ['file', 'muted'];
    return [symbol, color === 'muted' ? 'var(--bron-muted)' : 'var(--color-' + color + ')'];
  }
  openPath(path, event) {
    const file = this.app.vault.getAbstractFileByPath(path);
    if (!file) { new Notice('This file or folder could not be found.'); return; }
    if (file instanceof TFolder) {
      const view = this.app.workspace.getLeavesOfType('file-explorer')[0]?.view;
      const item = view?.fileItems?.[path];
      if (item?.collapsed) item.toggleCollapsed(false);
      view?.revealInFolder(file);
    } else {
      this.app.workspace.getLeaf(event.ctrlKey || event.metaKey ? 'tab' : false).openFile(file).catch(error => new Notice(error.message));
    }
  }
  itemMenu(section, path, event) {
    const menu = new Menu(); const index = section.items.indexOf(path);
    menu.addItem(i => i.setTitle('Open').setIcon('arrow-up-right').onClick(() => this.openPath(path, {})));
    menu.addItem(i => i.setTitle('Move up').setIcon('arrow-up').setDisabled(index === 0).onClick(() => this.run(this.store.moveItem(section.id, path, -1))));
    menu.addItem(i => i.setTitle('Move down').setIcon('arrow-down').setDisabled(index === section.items.length - 1).onClick(() => this.run(this.store.moveItem(section.id, path, 1))));
    menu.addSeparator();
    menu.addItem(i => i.setTitle('Remove from section').setIcon('x').onClick(() => this.run(this.store.removeItem(section.id, path))));
    this.showMenu(menu, event);
  }
  dragKind(event) {
    const types = [...(event.dataTransfer?.types || [])];
    if (types.includes(SECTION_DRAG)) return 'section';
    if (types.includes(ITEM_DRAG)) return 'item';
    const drag = this.app.dragManager?.draggable;
    if (drag && ['file', 'files', 'folder'].includes(drag.type)) return 'native';
    return null;
  }
  bindDrop(element, section, beforePath = null) {
    element.addEventListener('dragover', event => {
      const kind = this.dragKind(event); if (!kind || (kind === 'section' && beforePath !== null)) return;
      event.preventDefault(); event.stopPropagation(); event.dataTransfer.dropEffect = kind === 'native' ? 'copy' : 'move';
      this.element.querySelectorAll('.is-drop-target').forEach(e => { if (e !== element) e.classList.remove('is-drop-target'); });
      element.classList.add('is-drop-target');
      if (kind === 'native') this.app.dragManager.setAction('Add to ' + section.name);
    });
    element.addEventListener('dragleave', event => { if (!element.contains(event.relatedTarget)) element.classList.remove('is-drop-target'); });
    element.addEventListener('drop', event => {
      const kind = this.dragKind(event); if (!kind || (kind === 'section' && beforePath !== null)) return;
      event.preventDefault(); event.stopPropagation(); element.classList.remove('is-drop-target');
      try {
        if (kind === 'section') {
          const sections = this.store.data.sections;
          const index = sections.findIndex(s => s.id === section.id);
          const header = element.querySelector('.bron-section-header').getBoundingClientRect();
          const beforeId = event.clientY > header.top + header.height / 2 ? sections[index + 1]?.id || null : section.id;
          this.run(this.store.reorderSection(event.dataTransfer.getData(SECTION_DRAG), beforeId));
        }
        else if (kind === 'item') {
          const item = JSON.parse(event.dataTransfer.getData(ITEM_DRAG));
          this.run(this.store.transferItem(item.sectionId, section.id, item.path, beforePath));
        } else {
          const drag = this.app.dragManager.draggable;
          const files = drag.type === 'files' ? drag.files : [drag.file];
          const paths = files.filter(f => f?.path && f.path !== '/' && this.app.vault.getAbstractFileByPath(f.path)).map(f => f.path);
          this.run(this.store.addItems(section.id, paths, beforePath));
        }
      } catch (error) { new Notice('Could not add this shortcut: ' + error.message); }
    });
  }
  updateActive() {
    const active = this.app.workspace.getActiveFile()?.path;
    this.element?.querySelectorAll('.bron-section-item').forEach(row => {
      const selected = row.dataset.path === active; row.classList.toggle('is-active', selected);
      const button = row.querySelector('.bron-section-open');
      if (selected) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current');
    });
  }
}


class UsageError extends Error {
  constructor(code) { super(code); this.code = code; }
}
const USAGE_ERRORS = {
  AUTH: 'Sign in again', MISSING: 'Codex not found', LOCKED: 'Sign-in unavailable',
  TIMEOUT: 'Connection timed out', OFFLINE: 'Could not refresh', LIMITED: 'Try again later',
  INVALID: 'Usage unavailable', CANCELLED: 'Refresh cancelled',
};
function usageWindow(label, used, reset, minutes) {
  if (typeof used !== 'number' || !Number.isFinite(used) || used < 0) return null;
  const parsed = typeof reset === 'number' ? reset * 1000 : Date.parse(reset);
  return { label, used, resetsAt: Number.isFinite(parsed) ? parsed : null, minutes };
}
function durationLabel(minutes) {
  if (minutes === 10080) return 'Weekly';
  if (minutes === 300) return 'Session';
  if (!Number.isFinite(minutes) || minutes <= 0) return 'Usage';
  if (minutes % 1440 === 0) return minutes / 1440 + '-day';
  if (minutes % 60 === 0) return minutes / 60 + '-hour';
  return minutes + '-min';
}
function normalizeCodexUsage(result) {
  if (!result || typeof result !== 'object') throw new UsageError('INVALID');
  const main = result.rateLimitsByLimitId?.codex || result.rateLimits;
  if (!main || typeof main !== 'object') throw new UsageError('INVALID');
  const windows = [];
  const buckets = result.rateLimitsByLimitId && Object.keys(result.rateLimitsByLimitId).length ? Object.values(result.rateLimitsByLimitId) : [main];
  for (const bucket of buckets) {
    if (!bucket || typeof bucket !== 'object') continue;
    const prefix = bucket.limitId && bucket.limitId !== 'codex' ? (bucket.limitName || bucket.limitId) + ' · ' : '';
    for (const window of [bucket.primary, bucket.secondary]) {
      if (!window) continue;
      const normalized = usageWindow(prefix + durationLabel(window.windowDurationMins), window.usedPercent, window.resetsAt, window.windowDurationMins);
      if (normalized) windows.push(normalized);
    }
  }
  const balance = main.credits?.balance;
  const numericBalance = typeof balance === 'number' || typeof balance === 'string' && balance.trim() ? Number(balance) : NaN;
  return { windows, credits: main.credits?.hasCredits && !main.credits.unlimited && Number.isFinite(numericBalance) ? Math.max(0, numericBalance) : null, unlimited: main.credits?.unlimited === true };
}
function normalizeClaudeUsage(result) {
  if (!result || typeof result !== 'object' || !('five_hour' in result || 'seven_day' in result)) throw new UsageError('INVALID');
  const windows = [];
  for (const [key, label, minutes] of [['five_hour','Session',300],['seven_day','Weekly',10080],['seven_day_sonnet','Sonnet · week',10080],['seven_day_opus','Opus · week',10080]]) {
    const raw = result[key]; if (!raw) continue;
    const window = usageWindow(label, raw.utilization, raw.resets_at, minutes);
    if (window) windows.push(window);
  }
  if (result.extra_usage?.is_enabled && typeof result.extra_usage.utilization === 'number') {
    const extra = usageWindow('Extra usage', result.extra_usage.utilization, null, null);
    if (extra) windows.push(extra);
  }
  return { windows, credits: null, unlimited: false };
}
async function findCodexBinary() {
  const fs = require('fs').promises, path = require('path'), os = require('os');
  const candidates = [path.join(os.homedir(), '.local/bin/codex'), '/opt/homebrew/bin/codex', '/usr/local/bin/codex', ...(process.env.PATH || '').split(path.delimiter).filter(Boolean).map(dir => path.join(dir, 'codex'))];
  for (const candidate of [...new Set(candidates)]) {
    try { await fs.access(candidate, require('fs').constants.X_OK); return candidate; } catch {}
  }
  throw new UsageError('MISSING');
}
async function readCodexUsage(signal) {
  const executable = await findCodexBinary();
  if (signal.aborted) throw new UsageError('CANCELLED');
  return new Promise((resolve, reject) => {
    let processHandle, buffer = '', complete = false;
    const finish = (error, result) => {
      if (complete) return; complete = true;
      clearTimeout(timer); signal.removeEventListener('abort', cancel);
      processHandle?.stdin?.end(); processHandle?.kill();
      error ? reject(error) : resolve(result);
    };
    const cancel = () => finish(new UsageError('CANCELLED'));
    const timer = setTimeout(() => finish(new UsageError('TIMEOUT')), 20000);
    signal.addEventListener('abort', cancel, { once: true });
    try {
      processHandle = require('child_process').spawn(executable, ['app-server', '--listen', 'stdio://'], { cwd: require('os').homedir(), stdio: ['pipe','pipe','ignore'], windowsHide: true });
      processHandle.on('error', () => finish(new UsageError('MISSING')));
      processHandle.on('exit', () => { if (!complete) finish(new UsageError('OFFLINE')); });
      processHandle.stdin.on('error', () => finish(new UsageError('OFFLINE')));
      const send = message => { if (!complete) processHandle.stdin.write(JSON.stringify(message) + '\n'); };
      processHandle.stdout.setEncoding('utf8');
      processHandle.stdout.on('data', chunk => {
        buffer += chunk;
        if (buffer.length > 1024 * 1024) { finish(new UsageError('INVALID')); return; }
        let end;
        while (!complete && (end = buffer.indexOf('\n')) !== -1) {
          const line = buffer.slice(0, end); buffer = buffer.slice(end + 1);
          let message; try { message = JSON.parse(line); } catch { continue; }
          if (message.id === 1) {
            if (message.error) { finish(new UsageError('OFFLINE')); return; }
            send({ method: 'initialized', params: {} });
            send({ id: 2, method: 'account/rateLimits/read' });
          } else if (message.id === 2) {
            if (message.error) {
              const auth = /auth|login|sign.?in|401|unauthorized/i.test(message.error.message || '');
              finish(new UsageError(auth ? 'AUTH' : 'OFFLINE')); return;
            }
            try { finish(null, normalizeCodexUsage(message.result)); } catch (error) { finish(error); }
          }
        }
      });
      send({ id: 1, method: 'initialize', params: { clientInfo: { name: 'bron_obsidian_usage', title: 'Bron Usage', version: '1.0.0' } } });
    } catch { finish(new UsageError('OFFLINE')); }
  });
}
async function readClaudeCredential(signal) {
  if (signal.aborted) throw new UsageError('CANCELLED');
  if (process.platform === 'darwin') {
    return new Promise((resolve, reject) => {
      const child = require('child_process').execFile('/usr/bin/security', ['find-generic-password', '-s', 'Claude Code-credentials', '-w'], { timeout: 10000, maxBuffer: 128 * 1024 }, (error, stdout) => {
        signal.removeEventListener('abort', cancel);
        if (signal.aborted) { reject(new UsageError('CANCELLED')); return; }
        if (error) { reject(new UsageError('LOCKED')); return; }
        try { resolve(JSON.parse(stdout).claudeAiOauth); } catch { reject(new UsageError('AUTH')); }
      });
      const cancel = () => child.kill(); signal.addEventListener('abort', cancel, { once: true });
    });
  }
  try {
    const path = require('path'), os = require('os');
    const dir = process.env.CLAUDE_CONFIG_DIR || path.join(os.homedir(), '.claude');
    return JSON.parse(await require('fs').promises.readFile(path.join(dir, '.credentials.json'), 'utf8')).claudeAiOauth;
  } catch { throw new UsageError('AUTH'); }
}
async function readClaudeUsage(signal) {
  const credential = await readClaudeCredential(signal);
  if (!credential || typeof credential.accessToken !== 'string' || !credential.accessToken) throw new UsageError('AUTH');
  if (signal.aborted) throw new UsageError('CANCELLED');
  return new Promise((resolve, reject) => {
    let complete = false, request;
    const finish = (error, result) => {
      if (complete) return; complete = true; signal.removeEventListener('abort', cancel);
      error ? reject(error) : resolve(result);
    };
    const cancel = () => { request?.destroy(); finish(new UsageError('CANCELLED')); };
    signal.addEventListener('abort', cancel, { once: true });
    request = require('https').get('https://api.anthropic.com/api/oauth/usage', {
      headers: { Authorization: 'Bearer ' + credential.accessToken, 'anthropic-beta': 'oauth-2025-04-20', 'User-Agent': 'Bron-Obsidian-Usage/1.0' }, timeout: 15000,
    }, response => {
      if (response.statusCode !== 200) {
        response.resume(); finish(new UsageError(response.statusCode === 401 || response.statusCode === 403 ? 'AUTH' : response.statusCode === 429 ? 'LIMITED' : 'OFFLINE')); return;
      }
      let buffer = ''; response.setEncoding('utf8');
      response.on('data', chunk => {
        buffer += chunk;
        if (buffer.length > 128 * 1024) { request.destroy(); finish(new UsageError('INVALID')); }
      });
      response.on('error', () => finish(new UsageError('OFFLINE')));
      response.on('end', () => {
        try { finish(null, normalizeClaudeUsage(JSON.parse(buffer))); } catch { finish(new UsageError('INVALID')); }
      });
    });
    request.on('timeout', () => { request.destroy(); finish(new UsageError('TIMEOUT')); });
    request.on('error', () => finish(new UsageError('OFFLINE')));
  });
}
function usageResetText(timestamp, now = Date.now()) {
  if (!Number.isFinite(timestamp)) return '';
  const minutes = Math.ceil((timestamp - now) / 60000);
  if (minutes <= 0) return 'Reset due';
  if (minutes >= 1440) return 'Resets in ' + Math.floor(minutes / 1440) + 'd ' + Math.floor(minutes % 1440 / 60) + 'h';
  if (minutes >= 60) return 'Resets in ' + Math.floor(minutes / 60) + 'h ' + minutes % 60 + 'm';
  return 'Resets in ' + minutes + 'm';
}


const USAGE_POLL_MS = 5 * 60 * 1000;
const USAGE_PROVIDERS = [
  { id: 'claude', name: 'Claude Code', read: readClaudeUsage, logo: 'claude', url: 'https://claude.ai/settings/usage' },
  { id: 'codex', name: 'Codex', read: readCodexUsage, logo: 'codex', url: 'https://chatgpt.com/codex/settings/usage' },
];
class SidebarUsage {
  constructor(plugin) {
    this.plugin = plugin; this.app = plugin.app; this.element = null; this.active = false; this.disposed = false;
    this.states = Object.fromEntries(USAGE_PROVIDERS.map(p => [p.id, { data: null, updatedAt: null, error: null }]));
    this.refreshPromise = null; this.controller = null;
    this.poll = window.setInterval(() => { if (this.active && !document.hidden) this.refresh(); }, USAGE_POLL_MS);
    this.clock = window.setInterval(() => { if (this.active && !document.hidden) this.render(); }, 60000);
  }
  sync() {
    if (this.disposed) return;
    const profile = document.querySelector('.mod-left-split > .workspace-sidedock-vault-profile');
    const enabled = this.plugin.store?.data.usageEnabled !== false;
    const mount = enabled && !Platform.isMobile && this.app.customCss.theme === 'Bron' && profile;
    if (!mount) { this.active = false; this.controller?.abort(); this.element?.remove(); this.element = null; return; }
    if (!this.element) {
      this.element = sectionElement('section', 'bron-ai-usage');
      this.element.setAttribute('aria-label', 'AI usage');
      profile.before(this.element); this.render();
    } else if (this.element.nextElementSibling !== profile) profile.before(this.element);
    const active = !this.app.workspace.leftSplit.collapsed && !document.hidden;
    if (!active) { this.active = false; this.controller?.abort(); return; }
    if (!this.active) { this.active = true; this.refresh(); }
  }
  async setEnabled(enabled) {
    try { await this.plugin.store.setUsageEnabled(enabled); }
    catch { new Notice('Could not save the AI usage setting. Please try again.'); }
  }
  refresh() {
    if (this.disposed || !this.active || this.refreshPromise) return this.refreshPromise || Promise.resolve();
    const controller = this.controller = new AbortController();
    this.refreshPromise = Promise.allSettled(USAGE_PROVIDERS.map(async provider => {
      try {
        const data = await provider.read(controller.signal);
        if (!controller.signal.aborted && !this.disposed) this.states[provider.id] = { data, updatedAt: Date.now(), error: null };
      } catch (error) {
        if (!controller.signal.aborted && !this.disposed) this.states[provider.id].error = error.code && USAGE_ERRORS[error.code] ? error.code : 'OFFLINE';
      }
      if (!this.disposed) this.render();
    })).finally(() => {
      this.refreshPromise = null;
      if (!this.disposed) {
        this.render();
        if (controller.signal.aborted && this.active) this.refresh();
      }
    });
    this.render(); return this.refreshPromise;
  }
  render() {
    if (!this.element || this.disposed) return;
    const focused = this.element.contains(document.activeElement) ? document.activeElement.dataset.usageFocus : null;
    const scroll = this.element.scrollTop;
    this.element.replaceChildren();
    this.element.classList.toggle('is-refreshing', !!this.refreshPromise);
    const header = sectionElement('div', 'bron-usage-heading');
    const title = sectionElement('span', '', 'AI usage');
    const controls = sectionElement('div', 'bron-usage-controls');
    const refresh = sectionButton('Refresh AI usage', 'refresh-cw', () => this.refresh());
    refresh.dataset.usageFocus = 'refresh'; refresh.disabled = !!this.refreshPromise;
    const more = sectionButton('AI usage options', 'ellipsis', event => this.menu(event)); more.dataset.usageFocus = 'menu';
    controls.append(refresh, more); header.append(title, controls); this.element.append(header);
    for (const provider of USAGE_PROVIDERS) {
      const state = this.states[provider.id];
      const block = sectionElement('div', 'bron-usage-provider bron-usage-' + provider.id);
      const name = sectionElement('div', 'bron-usage-provider-name');
      const logo = sectionElement('img', 'bron-usage-logo'); logo.src = USAGE_LOGOS[provider.logo]; logo.alt = ''; logo.width = 16; logo.height = 16;
      name.append(logo, sectionElement('span', '', provider.name)); block.append(name);
      if (state.data) {
        if (state.error) {
          const stale = sectionElement('span', 'bron-usage-stale-dot');
          stale.setAttribute('role', 'img');
          stale.title = USAGE_ERRORS[state.error] + ' · showing the reading from ' + new Date(state.updatedAt).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
          stale.setAttribute('aria-label', stale.title);
          name.append(stale); block.classList.add('is-stale'); refresh.classList.add('has-alert');
        }
        for (const limit of state.data.windows) {
          const row = sectionElement('div', 'bron-usage-window');
          const labels = sectionElement('div', 'bron-usage-labels');
          const percent = Math.round(limit.used) + '%';
          const details = sectionElement('div', 'bron-usage-limit-details');
          const label = sectionElement('span', 'bron-usage-window-label', limit.label);
          label.title = limit.label; details.append(label);
          if (limit.resetsAt) {
            const reset = sectionElement('span', 'bron-usage-reset', usageResetText(limit.resetsAt).replace(/^Resets/, 'resets'));
            reset.title = 'Resets ' + new Date(limit.resetsAt).toLocaleString(); details.append(reset);
          }
          labels.append(details, sectionElement('span', 'bron-usage-percent', percent));
          const bar = sectionElement('div', 'bron-usage-track');
          bar.setAttribute('role', 'progressbar'); bar.setAttribute('aria-label', provider.name + ' ' + limit.label);
          bar.setAttribute('aria-valuemin', '0'); bar.setAttribute('aria-valuemax', '100'); bar.setAttribute('aria-valuenow', String(Math.min(100, limit.used)));
          bar.setAttribute('aria-valuetext', percent + ' used');
          const fill = sectionElement('div', 'bron-usage-fill'); fill.style.width = Math.min(100, limit.used) + '%'; bar.append(fill);
          const elapsed = usageElapsed(limit);
          if (elapsed !== null) {
            const pace = sectionElement('span', 'bron-usage-pace'); pace.style.left = elapsed * 100 + '%'; bar.append(pace);
            bar.title = percent + ' used · ' + Math.round(elapsed * 100) + '% of the window has passed';
          }
          if (limit.used >= 90) bar.classList.add('is-near-limit');
          else if (limit.used >= 75) bar.classList.add('is-high');
          row.append(labels, bar);
          block.append(row);
        }
        if (!state.data.windows.length) block.append(sectionElement('div', 'bron-usage-status', 'No limits reported'));
        if (state.data.credits !== null) {
          name.append(sectionElement('span', 'bron-usage-credit', state.data.credits.toLocaleString(undefined, { maximumFractionDigits: 1 }) + ' credits available'));
        }
      } else {
        const status = state.error ? USAGE_ERRORS[state.error] : this.refreshPromise ? 'Checking usage…' : 'Not refreshed yet';
        const message = sectionElement('div', 'bron-usage-status', status);
        if (state.error === 'AUTH' || state.error === 'LOCKED') message.title = 'Sign in to ' + provider.name + ' on this Mac, then refresh.';
        if (state.error === 'MISSING') message.title = 'Install the Codex CLI and sign in, then refresh.';
        block.append(message);
      }
      if (state.updatedAt) block.title = 'Last updated ' + new Date(state.updatedAt).toLocaleTimeString();
      this.element.append(block);
    }
    const dates = Object.values(this.states).map(s => s.updatedAt).filter(Boolean);
    if (dates.length) {
      const age = Math.max(0, Math.floor((Date.now() - Math.min(...dates)) / 60000));
      const updated = sectionElement('span', 'bron-usage-updated', age < 1 ? 'Updated just now' : 'Updated ' + age + 'm ago');
      updated.title = 'Oldest reading from ' + new Date(Math.min(...dates)).toLocaleTimeString(); controls.prepend(updated);
    }
    this.element.scrollTop = scroll;
    if (focused) [...this.element.querySelectorAll('[data-usage-focus]')].find(e => e.dataset.usageFocus === focused && !e.disabled)?.focus({ preventScroll: true });
  }
  menu(event) {
    this.openMenu?.hide(); const menu = this.openMenu = new Menu(); menu.setUseNativeMenu?.(false);
    menu.addItem(i => i.setTitle('Refresh usage').setIcon('refresh-cw').setDisabled(!!this.refreshPromise).onClick(() => this.refresh()));
    for (const provider of USAGE_PROVIDERS) menu.addItem(i => i.setTitle('View ' + provider.name + ' usage').setIcon('external-link').onClick(() => require('electron').shell.openExternal(provider.url)));
    menu.addSeparator();
    menu.addItem(i => i.setTitle('Hide usage panel').setIcon('eye-off').onClick(() => this.setEnabled(false)));
    if (event.clientX || event.clientY) menu.showAtMouseEvent(event);
    else { const r = event.currentTarget.getBoundingClientRect(); menu.showAtPosition({ x: r.left, y: r.bottom }); }
  }
  dispose() {
    this.disposed = true; this.active = false; this.controller?.abort();
    window.clearInterval(this.poll); window.clearInterval(this.clock); this.openMenu?.hide(); this.element?.remove(); this.element = null;
  }
}
// Share of the limit window already elapsed (0–1), or null when the window length or reset is unknown.
function usageElapsed(limit, now = Date.now()) {
  if (!Number.isFinite(limit.minutes) || limit.minutes <= 0 || !Number.isFinite(limit.resetsAt)) return null;
  return Math.min(1, Math.max(0, 1 - (limit.resetsAt - now) / (limit.minutes * 60000)));
}
class BronUsageSettings extends PluginSettingTab {
  constructor(app, plugin) { super(app, plugin); this.plugin = plugin; }
  display() {
    this.containerEl.replaceChildren();
    new Setting(this.containerEl).setName('AI usage panel').setDesc('Show Claude Code and Codex limits at the bottom of the sidebar. Refreshes every five minutes while visible.').addToggle(toggle => toggle.setValue(this.plugin.store.data.usageEnabled !== false).onChange(async enabled => {
      await this.plugin.usage.setEnabled(enabled); toggle.setValue(this.plugin.store.data.usageEnabled !== false);
    }));
    new Setting(this.containerEl).setName('Refresh usage').setDesc('Uses the accounts signed in to Claude Code and Codex on this computer.').addButton(button => button.setButtonText('Refresh').onClick(async () => {
      button.setDisabled(true); await this.plugin.usage.refresh(); button.setDisabled(false);
    }));
  }
}


module.exports = class BronWorkspace extends Plugin {
  async onload() {
    this.pending = null;
    this.disposed = false;
    this.sidebar = new SidebarActions(this.app);
    const data = await this.loadData();
    try {
      this.store = new SectionStore(data, next => this.saveData(next), () => { if (!this.disposed) { this.sections?.refresh(); this.usage?.sync(); } });
      if (JSON.stringify(data) !== JSON.stringify(this.store.snapshot())) await this.saveData(this.store.snapshot());
      this.sections = new SidebarSections(this);
      this.usage = new SidebarUsage(this);
      this.addSettingTab(new BronUsageSettings(this.app, this));
    } catch (error) {
      new Notice('Sidebar sections could not load: ' + error.message);
      console.error('Bron Workspace:', error);
    }
    const refresh = () => { if (!this.disposed) { this.sidebar.refresh(); this.sections?.refresh(); this.usage?.sync(); } };
    const schedule = () => {
      if (this.pending !== null) return;
      this.pending = window.setTimeout(() => { this.pending = null; refresh(); }, 30);
    };
    this.app.workspace.onLayoutReady(refresh);
    this.registerEvent(this.app.workspace.on('layout-change', schedule));
    this.registerEvent(this.app.workspace.on('css-change', schedule));
    this.registerEvent(this.app.workspace.on('active-leaf-change', () => this.sections?.updateActive()));
    this.registerEvent(this.app.vault.on('rename', (file, oldPath) => {
      if (this.sections) this.sections.run(this.store.renamePath(oldPath, file.path));
    }));
    this.registerEvent(this.app.vault.on('delete', file => {
      if (this.sections) this.sections.run(this.store.deletePath(file.path));
    }));
    this.registerDomEvent(document, 'visibilitychange', () => this.usage?.sync());
    this.addCommand({ id: 'toggle-ai-usage', name: 'Toggle AI usage panel', callback: () => this.usage?.setEnabled(this.store.data.usageEnabled === false) });
    this.addCommand({ id: 'refresh-ai-usage', name: 'Refresh AI usage', callback: () => this.usage?.refresh() });
    this.addCommand({ id: 'add-sidebar-section', name: 'Add sidebar section', callback: () => this.sections?.createSection() });
    this.registerEvent(this.app.workspace.on('file-menu', (menu, file) => {
      if (!this.sections || this.app.customCss.theme !== 'Bron') return;
      const sections = this.store.snapshot().sections;
      if (!sections.length || !file.path || file.path === '/') return;
      menu.addSeparator();
      for (const section of sections) menu.addItem(item => item.setTitle('Add to ' + section.name).setIcon('bookmark-plus').setDisabled(section.items.includes(file.path)).onClick(() => this.sections.run(this.store.addItems(section.id, [file.path]))));
    }));
    this.registerDomEvent(document, 'dragend', () => this.sections?.element?.querySelectorAll('.is-drop-target').forEach(e => e.classList.remove('is-drop-target')));
  }
  onunload() {
    this.disposed = true;
    if (this.pending !== null) window.clearTimeout(this.pending);
    this.usage?.dispose();
    this.sections?.remove();
    this.sidebar?.remove();
  }
};
