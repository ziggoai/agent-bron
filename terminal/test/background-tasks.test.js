const test = require('node:test');
const assert = require('node:assert/strict');
const { backgroundTaskLines, BackgroundTasks } = require('../src/background-tasks');
const { inspectScreen } = require('../src/terminal-presentation');
const rule = '────────────────────────────────';
const task = '  ◯ general-purpose  Probing spikebot… 4m 38s · ↓ 74.3k tokens';
const lines = ['Answer', rule, '❯ ', rule, '  auto mode on (shift+tab to cycle) · ↓ to manage',
  '  ✔ Update installed · Restart to update', '', '  ⏺ main', task, ''];

test('Claude background activity is preserved without duplicating its input or mode footer', () => {
  const state = inspectScreen('claude', lines, 2);
  assert.deepEqual(backgroundTaskLines('claude', lines, state), ['⏺ main', task.trimStart()]);
});

test('task extraction excludes ordinary transcript text, Codex, and native dialogs', () => {
  const state = inspectScreen('claude', lines, 2);
  for (const other of [{...state, native:true}, {...state, ready:false}, {...state, bottom:0}]) {
    assert.deepEqual(backgroundTaskLines('claude', lines, other), []);
  }
  assert.deepEqual(backgroundTaskLines('codex', lines, state), []);
  const transcript = ['⏺ main', task, 'Answer', rule, '❯ ', rule, 'auto mode on', ''];
  assert.deepEqual(backgroundTaskLines('claude', transcript, inspectScreen('claude', transcript, 4)), []);
  assert.deepEqual(backgroundTaskLines('claude', lines.slice(0,-2), state), []);
});

test('multiple tasks and wrapped activity retain time and token details', () => {
  const wrapped = [...lines.slice(0,-1), '    more activity details', '  ◯ build  Running checks… 20s · ↓ 2k tokens', ''];
  assert.deepEqual(backgroundTaskLines('claude', wrapped, inspectScreen('claude', wrapped, 2)),
    ['⏺ main', task.trimStart(), '  more activity details', '◯ build  Running checks… 20s · ↓ 2k tokens']);
});

test('the task panel updates live and disappears when tasks finish or controls open', () => {
  const panel = {setAttribute(){}, remove(){this.removed=true;}};
  const container = {ownerDocument:{createElement:()=>panel}, parentElement:{nextElementSibling:{classList:{contains:()=>true},prepend(){}}}};
  const tasks = new BackgroundTasks({provider:'claude'}, container);
  const state = inspectScreen('claude', lines, 2);
  tasks.render(lines, state);
  assert.equal(panel.hidden,false);
  assert.match(panel.textContent,/4m 38s · ↓ 74.3k tokens/);
  tasks.render(lines.map(line=>line.replace('4m 38s', '5m 12s')), state);
  assert.match(panel.textContent,/5m 12s/);
  tasks.render(lines, {...state,native:true});
  assert.equal(panel.hidden,true);
  tasks.render(lines.slice(0,7), state);
  assert.equal(panel.hidden,true);
  assert.equal(panel.textContent,'');
  tasks.dispose();
  assert.equal(panel.removed,true);
});

test('task descriptions that sound like dialog prompts never hide the composer', () => {
  for (const activity of ['Confirming renamed-agents…', 'Select the newest build…', 'Checking yes/no, flags…', 'Press Enter to continue…']) {
    const screen = lines.map(line => line === task ? '  ○ general-purpose  ' + activity + ' 6m 2s · ↓ 125.5k tokens' : line);
    const state = inspectScreen('claude', screen, 2);
    assert.equal(state.ready, true, activity);
    assert.equal(state.mode, 'auto mode on', activity);
  }
});
