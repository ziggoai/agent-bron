const test = require('node:test');
const assert = require('node:assert/strict');
const { TerminalInput, editSequence, readEditor } = require('../src/terminal-input');
const { inspectScreen } = require('../src/terminal-presentation');
const rule='────────────────────────────────────';
function session(provider,lines,cursorY,cursorX){
  let listener;
  const writes=[];
  return {provider,writes,isAlive:()=>true,write:s=>writes.push(s),terminal:{rows:lines.length,onWriteParsed:fn=>{listener=fn;return {dispose(){}};},buffer:{active:{baseY:0,cursorY,cursorX,getLine:i=>({isWrapped:false,translateToString:(trim,start,end)=>end===undefined?lines[i]:lines[i].slice(start,end)})}}}};
}
test('edits preserve the suffix and use native multiline insertion without submitting',()=>{
  assert.equal(editSequence('/mod','/model'), 'el');
  assert.equal(editSequence('hello world','hello brave world'),'\x1b[D'.repeat(5)+'brave '+'\x1b[C'.repeat(5));
  assert.equal(editSequence('one','one\ntwo'),'\x1b\rtwo');
  assert.equal(editSequence('hello',''),'\x7f'.repeat(5));
});
test('command and skill prefixes reach the real CLI as typed characters',()=>{
  const s=session('codex',[],0,0),input=new TerminalInput(s,()=>{});
  for(const value of ['/','/mod','$pdf','@file','!pwd'])input.sync(value);
  assert.equal(s.writes[0],'/');assert.equal(s.writes[1],'mod');
  assert.ok(s.writes.some(s=>s.endsWith('$pdf')));
  input.dispose();
});
test('typed terminal escape characters cannot become native control sequences',()=>{
  const s=session('codex',[],0,0),input=new TerminalInput(s,()=>{});
  assert.throws(()=>input.sync('hello\x1b[A'),/control/);assert.equal(s.writes.length,0);input.dispose();
});
test('native completion preserves its trailing space for the next word',()=>{
  const s=session('codex',['› $pdf:pdf ','','GPT-6-Astra high · ~/project'],0,11);
  assert.equal(readEditor(s),'$pdf:pdf ');
});
test('Claude history remains an editor and restores multiline drafts',()=>{
  const lines=['─── History 2/2 ────────────────────','❯ one','  two',rule,'auto mode on (shift+tab to cycle)'];
  const s=session('claude',lines,2,5);
  assert.equal(inspectScreen('claude',lines,2).ready,true);
  assert.equal(readEditor(s),'one\ntwo');
});
test('native menus cannot be read back as draft text',()=>{
  const s=session('codex',['Select model','› 1. GPT-6-Astra','Enter to confirm · Esc to cancel'],1,2);
  assert.equal(readEditor(s),null);
});
test('typing during completion is retained after the CLI selects its result',()=>{
  const s=session('codex',['› /model ','','GPT-6-Astra high · ~/project'],0,9);
  let edited;
  const input=new TerminalInput(s,value=>{edited=value;});
  input.value='/mod';input.key('\t');input.sync('/modnext');input.reconcile();
  assert.equal(edited,'/model next');input.dispose();
});

test('blank drafts and pasted CRLF or tabs do not submit or select commands',()=>{
  const s=session('codex',[],0,0),input=new TerminalInput(s,()=>{});
  input.sync(' ');assert.equal(s.writes[0],' ');
  input.sync(' one\r\ntwo\t');
  assert.equal(input.value,' one\ntwo\t');
  assert.equal(s.writes[1],'one\x1b\rtwo\x1b[200~\t\x1b[201~');
  input.dispose();
});

test('a delayed submit redraw clears the draft even after the old timeout', () => {
  const lines=[rule,'❯ second message',rule,'auto mode on (shift+tab to cycle)'];
  const s=session('claude',lines,1,16),edits=[];
  const input=new TerminalInput(s,value=>edits.push(value));
  input.sync('second message');input.key('\r');input.reconcile(true);
  assert.equal(input.pending,true);assert.deepEqual(edits,['']);
  lines[1]='❯ ';s.terminal.buffer.active.cursorX=2;input.reconcile();
  assert.equal(input.pending,false);assert.deepEqual(edits,['','']);input.dispose();
});
test('typing the next draft during delayed submission is preserved', () => {
  const lines=['› first message','','GPT-6-Astra high · ~/project'];
  const s=session('codex',lines,0,15);let edited;
  const input=new TerminalInput(s,value=>{edited=value;});
  input.sync('first message');input.key('\r');input.reconcile(true);input.sync('next draft');
  lines[0]='› ';s.terminal.buffer.active.cursorX=2;input.reconcile();
  assert.equal(edited,'next draft');input.dispose();
});
test('Enter completion keeps the accepted skill in the textbox', () => {
  const lines=['› $pdf:pdf  Read PDFs', '', '› $pdf','','GPT-6-Astra high · ~/project'];
  const s=session('codex',lines,2,6);let edited;
  const input=new TerminalInput(s,value=>{edited=value;});
  input.sync('$pdf');input.key('\r');input.reconcile(true);
  lines[2]='› $pdf:pdf ';s.terminal.buffer.active.cursorX=11;input.reconcile();
  assert.equal(edited,'$pdf:pdf ');input.dispose();
});
test('Escape can cancel a submit that leaves the editor unchanged', () => {
  const s=session('claude',[rule,'❯ /',rule,'auto mode on (shift+tab to cycle)'],1,3);
  const input=new TerminalInput(s,()=>{});input.sync('/');input.key('\r');input.reconcile(true);
  assert.equal(input.key('\x1b'),true);assert.equal(s.writes.at(-1),'\x1b');input.dispose();
});

test('CLI word wrapping is not mistaken for Enter accepting a different draft', () => {
  const lines=[rule,'❯ Read the attached file','  and report its contents.',rule,'auto mode on (shift+tab to cycle)'];
  const s=session('claude',lines,2,lines[2].length),edits=[];
  const input=new TerminalInput(s,value=>edits.push(value));
  input.sync('Read the attached file and report its contents.');input.key('\r');input.reconcile(true);
  assert.equal(input.pending,true);assert.deepEqual(edits,['']);
  lines[1]='❯ ';lines[2]=rule;lines[3]='auto mode on (shift+tab to cycle)';lines[4]='';
  s.terminal.buffer.active.cursorY=1;s.terminal.buffer.active.cursorX=2;input.reconcile();
  assert.deepEqual(edits,['','']);input.dispose();
});

test('unconfirmed Enter has a bounded recovery path and never resends the old draft', () => {
  const s=session('claude',[rule,'❯ unchanged',rule,'auto mode on (shift+tab to cycle)'],1,11);
  const edits=[], errors=[];
  const input=new TerminalInput(s,v=>edits.push(v),e=>errors.push(e));
  input.sync('unchanged'); input.key('\r'); input.sync('next draft');
  input.deadline=0; input.reconcile(true);
  assert.equal(input.pending,false); assert.equal(input.blocked,true);
  assert.equal(errors.length,1); assert.deepEqual(edits,['']);
  assert.equal(input.sync('retry'),false);
  assert.equal(s.writes.filter(s=>s==='\r').length,1);
  input.dispose();
});

test('a new program in the tab starts unblocked with an empty editor', () => {
  const s=session('codex',['› unchanged','','GPT-6-Astra high · ~/project'],0,11);
  const input=new TerminalInput(s,()=>{},()=>{});
  input.sync('unchanged'); input.key('\r'); input.deadline=0; input.reconcile(true);
  assert.equal(input.blocked,true); assert.equal(input.sync('retry'),false);
  // The view calls reset() when Codex exits and a new program starts in the same tab.
  input.reset(); s.writes.length=0;
  assert.equal(input.sync('hello'),true); assert.deepEqual(s.writes,['hello']);
  input.dispose();
});

test('PTY write failure preserves the draft and does not leave a pending send', () => {
  const s=session('claude',[rule,'❯ draft',rule,'auto mode on (shift+tab to cycle)'],1,7);
  const edits=[]; const input=new TerminalInput(s,v=>edits.push(v)); input.value='draft';
  s.write=()=>{throw Error('closed');};
  assert.throws(()=>input.key('\r'),/closed/); assert.equal(input.pending,false);
  assert.equal(input.value,'draft'); assert.deepEqual(edits,[]); input.dispose();
});

test('collapsed paste labels are never restored as the user draft', () => {
  const lines=[rule,'❯ [Pasted text #1 +20 lines]',rule,'auto mode on (shift+tab to cycle)'];
  const s=session('claude',lines,1,29), edits=[];
  const input=new TerminalInput(s,v=>edits.push(v));
  input.submitPasted('real text\n'.repeat(20)); input.reconcile(true);
  assert.equal(input.pending,true); assert.deepEqual(edits,['']);
  lines[1]='❯ ';s.terminal.buffer.active.cursorX=2;input.reconcile();
  assert.equal(input.pending,false); assert.ok(edits.every(s=>s==='')); input.dispose();
});

test('disposed reconciliation cannot edit the next session', () => {
  const s=session('codex',['› draft','','GPT-6 high · ~/project'],0,7), edits=[];
  const input=new TerminalInput(s,v=>edits.push(v));input.value='draft';input.key('\r');input.dispose();
  input.reconcile(true);assert.deepEqual(edits,['']);assert.equal(input.sync('late'),false);
});
