const fs = require('fs');
const path = require('path');
const assert = require('assert');

console.log('Testing UniBuddy Login Page Dark Theme Conversion...');

// 1. Verify standalone login.html
console.log('--- Step 1: Checking standalone login.html ---');
const loginHtml = fs.readFileSync(path.join(__dirname, '..', 'login.html'), 'utf8');

assert(loginHtml.includes('color-scheme:dark;'), 'login.html must have color-scheme:dark');
assert(loginHtml.includes('--bg:#141413;'), 'login.html must have --bg:#141413');
assert(loginHtml.includes('--card:#201f1d;'), 'login.html must have --card:#201f1d');
assert(loginHtml.includes('--ink:#faf9f5;'), 'login.html must have --ink:#faf9f5');
assert(loginHtml.includes('--muted:#a6a39b;'), 'login.html must have --muted:#a6a39b');
assert(loginHtml.includes('--line:#34322e;'), 'login.html must have --line:#34322e');
assert(loginHtml.includes('--blue:#4a7cf7;'), 'login.html must have --blue:#4a7cf7');

// Verify .side has dark background and light text
assert(loginHtml.includes('.side{'), 'login.html must define .side');
assert(loginHtml.includes('background:var(--card);'), '.side must use background:var(--card)');

// Verify Google button styling
assert(loginHtml.includes('.gbtn{'), 'login.html must define .gbtn');
assert(loginHtml.includes('background:#242321;'), '.gbtn must have dark background');
assert(loginHtml.includes('color:var(--ink);'), '.gbtn must have light ink color');

// Verify input fields
assert(loginHtml.includes('input[type=email],input[type=password],input[type=text]'), 'Input fields must be styled');
assert(loginHtml.includes('background:#181716;'), 'Input fields must have dark background #181716');
assert(loginHtml.includes('input::placeholder'), 'Input placeholder must be styled');
assert(loginHtml.includes('#78756d'), 'Input placeholder color must be #78756d');

// Verify demo pills
assert(loginHtml.includes('.demo-pills .btn'), 'Demo pills must be styled');
assert(loginHtml.includes('background:#242321;'), 'Demo pills must have dark background');

// Verify primary button & link
assert(loginHtml.includes('.btn.pri{background:var(--blue);color:#ffffff;'), 'Primary button must use blue accent and white text');
assert(loginHtml.includes('.link{background:none;border:0;color:var(--bink);'), 'Links must use blue accent');

console.log('✓ Standalone login.html verified successfully.');

// 2. Verify SPA login in index.html
console.log('--- Step 2: Checking SPA login in index.html ---');
const indexHtml = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');

assert(indexHtml.includes('.ub-login {'), 'index.html must define .ub-login');
assert(indexHtml.includes('color-scheme: dark;'), 'index.html must have color-scheme: dark');
assert(indexHtml.includes('--bg: #141413;'), 'index.html must have --bg: #141413');
assert(indexHtml.includes('--card: #201f1d;'), 'index.html must have --card: #201f1d');
assert(indexHtml.includes('--ink: #faf9f5;'), 'index.html must have --ink: #faf9f5');
assert(indexHtml.includes('--line: #34322e;'), 'index.html must have --line: #34322e');

console.log('✓ SPA login in index.html verified successfully.');

// 3. Verify server serves login.html
console.log('--- Step 3: Checking server.js routing ---');
const serverJs = fs.readFileSync(path.join(__dirname, '..', 'server.js'), 'utf8');
assert(serverJs.includes('login.html'), 'server.js should support login.html');
console.log('✓ server.js routing verified.');

console.log('\n======================================================');
console.log('ALL LOGIN PAGE DARK THEME CONVERSION CHECKS PASSED!');
console.log('======================================================');

