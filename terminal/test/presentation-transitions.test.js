const test = require('node:test');
const assert = require('node:assert/strict');
const {TerminalPresentation} = require('../src/terminal-presentation');
const rule='────────────────────────────────';
const prompt=['Answer', '', '', '', rule, '❯ ', rule, 'auto mode on (shift+tab to cycle)'];
const menu=['Select model', '❯ 1. Default', '  2. Opus', '', '', '', '', 'Enter to select · Esc to cancel'];
function renderer(provider = 'claude', initial = prompt, initialCursor = 5) {
  const events={}, commits=[]; let lines=initial, cursor=initialCursor, composerVisible=false, now=0;
  const style=new Proxy({setProperty(){}}, {set(target,key,value) {
    if(session.provider !== 'shell' && key==='clipPath' && value==='inset(0px 0 0px 0)' && terminal.buffer.active.viewportY===terminal.buffer.active.baseY) assert.equal(composerVisible,false,'hide composer before unmasking native controls');
    target[key]=value;return true;
  }});
  const win={performance:{now:()=>now},setTimeout:()=>1,clearTimeout(){},requestAnimationFrame:()=>1,cancelAnimationFrame(){}};
  const terminal={rows:8,buffer:{active:{baseY:100,viewportY:100,get cursorY(){return cursor;},getLine:i=>({translateToString:()=>lines[i-terminal.buffer.active.baseY]||''})}}};
  for(const event of ['onWriteParsed','onRender','onResize','onScroll'])terminal[event]=fn=>{const previous=events[event];events[event]=()=>{previous?.();fn();};return {dispose(){}};};
  const session={provider,terminal,fit(){},host:{clientHeight:160,style,ownerDocument:{createElement:()=>({remove(){}}),body:{classList:{contains:()=>false}}},shadowRoot:{appendChild(){},querySelectorAll:()=>[],querySelector:selector=>selector==='.xterm-rows'?{children:[]}:{getBoundingClientRect:()=>({height:160})}}}};
  const container={clientHeight:160,ownerDocument:{defaultView:win},parentElement:{style:{}}};
  const presentation=new TerminalPresentation(session,container,state=>{
    composerVisible=!state.native;
    if(session.provider !== 'shell' && composerVisible && terminal.buffer.active.viewportY===terminal.buffer.active.baseY)assert.notEqual(style.clipPath,'inset(0px 0 0px 0)','mask prompt before revealing composer');
    commits.push({...state});
  });
  return {session,presentation,commits,style,container,scroll(rows){terminal.buffer.active.viewportY=terminal.buffer.active.baseY-rows;events.onScroll();events.onRender();},advance(ms){now+=ms;presentation.update();},render(){events.onRender();},get composerVisible(){return composerVisible;},screen(next,nextCursor=1){lines=next;cursor=nextCursor;events.onWriteParsed();}};
}

for (const [provider, lines, cursor, cropRows] of [
  ['claude', prompt, 5, 4],
  ['codex', ['• Answer', '', '', '', '› Ask Codex to do anything', '', 'GPT-6-Astra high · ~/project', ''], 4, 5],
]) {
  test(`${provider} keeps the native textbox hidden throughout scrollback and return`, () => {
    const r=renderer(provider,lines,cursor);
    for(const offset of [1,2,3,cropRows,cropRows+1,50,3,2,1,0]) {
      r.scroll(offset);
      const visible=Math.max(0,cropRows-offset);
      assert.equal(r.style.clipPath,`inset(0px 0 ${visible ? visible*20+1 : 0}px 0)`,`scroll offset ${offset}`);
      assert.equal(r.composerVisible,true);
      assert.equal(r.presentation.state.native,false);
    }
    r.presentation.dispose();
  });
}

test('scrolling still allows explicit native terminal controls', () => {
  const r=renderer();
  r.scroll(1);
  r.presentation.setNative(true);
  assert.equal(r.composerVisible,false);
  assert.equal(r.style.clipPath,'inset(0px 0 0px 0)');
  r.presentation.setNative(false);
  assert.equal(r.style.clipPath,'inset(0px 0 61px 0)');
  assert.equal(r.composerVisible,true);
  r.presentation.dispose();
});

test('model cancellation restores one composer in the same parsed-write callback',()=>{
  const r=renderer();
  r.presentation.setNative(true);assert.equal(r.composerVisible,false);
  r.screen(menu);assert.equal(r.presentation.state.native,true);
  r.screen(prompt,5);
  assert.equal(r.presentation.state.native,false);
  assert.equal(r.composerVisible,true);
  assert.equal(r.presentation.state.bottom,4);
  r.presentation.dispose();
});

test('unknown and partial screens cannot expose two inputs',()=>{
  const r=renderer();
  r.screen(['Loading a dialog…']);assert.equal(r.composerVisible,true);
  assert.equal(r.presentation.state.ready,false);
  r.screen(menu);r.advance(200);assert.equal(r.composerVisible,false);
  r.screen(prompt,5);assert.equal(r.composerVisible,true);
  r.presentation.dispose();
});

test('automatic dialogs return to the composer without a manual toggle',()=>{
  const r=renderer();
  for(let i=0;i<3;i++){
    r.screen(menu);r.advance(200);assert.equal(r.composerVisible,false);
    r.screen(prompt,5);assert.equal(r.composerVisible,true);
  }
  r.presentation.dispose();
});

test('loading redraws preserve the composer while clipping the native prompt',()=>{
  const r=renderer();
  const busy=[...prompt];busy[7]+=' · esc to interrupt';
  for(const cursor of [0,3,5]){
    r.screen(busy,cursor);assert.equal(r.composerVisible,true);assert.equal(r.presentation.state.bottom,4);
  }
  r.presentation.dispose();
});

test('transient redraws do not resize the terminal or switch input owners',()=>{
  const r=renderer(),margin=r.container.parentElement.style.marginBottom;
  for(let i=0;i<30;i++){
    r.screen(['Partial repaint']);r.advance(30);
    assert.equal(r.composerVisible,true);
    assert.equal(r.presentation.state.ready,false);
    assert.equal(r.container.parentElement.style.marginBottom,margin);
    r.screen(prompt,5);
    assert.equal(r.container.parentElement.style.marginBottom,margin);
  }
  assert.ok(r.commits.every(s=>!s.native));
  r.presentation.dispose();
});

test('unchanged terminal frames do not rewrite composer controls',()=>{
  const r=renderer(),count=r.commits.length;
  for(let i=0;i<30;i++)r.render();
  assert.equal(r.commits.length,count);
  r.presentation.dispose();
});

test('Back to message keeps a confirmed dialog active until Escape closes it',()=>{
  const r=renderer();
  r.presentation.setNative(true);r.screen(menu);
  r.presentation.setNative(false);
  assert.equal(r.presentation.state.native,true);
  assert.equal(r.composerVisible,false);
  r.screen(prompt,5);
  assert.equal(r.composerVisible,true);
  r.presentation.dispose();
});


test('Codex keeps the painted prompt covered until the next render',()=>{
  const first=['• Answer', '', '› Ask Codex to do anything', '', 'GPT-6-Astra high · ~/project', '', '', ''];
  const moved=['• Answer', '  More output', '  Still more', '', '› Ask Codex to do anything', '', 'GPT-6-Astra high · ~/project', ''];
  const r=renderer('codex',first,2);
  r.render();
  const oldClip=r.style.clipPath;
  r.screen(moved,1);
  assert.equal(r.presentation.state.ready,true,'cursor painting the response is not a dialog');
  assert.equal(r.style.clipPath,oldClip,'old DOM prompt stays covered before xterm renders');
  r.render();
  assert.notEqual(r.style.clipPath,oldClip,'new output becomes visible once painted');
  assert.equal(r.style.clipPath,'inset(0px 0 101px 0)');
  r.presentation.dispose();
});

test('a completion list below Claude input never unmasks the native textbox',()=>{
  const lines=['Claude Code',rule,'❯ /',rule,'  /help   Get help','  /model  Select model','',''];
  const r=renderer('claude',lines,2);
  r.render();assert.equal(r.composerVisible,true);
  assert.equal(r.presentation.state.bottom,7);
  assert.equal(r.style.clipPath,'inset(0px 0 141px 0)');
  r.presentation.dispose();
});

test('a slow Claude mention redraw keeps the composer visible while the cursor paints results',()=>{
  const lines=['Answer','',rule,'❯ look at @agent',rule,'  + agent.md','  * Agent (agent) – Select files to inspect',''];
  const r=renderer('claude',lines,3);
  r.screen(lines,6);r.advance(700);r.render();
  assert.equal(r.presentation.state.native,false);
  assert.equal(r.presentation.state.ready,true);
  assert.equal(r.composerVisible,true);
  assert.notEqual(r.style.clipPath,'inset(0px 0 0px 0)');
  r.screen(menu);r.advance(200);assert.equal(r.presentation.state.native,true);
  r.presentation.dispose();
});

test('stale mention rows during deletion do not hide the composer',()=>{
  const lines=['Answer','',rule,'❯ look at @',rule,'  + agent.md','  * Agent (agent) – Select files to inspect',''];
  const r=renderer('claude',lines,3);
  r.screen(['Answer','',rule,'❯ look at ',rule,'  + agent.md','  * Agent (agent) – Select files to inspect',''],6);
  r.advance(700);assert.equal(r.presentation.state.native,false);assert.equal(r.composerVisible,true);
  r.presentation.dispose();
});

test('a shell session recognizes CLI editors and returns to the shell without clipping its prompt', () => {
  const r=renderer('shell',['project % '],0),s=r.session;
  s.launchProvider='shell';s.atShell=true;s.terminal.modes={bracketedPasteMode:true};
  r.presentation.update();
  assert.equal(r.presentation.state.provider,'shell');assert.equal(r.presentation.state.ready,true);
  s.atShell=false;r.screen(prompt,5);
  assert.equal(s.provider,'claude');assert.equal(r.composerVisible,true);
  r.screen(menu);r.advance(200);assert.equal(r.composerVisible,false);
  r.screen(['• Done','','','','› Ask Codex to do anything','','GPT-6 high · ~/project',''],4);
  assert.equal(s.provider,'codex');assert.equal(r.presentation.state.native,false);
  s.atShell=true;r.screen(['project % '],0);
  assert.equal(s.provider,'shell');assert.equal(r.presentation.state.bottom,0);
  assert.equal(r.presentation.state.native,false);r.presentation.dispose();
});
