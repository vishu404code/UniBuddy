const fs = require('fs');
const path = require('path');
const assert = require('assert');
const vm = require('vm');

console.log('--- Running Management Portal & Authority Portal Verification ---');

const htmlPath = path.join(__dirname, '..', 'index.html');
const html = fs.readFileSync(htmlPath, 'utf8');

// 1. Static checks on HTML and Configs
console.log('Checking static HTML definitions...');

// Management navigation config
assert(html.includes("management: {"), 'Management role configuration should exist in UNIFIED_ROLES_CONFIG');
const mgmtConfigMatch = html.match(/management:\s*\{[\s\S]*?nav:\s*\[([\s\S]*?)\]\s*\}/);
assert(mgmtConfigMatch, 'Management nav configuration must be parseable');
const mgmtNavContent = mgmtConfigMatch[1];

assert(!mgmtNavContent.includes("'tix'"), 'Tickets section must be removed from Management nav');
assert(!mgmtNavContent.includes("'docs'"), 'Documents section must be removed from Management nav');
assert(!mgmtNavContent.includes("'ann'"), 'Announcements section must be removed from Management nav');
assert(!mgmtNavContent.includes("'help'"), 'Help & Support section must be removed from Management nav');

assert(mgmtNavContent.includes("'x'"), 'Management Stats overview (x) must be present in Management nav');
assert(mgmtNavContent.includes("'profile'"), 'Profile must be present in Management nav');
assert(mgmtNavContent.includes("'settings'"), 'Settings must be present in Management nav');
console.log('✓ Management nav config verified (Tickets, Docs, Announcements, Help & Support removed).');

// Management notification bell removal
assert(html.includes("role === 'management' ? '' : `<div class=\"bw\">"), 'Notification bell must be removed for management in portalHeader');
console.log('✓ Notification bell icon/section successfully removed for Management in portalHeader.');

// Management Avatar and Circular CSS
assert(html.includes("const mgmtAvatar = () =>"), 'mgmtAvatar function must be defined');
assert(html.includes("r === 'management' || r === 'super_admin') return mgmtAvatar()"), 'userAvatarFallback must return mgmtAvatar for management');
assert(html.includes("aspect-ratio:1/1 !important"), 'Circular aspect-ratio rule must be defined');
assert(html.includes(".sp-app .ph .av.xxl{width:104px !important;height:104px !important"), 'Circular xxl profile avatar dimensions must be enforced');
console.log('✓ Executive mgmtAvatar and perfect 1:1 circular CSS rules verified.');

// Authority Avatar definition
assert(html.includes("const authAvatar = () =>"), 'authAvatar function must be defined');
assert(/if\s*\(\s*r\s*===\s*'authority'\s*\)\s*return\s*authAvatar\(\);/.test(html), 'userAvatarFallback must return authAvatar for authority');
console.log('✓ Authority authAvatar function and fallback verified.');

// 2. Behavioral VM execution of portal components
console.log('Executing frontend JS functions in simulated VM sandbox...');

function createMockElement(id = 'mock') {
  return {
    id,
    value: '',
    textContent: '',
    innerHTML: '',
    style: {},
    classList: { add: () => {}, remove: () => {}, toggle: () => {}, contains: () => false },
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => true,
    closest: () => null,
    appendChild: () => {},
    append: () => {},
    querySelectorAll: () => [],
    querySelector: () => null,
    hasChildNodes: () => false,
    focus: () => {},
    scrollIntoView: () => {},
    setAttribute: () => {},
    removeAttribute: () => {}
  };
}

const mockStorage = {};
const sandbox = {
  window: {
    location: { hostname: 'localhost' },
    UB_CONFIG: {
      apiBase: 'http://127.0.0.1:8010/api/v1',
      googleClientId: 'test-client-id.apps.googleusercontent.com',
      supportEmail: 'vishnukumawat6674@gmail.com'
    },
    addEventListener: () => {},
    scrollTo: () => {},
    setInterval: () => {},
    clearInterval: () => {},
    setTimeout: () => {},
    clearTimeout: () => {},
    localStorage: {
      getItem: k => mockStorage[k] || null,
      setItem: (k, v) => { mockStorage[k] = String(v); },
      removeItem: k => { delete mockStorage[k]; }
    }
  },
  document: {
    activeElement: null,
    querySelector: () => createMockElement('el'),
    querySelectorAll: () => [],
    getElementById: () => createMockElement('el'),
    addEventListener: () => {},
    removeEventListener: () => {}
  },
  localStorage: {
    getItem: k => mockStorage[k] || null,
    setItem: (k, v) => { mockStorage[k] = String(v); },
    removeItem: k => { delete mockStorage[k]; }
  },
  console,
  setTimeout: () => 0,
  clearTimeout: () => {},
  setInterval: () => 0,
  clearInterval: () => {},
  navigator: { clipboard: { writeText: async () => {} } },
  fetch: async () => ({ ok: true, status: 200, json: async () => ({}) })
};

// Extract relevant script block from index.html
const scriptMatch = html.match(/<script>([\s\S]*?)<\/script>/i);
assert(scriptMatch, 'script tag must exist in index.html');
const fullScript = scriptMatch[1];

sandbox.window.document = sandbox.document;
sandbox.window.window = sandbox.window;
sandbox.window.self = sandbox.window;
sandbox.global = sandbox;

const ctx = vm.createContext(sandbox);
vm.runInContext(fullScript, ctx);

function evalInCtx(expr) {
  return vm.runInContext(expr, ctx);
}

// Check S object and config
const S = evalInCtx('S');
assert(S, 'Global state S must exist');

// Test portalHeader
const mgmtHeader = evalInCtx("portalHeader('management', 'x', 'ocean')");
assert(!mgmtHeader.includes('id="bl"'), 'Management header must NOT contain #bl bell button');
assert(!mgmtHeader.includes('data-a="sp-bell"'), 'Management header must NOT contain sp-bell action');
assert(!mgmtHeader.includes('data-v="help"'), 'Management user menu must NOT contain Help & Support');
console.log('✓ portalHeader test passed for management: No bell icon, no help item.');

const facultyHeader = evalInCtx("portalHeader('faculty', 'tix', 'ocean')");
assert(facultyHeader.includes('id="bl"'), 'Faculty header MUST contain #bl bell button');
console.log('✓ portalHeader test passed for faculty: Bell icon remains intact.');

// Test userAvatar and fallback
const mgmtSvg = evalInCtx("userAvatar('management', 'sm')");
assert(mgmtSvg.includes('viewBox="0 0 64 64"'), 'Management avatar should be SVG viewBox 0 0 64 64');
assert(mgmtSvg.includes('fill="#0f172a"'), 'Management avatar should have executive suit styling');
assert(!mgmtSvg.includes('M32 9L10 18l22 9 22-9z'), 'Management avatar must NOT contain graduation cap polygon');

const studentSvg = evalInCtx("userAvatar('student', 'sm')");
assert(studentSvg.includes('M32 9L10 18l22 9 22-9z'), 'Student avatar fallback still contains graduation cap');

const authoritySvg = evalInCtx("userAvatar('authority', 'sm')");
assert(authoritySvg.includes('viewBox="0 0 64 64"'), 'Authority avatar should be SVG viewBox 0 0 64 64');
assert(!authoritySvg.includes('M32 9L10 18l22 9 22-9z'), 'Authority avatar must NOT contain student graduation cap');
assert(authoritySvg.includes('fill="#d97706"'), 'Authority avatar has amber tie styling');
console.log('✓ userAvatar tests passed: Management (executive suit), Student (cap), Authority (admin suit, no cap).');

// Test Management Profile View
evalInCtx("S.role = 'management'; S.user = { full_name: 'Director Jane Doe', email: 'director@rishihood.edu.in', role: 'management' };");
const mgmtProfHtml = evalInCtx("managementProfile()");
assert(mgmtProfHtml.includes('Management Directorate') || mgmtProfHtml.includes('Executive Management'), 'Management profile should display executive role');
assert(mgmtProfHtml.includes('director@rishihood.edu.in'), 'Management profile should display email');
assert(mgmtProfHtml.includes('av xxl'), 'Management profile should display circular xxl avatar');
console.log('✓ managementProfile() renders executive profile correctly.');

// Test PART A: Management Statistics Redesign (5 Exact Sections)
evalInCtx(`
S.role = 'management';
S.analytics = {
  questions_total: 156,
  questions_by_day: [
    { day: '2026-11-18', count: 12 },
    { day: '2026-11-19', count: 18 },
    { day: '2026-11-20', count: 25 }
  ],
  tickets_by_day: [
    { day: '2026-11-18', count: 5 },
    { day: '2026-11-19', count: 7 },
    { day: '2026-11-20', count: 4 }
  ],
  ticket_totals: {
    total_tickets: 42,
    resolved_tickets: 38,
    resolution_rate: 0.9047,
    avg_first_response_hours: 2.4,
    campuses: [
      { name: 'Newton Campus', total_tickets: 24, resolved_tickets: 22, resolution_rate: 0.916, avg_first_response_hours: 1.8 },
      { name: 'Rishihood Campus', total_tickets: 18, resolved_tickets: 16, resolution_rate: 0.888, avg_first_response_hours: 3.1 }
    ]
  },
  gemini: {
    rows_recorded: 156,
    requests: 156,
    input_tokens: 38400,
    output_tokens: 12850,
    rows_with_input_tokens: 156,
    rows_with_output_tokens: 156,
    models: ['gemini-1.5-flash'],
    first_recorded_at: '2026-11-01T00:00:00Z'
  }
};
`);

const renderedStats = evalInCtx("mgmtPortalView('x')");
assert(renderedStats.includes('Management Stats'), 'mgmtPortalView(x) must render Management Stats heading');

// Section 1: University Overview with 5 specific cards
assert(renderedStats.includes('University Overview'), 'Section 1 heading University Overview must exist');
assert(renderedStats.includes('Student Body'), 'Section 1 must render Student Body card');
assert(renderedStats.includes('Faculty Members'), 'Section 1 must render Faculty Members card');
assert(renderedStats.includes('Club Initiatives'), 'Section 1 must render Club Initiatives card');
assert(renderedStats.includes('Documents'), 'Section 1 must render Documents card');
assert(renderedStats.includes('Broadcast Notices'), 'Section 1 must render Broadcast Notices card');

// Section 2: Platform Activity Summary
assert(renderedStats.includes('Platform Activity'), 'Section 2 heading Platform Activity must exist');
assert(renderedStats.includes('Questions asked'), 'Section 2 must render Questions asked');
assert(renderedStats.includes('Tickets'), 'Section 2 must render Tickets');
assert(renderedStats.includes('Resolved'), 'Section 2 must render Resolved');
assert(renderedStats.includes('Resolution rate'), 'Section 2 must render Resolution rate');
assert(renderedStats.includes('Avg first response'), 'Section 2 must render Avg first response');

// Section 3: Daily Activity Charts
assert(renderedStats.includes('Daily Activity'), 'Section 3 heading Daily Activity must exist');
assert(renderedStats.includes('Questions per day (last 30 days)'), 'Section 3 must render Questions per day chart');
assert(renderedStats.includes('Tickets per day (last 30 days)'), 'Section 3 must render Tickets per day chart');

// Section 4: Campus-Wise Analytics
assert(renderedStats.includes('By Campus'), 'Section 4 heading By Campus must exist');
assert(renderedStats.includes('Newton Campus'), 'Section 4 must render campus rows');
assert(renderedStats.includes('Rishihood Campus'), 'Section 4 must render campus rows');

// Section 5: Gemini Answer Usage
assert(renderedStats.includes('Gemini answer usage'), 'Section 5 heading Gemini answer usage must exist');
assert(renderedStats.includes('Answer calls recorded'), 'Section 5 must render Answer calls recorded');
assert(renderedStats.includes('Input tokens'), 'Section 5 must render Input tokens');
assert(renderedStats.includes('Output tokens'), 'Section 5 must render Output tokens');
console.log('✓ Management Stats 5 sections (Overview, Platform Activity, Daily Activity, By Campus, Gemini Usage) verified successfully.');

// Test PART B: Authority Portal Profile & Help & Support
evalInCtx("S.role = 'authority'; S.user = { full_name: 'Registrar John Smith', email: 'authority@unibuddy.edu', role: 'authority', department: 'Academic Affairs' };");

const authProfHtml = evalInCtx("authorityProfile()");
assert(authProfHtml.includes('Authority'), 'Authority profile must display Authority role');
assert(authProfHtml.includes('Registrar John Smith'), 'Authority profile must display full name');
assert(authProfHtml.includes('authority@unibuddy.edu'), 'Authority profile must display email');
assert(authProfHtml.includes('av xxl'), 'Authority profile must render circular XXL avatar');
console.log('✓ authorityProfile() renders Authority profile with circular XXL avatar & credentials.');

const authHelpHtml = evalInCtx("authorityHelp()");
assert(authHelpHtml.includes('vishnukumawat6674@gmail.com'), 'Authority Help & Support must display target support email vishnukumawat6674@gmail.com');
assert(authHelpHtml.includes('mail.google.com/mail/?view=cm'), 'Authority Help & Support must link to Gmail compose interface');
assert(authHelpHtml.includes('UniBuddy%20Authority%20Portal%20Support%20Request'), 'Authority Help & Support Gmail link must prefill subject');
console.log('✓ authorityHelp() renders Help & Support with vishnukumawat6674@gmail.com and Gmail compose link.');

const renderedAuthProf = evalInCtx("authorityPortalView('profile')");
assert(renderedAuthProf.includes('Registrar John Smith'), 'authorityPortalView(profile) routes to authorityProfile');

const renderedAuthHelp = evalInCtx("authorityPortalView('help')");
assert(renderedAuthHelp.includes('vishnukumawat6674@gmail.com'), 'authorityPortalView(help) routes to authorityHelp');
console.log('✓ authorityPortalView() routing for profile and help verified.');

console.log('================================================================');
console.log('ALL MANAGEMENT & AUTHORITY PORTAL VERIFICATION CHECKS PASSED!');
console.log('================================================================');
process.exit(0);
