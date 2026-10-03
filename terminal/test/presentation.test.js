const test = require('node:test');
const assert = require('node:assert/strict');
const {inspectScreen, modeLabel} = require('../src/terminal-presentation');
const rule = '────────────────────────────────────────────────────';
const banner = ['', ' ▐▛███▛█   Claude Code v2.1.286', '▝▜██████▀  Opus 5.5 with high effort · Claude Team', ' ▝▝   ▝▝   ~/Documents/Obsidian/theme-test', '', ''];
const transcript = ['❯ hello', '', '⏺ Hello!'];
function claude(mode='auto mode on', extra=[]) { return [...banner, ...transcript, ...extra, rule, '❯ ', rule, `  ⏵⏵ ${mode} (shift+tab to cycle) · ← 6 agents`]; }

test('Claude startup branding stays visible while its input is hidden', () => {
  const lines = claude();
  const state = inspectScreen('claude', lines, lines.length - 3);
  assert.deepEqual(state, {top:0, bottom:4, mode:'auto mode on', ready:true, busy:false});
  assert.deepEqual(lines.slice(state.top, -state.bottom), [...banner,...transcript]);
});

test('mode label follows actual CLI state, including manual mode', () => {
  for (const mode of ['auto mode on', 'manual mode on', 'plan mode on', 'accept edits on', 'bypass permissions on']) {
    const lines = claude(mode);
    assert.equal(inspectScreen('claude', lines, lines.length - 3).mode, mode);
  }
});

test('an unrecognized mode never inherits an earlier auto-mode label', () => {
  const lines = claude('');
  assert.equal(inspectScreen('claude', lines, lines.length - 3).mode, 'Mode');
});

test('Claude effort indicator belongs to the hidden input area', () => {
  const lines = claude('auto mode on', ['                    ● high · /effort']);
  const state = inspectScreen('claude', lines, lines.length - 3);
  assert.equal(state.bottom, 5);
  assert.deepEqual(lines.slice(state.top, -state.bottom), [...banner,...transcript]);
});

test('multiline prompt and blank trailing rows are cropped as one area', () => {
  const lines = [...transcript, rule, '❯ first', '  second', rule, '  ⏵⏵ auto mode on (shift+tab to cycle)', '', ''];
  assert.equal(inspectScreen('claude', lines, 5).bottom, 7);
});

test('Claude approval and model menus stay visible', () => {
  for (const lines of [
    [rule, 'Allow this command?', '❯ 1. Yes', '  2. No', rule, 'Enter to confirm · Esc to cancel'],
    [rule, '❯ /model', rule, 'Select model', '❯ 1. Opus', '  2. Sonnet', 'Enter to confirm'],
    [rule, '❯ ', rule, 'Press Enter to confirm'],
  ]) assert.equal(inspectScreen('claude', lines, 2).bottom, 0);
});

test('a rule inside output is not mistaken for an active prompt', () => {
  const lines = [...claude(), 'Other output'];
  assert.equal(inspectScreen('claude', lines, lines.length - 1).bottom, 0);
});

test('Codex prompt and status are hidden but its response stays visible', () => {
  const lines = ['› hello', '', '• Hello!', '', '› Ask Codex to do anything', '', '  GPT-6-Astra high · ~/project · ← for agents', '', ''];
  const state = inspectScreen('codex', lines, 4);
  assert.equal(state.bottom, 6);
  assert.deepEqual(lines.slice(0, -state.bottom), ['› hello', '', '• Hello!']);
});

test('Codex startup branding and first message remain visible', () => {
  const lines = ['', '  >_ OpenAI Codex (v0.159.2)', '     ~/project', '', '  What are we cooking up?', '', '  Tip: Try a command', '  continued tip', '', '› hello', '', '• Hello!', '', '› Ask Codex to do anything', '', 'GPT-6-Astra high · ~/project'];
  const state = inspectScreen('codex', lines, 13);
  assert.equal(state.top, 0);
  assert.ok(lines.slice(state.top, -state.bottom).includes('• Hello!'));
});

test('Codex approvals and numbered menus are never mistaken for the composer', () => {
  const lines = ['Select model', '› 1. GPT-6-Astra', '  2. GPT-6-Sol', 'Enter to confirm · Esc to cancel', 'GPT-6-Astra high · ~/project'];
  assert.equal(inspectScreen('codex', lines, 1).bottom, 0);
});

test('no banner is hidden in scrollback based on a quoted version string', () => {
  const lines = claude();
  assert.equal(inspectScreen('claude', lines, lines.length - 3, false).top, 0);
});

test('narrow Claude layout keeps its branding and hides the truncated manual footer', () => {
  const lines = ['', '           Claude Code v2.1.286', ' ▐▛███▛█   Opus 5.5 with high …', '▝▜██████▀  Claude Team', ' ▝▝   ▝▝   ~/…/theme-test', '', '', ...transcript, rule, '❯ ', rule, '  ⏸ manual mode on · ? for short…'];
  const state = inspectScreen('claude', lines, lines.length - 3);
  assert.deepEqual(state, {top:0,bottom:4,mode:'manual mode on',ready:true,busy:false});
  assert.deepEqual(lines.slice(state.top, -state.bottom),lines.slice(0,-4));
});

test('Claude loading hint keeps its textbox hidden and mode available', () => {
  const lines = [...transcript, '', '✶ Brewing…', '  Tip: Use /feedback to help us improve!', '', rule, '❯ ', rule, '  ⏵⏵ auto mode on (shift+tab to cycle) · esc to interrupt · ← 6 agents'];
  const state = inspectScreen('claude', lines, lines.length - 3);
  assert.equal(state.bottom, 4);
  assert.equal(state.mode, 'auto mode on');
  assert.equal(state.ready, true);
  assert.equal(state.busy, true);
  assert.ok(lines.slice(0, -state.bottom).includes('✶ Brewing…'));
});

test('Codex interrupt hint keeps the response composer hidden', () => {
  const lines = ['• Working (esc to interrupt)', '', '› Ask Codex to do anything', '', 'GPT-6-Astra high · ~/project · esc to interrupt'];
  const state = inspectScreen('codex', lines, 2);
  assert.equal(state.bottom, 4);
  assert.equal(state.busy, true);
});

test('idle prompts are not busy, so the stop button stays hidden', () => {
  const claudeLines = claude();
  assert.equal(inspectScreen('claude', claudeLines, claudeLines.length - 3).busy, false);
  const codexLines = ['• Done', '', '› Ask Codex to do anything', '', '  GPT-6-Astra high · ~/project · ← for agents'];
  assert.equal(inspectScreen('codex', codexLines, 2).busy, false);
});

test('a dialog that mentions interrupting is never reported as busy', () => {
  const lines = [rule, 'Allow this command?', '❯ 1. Yes', '  2. No', rule, 'Enter to confirm · esc to interrupt'];
  const state = inspectScreen('claude', lines, 2);
  assert.equal(state.ready, false);
  assert.equal(state.busy, false);
});

test('cancel and confirmation dialogs still stay visible', () => {
  for (const footer of ['esc to cancel', 'esc to go back', 'enter to confirm', 'select an option']) {
    const lines = [rule, '❯ ', rule, 'auto mode on · ' + footer];
    assert.equal(inspectScreen('claude', lines, 1).bottom, 0, footer);
    const codex = ['› Ask Codex to do anything', '', 'GPT-6-Astra high · ~/project · ' + footer];
    assert.equal(inspectScreen('codex', codex, 0).bottom, 0, footer);
  }
});

test('empty Claude session keeps the startup logo and clips only the prompt', () => {
  const lines=[...banner,...Array(25).fill(''),rule,'❯ Try a question',rule,'auto mode on (shift+tab to cycle)'];
  const state=inspectScreen('claude',lines,lines.length-3);
  assert.equal(state.top,0);
  assert.equal(state.bottom,4);
});

test('mode pill labels drop the trailing "on" and keep a kind for the indicator', () => {
  assert.deepEqual(modeLabel('auto mode on'), {label:'Auto mode', kind:'auto'});
  assert.deepEqual(modeLabel('plan mode on'), {label:'Plan mode', kind:'plan'});
  assert.deepEqual(modeLabel('accept edits on'), {label:'Accept edits', kind:'accept'});
  assert.deepEqual(modeLabel('bypass permissions on'), {label:'Bypass permissions', kind:'bypass'});
  assert.deepEqual(modeLabel('Mode'), {label:'Mode', kind:'other'});
  assert.deepEqual(modeLabel(''), {label:'', kind:'other'});
});
