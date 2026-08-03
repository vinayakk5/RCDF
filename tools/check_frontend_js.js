const fs = require('fs');
const path = 'c:/Users/user/Desktop/freelancer/business/rcdf/frontend/index.html';
const s = fs.readFileSync(path, 'utf8');
const m = s.match(/<script[^>]*>([\s\S]*)<\/script>/);
if (!m) { console.error('script tag not found'); process.exit(2); }
const code = m[1];
try {
  const vm = require('vm');
  // Compile with a filename so stack traces show line numbers relative to the script
  new vm.Script(code, { filename: 'frontend_inline.js' });
  console.log('OK');
} catch (e) {
  console.error('SYNTAX ERROR');
  console.error(e && e.stack ? e.stack : e);
  process.exit(3);
}
