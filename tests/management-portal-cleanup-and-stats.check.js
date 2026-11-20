const fs = require('fs');
const path = require('path');
const assert = require('assert');
const vm = require('vm');

console.log('--- Running Management Portal UI Cleanup & Functional Stats Verification ---');

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
      supportEmail: 'mgmt-support@unibuddy.edu'
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
console.log('✓ userAvatar tests passed: Management avatar has executive suit, Student avatar has cap.');

// Test Management Profile View
evalInCtx("S.role = 'management'; S.user = { full_name: 'Director Jane Doe', email: 'director@rishihood.edu.in', role: 'management' };");
const mgmtProfHtml = evalInCtx("managementProfile()");
assert(mgmtProfHtml.includes('Management Directorate') || mgmtProfHtml.includes('Executive Management'), 'Management profile should display executive role');
assert(mgmtProfHtml.includes('director@rishihood.edu.in'), 'Management profile should display email');
assert(mgmtProfHtml.includes('av xxl'), 'Management profile should display circular xxl avatar');
console.log('✓ managementProfile() renders executive profile correctly.');

// Test Management Portal View Routing
const renderedProf = evalInCtx("mgmtPortalView('profile')");
assert(renderedProf.includes('Management Directorate') || renderedProf.includes('Executive Management'), 'mgmtPortalView(profile) must render management profile');

const renderedStats = evalInCtx("mgmtPortalView('x')");
assert(renderedStats.includes('Management Platform Overview'), 'mgmtPortalView(x) must render Management Platform Overview');
assert(renderedStats.includes('Student Body'), 'Management overview must render Student Body KPI card');
assert(renderedStats.includes('Faculty Members'), 'Management overview must render Faculty Members KPI card');
assert(renderedStats.includes('Club Initiatives'), 'Management overview must render Club Initiatives KPI card');
assert(renderedStats.includes('Documents'), 'Management overview must render Documents KPI card');
assert(renderedStats.includes('Broadcast Notices'), 'Management overview must render Broadcast Notices KPI card');
assert(renderedStats.includes('Support Tickets'), 'Management overview must render Support Tickets KPI card');
console.log('✓ mgmtPortalView() renders executive sections and stats view.');

// Test Management Metrics Calculation
const metrics = evalInCtx("getManagementMetrics()");
assert(metrics.students && typeof metrics.students.total === 'number', 'Student metrics must include total count');
assert(metrics.students.breakdown?.batch_year, 'Student metrics must include batch breakdown');
assert(metrics.students.breakdown?.course, 'Student metrics must include course breakdown');
assert(metrics.students.breakdown?.section, 'Student metrics must include section breakdown');
assert(metrics.faculty && typeof metrics.faculty.total === 'number', 'Faculty metrics must include total count');
assert(metrics.clubs && typeof metrics.clubs.total_initiatives === 'number', 'Club metrics must include initiatives count');
assert(metrics.clubs.notes && metrics.clubs.notes.includes('Direct student club membership table is not yet provisioned'), 'Club metrics must note schema membership table status');
assert(metrics.documents && typeof metrics.documents.total === 'number', 'Document metrics must include total count');
assert(metrics.announcements && typeof metrics.announcements.total === 'number', 'Announcement metrics must include total count');
assert(metrics.tickets && typeof metrics.tickets.total === 'number', 'Ticket metrics must include total count');
assert(metrics.platform && metrics.platform.by_role, 'Platform metrics must include roles count');
console.log('✓ getManagementMetrics() calculates complete student, faculty, club, doc, announcement, ticket data.');

// Test Interactive Detail Modals
evalInCtx("S.modal = { type: 'mgmt-detail', section: 'students' };");
const studentModal = evalInCtx("modal()");
assert(studentModal.includes('Student Body Directory'), 'Student modal title must be present');
assert(studentModal.includes('Batch'), 'Student modal must display batch columns');

evalInCtx("S.modal = { type: 'mgmt-detail', section: 'clubs' };");
const clubModal = evalInCtx("modal()");
assert(clubModal.includes('Clubs') && clubModal.includes('Student Initiatives'), 'Club modal title must be present');
assert(clubModal.includes('Database Schema Notice'), 'Club modal must state database schema notice');

evalInCtx("S.modal = { type: 'mgmt-detail', section: 'tickets' };");
const ticketModal = evalInCtx("modal()");
assert(ticketModal.includes('Support Tickets Monitor'), 'Ticket modal title must be present');
console.log('✓ Interactive detail modals (students, clubs, tickets) verified successfully.');

console.log('================================================================');
console.log('ALL MANAGEMENT PORTAL CLEANUP & STATS VERIFICATION CHECKS PASSED!');
console.log('================================================================');
process.exit(0);
