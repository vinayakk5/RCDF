const fs = require('fs');
const path = 'index.html';
const data = fs.readFileSync(path, 'utf8');
const m = data.match(/<script[^>]*>([\s\S]*?)<\/script>/i);
if(!m){ console.error('NO_SCRIPT'); process.exit(2); }
const script = m[1];
const lines = script.split('\n');
for(let i=1;i<=lines.length;i++){
  const chunk = lines.slice(0,i).join('\n');
  try{
    new Function(chunk);
  }catch(e){
    console.error('ERROR_AT_LINE', i);
    const start = Math.max(0, i-6);
    const end = Math.min(lines.length, i+2);
    const ctx = lines.slice(start, end).map((l, idx) => `${start+idx+1}: ${l}`).join('\n');
    console.error(ctx);
    console.error('ERR_MSG', e && e.message);
    process.exit(3);
  }
}
console.log('NO_SYNTAX_ERROR_DETECTED');
