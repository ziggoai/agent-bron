const test = require('node:test');
const assert = require('node:assert/strict');
const { droppedPaths, mergeAttachments } = require('../src/file-drop');
const { composeMessage } = require('../src/composer-service');
const context = { vaultRoot: '/vault', vaultName: 'My Vault', filePath: f => f.nativePath, resolveLink: link => ['Notes/A & B.md', 'Notes'].includes(link) ? { path: link } : null };
const transfer = (data = {}, files = []) => ({ files, getData: key => data[key] || '' });

test('Finder files and encoded file URLs resolve without losing spaces or punctuation', () => {
  assert.deepEqual(droppedPaths(transfer({'text/uri-list':'file:///tmp/A%20%26%20B.png'}, [{nativePath:'/tmp/A & B.png'}]), context), ['/tmp/A & B.png']);
});
test('Obsidian multi-file and folder drags retain full vault paths', () => {
  assert.deepEqual(droppedPaths(transfer({'text/plain':'A & B'}), {...context, dragged:{type:'files',files:[{path:'Notes/A & B.md'},{path:'Notes'}]}}), ['/vault/Notes/A & B.md','/vault/Notes']);
});
test('Obsidian URLs and wiki links resolve existing files but not another vault', () => {
  assert.deepEqual(droppedPaths(transfer({'text/uri-list':'obsidian://open?vault=My%20Vault&file=Notes%2FA%20%26%20B.md','text/plain':'[[Notes/A & B.md|Alias]]'}), context), ['/vault/Notes/A & B.md']);
  assert.deepEqual(droppedPaths(transfer({'text/plain':'obsidian://open?vault=Other&file=Notes'}), context), []);
});
test('ordinary text and malformed URIs do not become attachments', () => {
  assert.deepEqual(droppedPaths(transfer({'text/plain':'Some prose','text/uri-list':'file://%broken'}), context), []);
});
test('attachments deduplicate, skip missing files, and keep the twelve-file limit', () => {
  const stat = p => { if(p==='/missing')throw Error('Missing');return {isFile:()=>true}; };
  const existing=Array.from({length:11},(_,i)=>({name:String(i),path:'/tmp/'+i}));
  const result=mergeAttachments(existing,['/tmp/0','/missing','/tmp/new','/tmp/extra'],stat);
  assert.equal(result.attachments.length,12);assert.equal(existing.length,11);
  assert.deepEqual(result.rejected,['/missing','/tmp/extra']);
});
test('dropped paths enter the same quoted message used by both providers', () => {
  const fullPath='/tmp/a "quoted" $(name).txt';
  const result=mergeAttachments([], [fullPath], ()=>({isFile:()=>true}));
  assert.ok(composeMessage('Read this',result.attachments).includes(JSON.stringify(fullPath)));
});
