// Reuse the agent's exact rich-copy renderer; do not invent a new layout.
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(process.argv[2], 'utf8')
  .replace(/^import .*;$/gm, '').replace(/^export \{[^\n]*\};?$/gm, '');
const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(source, sandbox);
const md = fs.readFileSync(0, 'utf8');
process.stdout.write(JSON.stringify({html: "<meta charset='utf-8'>" + sandbox.mdToHtml(md), plain: sandbox.stripMarkdown(md)}));
