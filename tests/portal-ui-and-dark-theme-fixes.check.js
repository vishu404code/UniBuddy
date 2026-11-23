const fs = require('fs');
const path = require('path');
const assert = require('assert');
const vm = require('vm');

console.log('Testing UniBuddy Critical UI Fixes & Dark Theme Consistency...');

const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');

// 1. Verify Login Page Dark Theme
console.log('--- Step 1: Checking Login Page Dark Theme CSS ---');
assert(html.includes('.ub-login {'), 'Login page styles must exist');
assert(html.includes('--bg: #141413;'), 'Login page must have dark canvas --bg #141413');
assert(html.includes('--card: #201f1d;'), 'Login page must have dark card --card #201f1d');
assert(html.includes('--ink: #faf9f5;'), 'Login page must have light ink --ink #faf9f5');
assert(html.includes('--line: #34322e;'), 'Login page must have dark border --line #34322e');
assert(html.includes('color-scheme: dark;'), 'Login page must declare color-scheme: dark');
console.log('✓ Login Page Dark Theme CSS verified.');

// 2. Verify AI Assistant Suggestion Chips
console.log('--- Step 2: Checking AI Assistant Suggestion Chips Styling ---');
assert(html.includes('.sp-app .chip') || html.includes('.sp-app button.chip'), 'AI assistant suggestion chips must be styled in .sp-app');
assert(html.includes('background:#242321 !important') || html.includes('background: #242321'), 'Suggestion buttons must have dark background');
assert(html.includes('color:#faf9f5 !important') || html.includes('color: #faf9f5'), 'Suggestion buttons must have high contrast text');
console.log('✓ AI Assistant Suggestion Chips dark styling verified.');

// 3. Verify .hd Transparent Heading Rules
console.log('--- Step 3: Checking Transparent Headings in Portals ---');
assert(html.includes('.sp-app .hd, .sp-app #view .hd'), 'Transparent heading selector must exist');
assert(html.includes('background:transparent !important;') || html.includes('background:transparent !important'), 'Heading background must be transparent');
assert(html.includes('border:none !important') || html.includes('border:none !important;'), 'Heading borders must be removed');
console.log('✓ Unwanted white rectangular boundary eliminated.');

// 4. Verify Status Dropdown Dark Theme
console.log('--- Step 4: Checking Ticket Status Dropdown Styling ---');
assert(!html.includes('id="qfl" aria-label="Filter status" style="width:auto;min-width:130px;padding:8px 12px;border-radius:10px;border:1px solid var(--bd);background:#ffffff;font-size:14px"'), 'Inline background:#ffffff on qfl must be removed');
assert(html.includes('select#qfl'), 'select#qfl custom dark styles must exist');
console.log('✓ Ticket Status Dropdown dark theme verified.');

// 5. Verify Academic Year Removed from filterBar
console.log('--- Step 5: Checking Academic Year in Documents & Announcements ---');
const filterBarMatch = html.match(/function filterBar\(kind\)\{[\s\S]*?return `<div class="card filters">([\s\S]*?)<\/div>`;/);
assert(filterBarMatch, 'filterBar function must exist');
assert(!filterBarMatch[1].includes('Academic year'), 'Academic year must be removed from filterBar');
console.log('✓ Academic Year removed from filterBar.');

// 6. Test runtime portal rendering in VM
console.log('--- Step 6: Verifying Runtime Rendering in VM ---');
const sMatch = html.match(/<script>([\s\S]*?)<\/script>\s*<\/body>\s*<\/html>/i);
assert(sMatch, 'Main script must exist');
const scriptCode = sMatch[1];

const mockDom = {
  console,
  setTimeout: (fn, ms) => setTimeout(fn, 0),
  setInterval: () => 1,
  clearInterval: () => {},
  clearTimeout: () => {},
  Date, Math, String, Number, Boolean, Array, Object, JSON, RegExp,
  localStorage: {
    data: {},
    getItem(k) { return this.data[k] || null; },
    setItem(k, v) { this.data[k] = String(v); },
    removeItem(k) { delete this.data[k]; }
  },
  window: {
    location: { hash: '', search: '', pathname: '/' },
    addEventListener: () => {},
    innerWidth: 1200,
    innerHeight: 800
  },
  document: {
    readyState: 'complete',
    getElementById: id => ({ id, innerHTML: '', querySelectorAll: () => [], addEventListener: () => {}, appendChild: () => {} }),
    querySelector: sel => ({ innerHTML: '', style: {}, addEventListener: () => {} }),
    querySelectorAll: () => [],
    addEventListener: () => {},
    title: 'UniBuddy'
  },
  location: { hash: '', search: '', pathname: '/' }
};
mockDom.window.document = mockDom.document;
mockDom.window.localStorage = mockDom.localStorage;

const ctx = vm.createContext(mockDom);
vm.runInContext(scriptCode, ctx);

function evalInCtx(expr) {
  return vm.runInContext(expr, ctx);
}

// Student Chat view
evalInCtx("S.scr = 'app'; S.role = 'student'; S.view = 'chat';");
const stuChat = evalInCtx("student()");
assert(stuChat.includes('sp-app'), 'Student app must render');
assert(stuChat.includes('Academic Timetable'), 'Academic Timetable chip must render');
assert(stuChat.includes('Examination Information'), 'Examination Information chip must render');
assert(stuChat.includes('Scholarships'), 'Scholarships chip must render');
assert(stuChat.includes('Campus Facilities'), 'Campus Facilities chip must render');
console.log('✓ Student AI Assistant suggestion chips verified.');

// Management Stats view
evalInCtx("S.role = 'management'; S.view = 'x';");
const mgmtView = evalInCtx("placeholder()");
assert(mgmtView.includes('Management Stats'), 'Management Stats heading must render');
assert(!mgmtView.includes('University Overview'), 'University Overview section must NOT render');
assert(!mgmtView.includes('Student Body'), 'Student Body card must NOT render');
assert(!mgmtView.includes('Faculty Members'), 'Faculty Members card must NOT render');
assert(!mgmtView.includes('Club Initiatives'), 'Club Initiatives card must NOT render');
assert(!mgmtView.includes('Broadcast Notices'), 'Broadcast Notices card must NOT render');
assert(mgmtView.includes('Platform Activity'), 'Platform Activity section must render');
assert(mgmtView.includes('Daily Activity'), 'Daily Activity section must render');
assert(mgmtView.includes('By Campus'), 'By Campus section must render');
console.log('✓ Management Stats: University Overview completely removed, other sections intact.');

// Faculty Staff Overview
evalInCtx("S.role = 'faculty'; S.view = 'fdash';");
const facDash = evalInCtx("faculty()");
assert(facDash.includes('Staff Overview'), 'Staff Overview heading must render');
assert(facDash.includes('Open Tickets'), 'Staff overview cards must render');
console.log('✓ Faculty Staff Overview verified.');

// Authority Campus Overview
evalInCtx("S.role = 'authority'; S.view = 'x';");
const authDash = evalInCtx("placeholder()");
assert(authDash.includes('Authority Portal'), 'Authority portal heading must render');
assert(authDash.includes('Campus Escalation Queue'), 'Campus escalation queue must render');
console.log('✓ Authority Campus Overview verified.');

console.log('\n=============================================================');
console.log('ALL CRITICAL UI & DARK THEME CONSISTENCY VERIFICATIONS PASSED!');
console.log('=============================================================');

