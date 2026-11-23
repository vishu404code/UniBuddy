const fs = require('fs');
const assert = require('assert');
const vm = require('vm');

console.log('Testing Internal Portals Dark Theme (Landing Page Theme)...');

const html = fs.readFileSync('index.html', 'utf8');

// 1. Verify CSS tokens for dark theme
console.log('--- Step 1: Checking CSS design tokens ---');
assert(html.includes(':root{--bg:#141413'), ':root must have dark background #141413');
assert(html.includes('--bd:#34322e'), ':root must use dark borders #34322e');
assert(html.includes('--ink:#faf9f5') || html.includes('--tx:#faf9f5'), 'Must use landing page text color #faf9f5');

// Verify .sp-app dark theme variables
assert(html.includes('.sp-app {'), '.sp-app definition must exist');
assert(html.includes('--bg:#141413') || html.includes('--bg: #141413'), '.sp-app must have dark background #141413');
assert(html.includes('--tx:#faf9f5') || html.includes('--tx: #faf9f5'), '.sp-app text must be #faf9f5');
assert(html.includes('--ac:#4a7cf7') || html.includes('--ac: #4a7cf7'), '.sp-app accent must be landing page blue #4a7cf7');
assert(html.includes('color-scheme:dark') || html.includes('color-scheme: dark'), '.sp-app must have dark color-scheme');
console.log('✓ Dark theme variables and design tokens verified.');

// 2. Verify component dark styles
console.log('--- Step 2: Checking component dark styling ---');
assert(html.includes('.sp-app aside{width:272px;flex:none;background:var(--bg-aside)'), 'Sidebar must have dark background');
assert(html.includes('.sp-app .mn{flex:1;min-width:0;display:flex;flex-direction:column;background:var(--bg-page)'), 'Main portal view must have dark background');
assert(html.includes('header#tp{display:flex;align-items:center;gap:12px;padding:12px 24px;border-bottom:1px solid var(--bd);background:var(--bg-header)'), 'Header must have dark background');
assert(html.includes('.sp-app .card{background:var(--bg-card)'), 'Cards must have dark card background');
assert(html.includes('.sp-app table{width:100%;border-collapse:collapse;font-size:14px;color:#dedbcf}'), 'Tables must have dark-theme text color');
assert(html.includes('.sp-app th{text-align:left;font-size:12px;font-weight:700;color:var(--mu);padding:12px 14px;background:#242321'), 'Table headers must have dark surface');
assert(html.includes('.sp-app input,.sp-app textarea,.sp-app select{width:100%;font:inherit;color:var(--tx);background:#181716'), 'Inputs must have dark surface #181716');
assert(html.includes('.modal{width:100%;max-width:490px;max-height:92vh;overflow:auto;background:#1e1d1b'), 'Modals must have dark surface #1e1d1b');
assert(html.includes('.ov{position:fixed;inset:0;background:rgba(0,0,0,.72)'), 'Overlay backdrop must be dark rgba(0,0,0,.72)');
console.log('✓ Sidebar, header, cards, tables, inputs, and modals verified in dark theme.');

// 3. Verify that all 4 portals render cleanly in simulated JS environment
console.log('--- Step 3: Verifying all 4 portals render in dark theme ---');

function createMockEl(id = '', tag = 'div') {
  return {
    id,
    tagName: tag.toUpperCase(),
    value: '',
    checked: false,
    innerHTML: '',
    textContent: '',
    style: {},
    classList: {
      add: () => {},
      remove: () => {},
      toggle: () => {},
      contains: () => false
    },
    addEventListener: () => {},
    removeEventListener: () => {},
    setAttribute: () => {},
    getAttribute: () => null,
    focus: () => {}
  };
}

const mockApp = createMockEl('app');

const mockDom = {
  document: {
    querySelector: sel => (sel === '#app' ? mockApp : createMockEl(sel.replace('#', ''))),
    querySelectorAll: () => [],
    getElementById: id => (id === 'app' ? mockApp : createMockEl(id)),
    createElement: tag => createMockEl('', tag),
    activeElement: null,
    hidden: false,
    addEventListener: () => {},
    removeEventListener: () => {}
  },
  window: {
    addEventListener: () => {},
    removeEventListener: () => {},
    localStorage: {
      getItem: () => null,
      setItem: () => {},
      removeItem: () => {}
    },
    location: { hostname: 'localhost' }
  },
  localStorage: {
    getItem: () => null,
    setItem: () => {},
    removeItem: () => {}
  },
  performance: { now: () => 1000 },
  requestAnimationFrame: () => 1,
  cancelAnimationFrame: () => {},
  setInterval: () => 1,
  clearInterval: () => {},
  setTimeout: () => 1,
  clearTimeout: () => {},
  console: console
};

const scriptStart = html.indexOf('<script>');
const scriptEnd = html.lastIndexOf('</script>');
const scriptCode = html.slice(scriptStart + 8, scriptEnd);

const ctx = vm.createContext(mockDom);
vm.runInContext(scriptCode, ctx);

function evalInCtx(expr) {
  return vm.runInContext(expr, ctx);
}

// Test Student Portal
evalInCtx("S.scr = 'app'; S.role = 'student'; S.view = 'chat';");
const stuChat = evalInCtx("student()");
assert(stuChat.includes('class="app sp-app"'), 'Student portal must render with .sp-app');
assert(stuChat.includes('Assist You'), 'Student portal chat greeting must exist');

evalInCtx("S.view = 'docs';");
const stuDocs = evalInCtx("student()");
assert(stuDocs.includes('Documents') && stuDocs.includes('All Documents'), 'Student documents must render');

evalInCtx("S.view = 'queries';");
const stuQueries = evalInCtx("student()");
assert(stuQueries.includes('My Queries'), 'Student queries must render');

console.log('✓ Student Portal views verified.');

// Test Faculty Portal
evalInCtx("S.role = 'faculty'; S.view = 'tix';");
const facTix = evalInCtx("faculty()");
assert(facTix.includes('Faculty Tickets'), 'Faculty tickets must render');

evalInCtx("S.view = 'publish';");
const facPub = evalInCtx("faculty()");
assert(facPub.includes('Publish') && facPub.includes('PDF document'), 'Faculty publish must render');

console.log('✓ Faculty Portal views verified.');

// Test Authority Portal
evalInCtx("S.role = 'authority'; S.view = 'x';");
const authView = evalInCtx("placeholder()");
assert(authView.includes('Authority Portal'), 'Authority portal must render');

console.log('✓ Authority Portal views verified.');

// Test Management Portal
evalInCtx("S.role = 'management'; S.view = 'x';");
const mgmtView = evalInCtx("placeholder()");
assert(mgmtView.includes('Management Stats'), 'Management stats must render');
assert(!mgmtView.includes('University Overview'), 'University Overview must be removed');
assert(mgmtView.includes('Platform Activity') && mgmtView.includes('Questions asked'), 'Management platform activity must render');
assert(mgmtView.includes('Answer calls recorded'), 'Gemini AI analytics must render');

console.log('✓ Management Portal views verified.');

console.log('\n======================================================');
console.log('ALL INTERNAL PORTALS DARK THEME TESTS PASSED PERFECTLY!');
console.log('======================================================');
