const test = require('node:test');
const assert = require('node:assert/strict');
const { isToolAction } = require('../src/transcript-style');
test('both providers identify tool activity for accents', () => {
  for (const line of ['⏺ Bash(node check.js)', '⏺ Read(file.md)', '  Read 1 file (ctrl+o to expand)', '• Ran npm test', '• Edited 2 files (+2 -1)', '  └ Read main.js']) assert.equal(isToolAction(line), true, line);
});
test('conversation prose, prompts, and menus keep their native styling', () => {
  for (const line of ['• I will read the file.', '⏺ The file is ready.', '❯ Read file.md', '› 1. GPT-6', '- Updated instructions', '  + 24 lines (ctrl+o to expand)']) assert.equal(isToolAction(line), false, line);
});
