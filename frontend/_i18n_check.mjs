import fs from 'fs';
import path from 'path';
import { fileURLToPath, pathToFileURL } from 'url';
import { execSync } from 'child_process';

const base = '/home/liunx/workspace/ai-team-hub/frontend/src';
const i18nDir = path.join(base, 'i18n');

// Use babel-free: read file, strip `export default` and re-wrap as a function return.
function loadDict(file) {
  const src = fs.readFileSync(file, 'utf-8');
  // extract the object: convert `export default {` ... `}` to a CommonJS module returning the object.
  // Remove comments
  let s = src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
  // find first '{' and last '}'
  const start = s.indexOf('{');
  const end = s.lastIndexOf('}');
  const objLiteral = s.slice(start, end + 1);
  // Use Function to evaluate the object literal (safe: it's our own i18n data, no calls except template literals fine)
  // eslint-disable-next-line no-new-func
  const dict = new Function('return (' + objLiteral + ');')();
  return dict;
}

function flatten(obj, prefix = '', out = new Set()) {
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix ? prefix + '.' + k : k;
    if (v && typeof v === 'object' && !Array.isArray(v)) {
      flatten(v, key, out);
    } else {
      out.add(key);
    }
  }
  return out;
}

const langs = ['zh', 'en', 'ja', 'ko'];
const dicts = {};
for (const l of langs) {
  const d = loadDict(path.join(i18nDir, l + '.js'));
  dicts[l] = flatten(d);
}

// Collect t('literal.key') refs across src (jsx/js)
const KEY_RE = /^[a-z][a-z0-9_]*(\.[a-zA-Z0-9_]+)+$/;
const litKeys = new Set();
function walk(dir) {
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, ent.name);
    if (ent.isDirectory()) walk(p);
    else if (ent.name.endsWith('.jsx') || ent.name.endsWith('.js')) {
      const txt = fs.readFileSync(p, 'utf-8');
      const re = /t\(\s*'([^']+)'\s*\)/g;
      let m;
      while ((m = re.exec(txt))) {
        if (KEY_RE.test(m[1])) litKeys.add(m[1]);
      }
    }
  }
}
walk(base);

const results = {};
for (const l of langs) {
  const missing = [...litKeys].filter(k => !dicts[l].has(k)).sort();
  results[l] = missing;
}

console.log('referenced literal i18n keys:', litKeys.size);
for (const l of langs) {
  console.log(`\n=== MISSING in ${l} (${results[l].length}) ===`);
  for (const k of results[l]) console.log('  ' + k);
}
