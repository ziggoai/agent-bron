const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {createRequire} = require('node:module');
const {normalizeMessage, ComposerService, MAX_MESSAGE_BYTES} = require('../src/composer-service');
const localRequire = createRequire(require.resolve('../src/main'));
const moduleStub = {exports:{}};
vm.runInNewContext(fs.readFileSync(require.resolve('../src/main'),'utf8'), {
  module:moduleStub, Buffer, setTimeout, clearTimeout,
  require: name => name === 'obsidian' ? Object.fromEntries(['Plugin','ItemView','Modal','FuzzySuggestModal','PluginSettingTab'].map(k=>[k,class {}]))
    : name === 'electron' ? {} : name.endsWith('.svg') ? '' : localRequire(name)
});
const View = moduleStub.exports.View;
function view(draft) {
  const events=[];
  const v=Object.create(View.prototype);
  Object.assign(v,{phase:'running',input:{value:draft,focus(){}},attachments:[],closed:false,
    presentation:{state:{ready:true}},composer:new ComposerService(async()=>{}),
    terminalInput:{pending:false,sync:s=>{events.push(['sync',s]);return true;},key:k=>events.push(['key',k])},
    session:{isAlive:()=>true,paste:s=>events.push(['paste',s]),write:s=>events.push(['write',s])},
    errorEl:{empty(){},setText:s=>events.push(['error',s])},
    sync(){},saveLayout(){},resizeInput(){},renderAttachments(){}});
  return {v,events};
}
test('messages above the old limit are preserved; the new boundary is UTF-8 bytes',()=>{
  for(const text of ['a'.repeat(177012), '🌍'.repeat(MAX_MESSAGE_BYTES/4), 'a'.repeat(MAX_MESSAGE_BYTES)])
    assert.equal(normalizeMessage(text),text);
  assert.throws(()=>normalizeMessage('🌍'.repeat(MAX_MESSAGE_BYTES/4)+'a'),/1 MiB/);
});
test('long drafts stay local and submit in one complete paste followed by Enter',async()=>{
  const draft=('café 🌍\n').repeat(20000)+'END'; const {v,events}=view(draft);
  assert.equal(v.syncTerminalInput(),false); assert.deepEqual(events,[]);
  await v.submit();
  assert.deepEqual(events,[['sync',''],['paste',draft],['write','\r']]);
  assert.equal(v.input.value,'');
});
test('short typing still reaches native completion and submission',async()=>{
  const {v,events}=view('/model');await v.submit();
  assert.deepEqual(events,[['sync','/model'],['key','\r']]);
});
test('oversized text stays intact and is rejected before any terminal mutation',async()=>{
  const draft='x'.repeat(MAX_MESSAGE_BYTES+1);const {v,events}=view(draft);
  await v.submit();assert.equal(v.input.value,draft);
  assert.equal(events.length,1);assert.equal(events[0][0],'error');assert.match(events[0][1],/1 MiB/);
});
test('paste failure retains the entire composer draft',async()=>{
  const draft='x'.repeat(150000);const {v,events}=view(draft);
  v.session.paste=()=>{throw Error('Session ended');};await v.submit();
  assert.equal(v.input.value,draft);assert.deepEqual(events,[['sync',''],['error','Session ended']]);
});
test('large first message bypasses argv and waits for the ready editor',async()=>{
  const draft='x'.repeat(177012);const {v,events}=view(draft);
  v.phase='idle';v.provider='claude';v.cwd='/tmp';
  v.terminalInput.dispose=()=>{};v.presentation.dispose=()=>{};v.setMode=()=>{};
  v.terminalEl={empty(){}};v.session.dispose=()=>{};
  const session={...v.session,fit(){},terminal:{rows:0,buffer:{active:{baseY:0}},modes:{bracketedPasteMode:true},onWriteParsed:()=>({dispose(){}})}};
  v.plugin={terminals:{create:async options=>{assert.equal(options.initialPrompt,'');return session;}}};
  v.attachPresentation=()=>{v.presentation={state:{ready:true}};};
  await v.start(false,true);
  assert.deepEqual(events,[['paste',draft],['write','\r']]);assert.equal(v.input.value,'');
  assert.equal(v.phase,'running');assert.equal(v.startingWithPrompt,false);v.terminalInput.dispose();
});

test('even short multiline and tabbed drafts use bracketed paste, never synthetic Escape/Enter', async () => {
  for (const draft of ['first\nsecond', 'café 🌍\n世界', 'one\ttwo']) {
    const {v,events}=view(draft);
    assert.equal(v.syncTerminalInput(),false);
    await v.submit();
    assert.deepEqual(events,[['sync',''],['paste',draft],['write','\r']]);
    assert.equal(v.input.value,'');
  }
});
