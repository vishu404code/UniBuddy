const fs = require('fs');
const path = require('path');
const assert = require('assert');
const vm = require('vm');

console.log('--- Running Student, Faculty & Authority Portal Fixes Verification ---');

const htmlPath = path.join(__dirname, '..', 'index.html');
const html = fs.readFileSync(htmlPath, 'utf8');

// Set up VM mock environment
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
    location: { hostname: 'localhost', hash: '' },
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

sandbox.window.document = sandbox.document;
sandbox.window.window = sandbox.window;
sandbox.window.self = sandbox.window;
sandbox.global = sandbox;

const scriptMatch = html.match(/<script>([\s\S]*?)<\/script>/i);
assert(scriptMatch, 'script tag must exist in index.html');
const fullScript = scriptMatch[1];

const ctx = vm.createContext(sandbox);
vm.runInContext(fullScript, ctx);

function evalInCtx(expr) {
  return vm.runInContext(expr, ctx);
}

// -------------------------------------------------------------
// TEST 1: STUDENT PORTAL — REMOVE RAISE QUERY FROM MY QUERY
// -------------------------------------------------------------
console.log('Testing Requirement 1: Remove Raise Query from My Query...');

evalInCtx(`
S.role = 'student';
S.view = 'queries';
S.tickets = [
  { id: 'UB-101', uuid: 'u-101', subj: 'Hostel WiFi issue', dept: 'IT Services', fac: 'Prof A', date: '2026-11-20', pri: 'high', status: 'submitted' },
  { id: 'UB-102', uuid: 'u-102', subj: 'Grade correction request', dept: 'Examinations', fac: 'Dr B', date: '2026-11-19', pri: 'medium', status: 'resolved' }
];
S.fq = '';
S.fs = 'All';
`);

const studentQueriesHtml = evalInCtx('studentQueries()');

// Assert Raise query button is completely absent
assert(!studentQueriesHtml.includes('open-new-query'), 'studentQueries must NOT contain data-a="open-new-query"');
assert(!studentQueriesHtml.includes('+ Raise query'), 'studentQueries must NOT contain "+ Raise query"');
assert(!studentQueriesHtml.includes('Raise Query'), 'studentQueries must NOT contain "Raise Query"');

// Assert existing ticket list & search controls are preserved
assert(studentQueriesHtml.includes('My Queries'), 'Header title My Queries must exist');
assert(studentQueriesHtml.includes('id="qsr"'), 'Search input #qsr must remain in My Queries');
assert(studentQueriesHtml.includes('id="qfl"'), 'Status filter select #qfl must remain in My Queries');
assert(studentQueriesHtml.includes('UB-101'), 'Existing queries must be rendered in table');
assert(studentQueriesHtml.includes('Hostel WiFi issue'), 'Query subject must be rendered in table');
assert(studentQueriesHtml.includes('UB-102'), 'Resolved queries must be rendered in table');

// Test status filtering in Student My Queries
evalInCtx("S.fs = 'Submitted';");
const filteredSubmitted = evalInCtx('studentQueries()');
assert(filteredSubmitted.includes('UB-101'), 'Submitted query must appear');
assert(!filteredSubmitted.includes('UB-102'), 'Resolved query must be filtered out');

// Test query detail expansion in Student My Queries
evalInCtx(`
S.detail = {
  ticket: { id: 'UB-101', uuid: 'u-101', subj: 'Hostel WiFi issue', pri: 'high', date: '2026-11-20', q: 'WiFi not working in Block B', status: 'submitted', events: [] }
};
`);
const studentDetailHtml = evalInCtx('studentQueries()');
assert(studentDetailHtml.includes('WiFi not working in Block B'), 'Query details must be rendered');
console.log('✓ Requirement 1 verified: Raise Query removed, existing queries, filters & details intact.');

// -------------------------------------------------------------
// TEST 2: STUDENT PORTAL — CONTACT SUPPORT EMAIL IN HELP & SUPPORT
// -------------------------------------------------------------
console.log('Testing Requirement 2: Contact Support email in Help & Support...');

evalInCtx("S.role = 'student'; S.view = 'help';");
const studentHelpHtml = evalInCtx('studentHelp()');

// Check that fake contact form is removed
assert(!studentHelpHtml.includes('id="hs"'), 'Fake subject input #hs must be removed');
assert(!studentHelpHtml.includes('id="hm_"'), 'Fake message textarea #hm_ must be removed');
assert(!studentHelpHtml.includes('id="cp"'), 'Copy address button must be removed');

// Check professional Contact Support button
assert(studentHelpHtml.includes('Contact Support'), 'Contact Support button text must be present');
assert(studentHelpHtml.includes('mail'), 'Mail icon SVG must be rendered in button');

// Check Gmail URL prefill
const expectedRecipient = 'vishnukumawat6674%40gmail.com';
const expectedSubject = 'UniBuddy%20Student%20Portal%20Support%20Request';
const expectedBody = 'Hello%2C%20I%20need%20assistance%20with%20the%20Student%20Portal.';
assert(studentHelpHtml.includes('mail.google.com/mail/?view=cm'), 'Contact Support button must link to Gmail compose');
assert(studentHelpHtml.includes(expectedRecipient), 'Gmail compose URL must target vishnukumawat6674@gmail.com');
assert(studentHelpHtml.includes(expectedSubject), 'Gmail compose URL must have prefilled subject');
assert(studentHelpHtml.includes(expectedBody), 'Gmail compose URL must have prefilled body');
assert(studentHelpHtml.includes('target="_blank"'), 'Gmail link must open in new tab');

// Check privacy protection: email is not exposed as raw visible body text
assert(!studentHelpHtml.includes('Sending to <b'), 'Raw email must not be exposed in visible text');
console.log('✓ Requirement 2 verified: Contact Support button connects to Gmail compose with prefilled details.');

// -------------------------------------------------------------
// TEST 3: FACULTY & AUTHORITY PORTAL — TICKET SEARCH BAR POSITION & FUNCTIONALITY
// -------------------------------------------------------------
console.log('Testing Requirement 3: Ticket Section Search Bar Position & Functionality...');

// Static CSS check for sticky search bar
assert(html.includes('.sp-app .ticket-sticky-bar'), '.ticket-sticky-bar CSS class must be defined');
assert(html.includes('position:sticky;top:0') || html.includes('position: sticky; top: 0') || html.includes('position: -webkit-sticky; position: sticky; top: 0'), 'Sticky top: 0 positioning must be defined');

evalInCtx(`
S.tickets = [
  { id: 'UB-201', ticket_number: 'UB-201', uuid: 'u-201', subj: 'Math assignment doubt', dept: 'Mathematics', fac: 'Prof Gauss', student_name: 'Rahul Sharma', creator_name: 'Rahul Sharma', date: '2026-11-20', pri: 'high', status: 'submitted' },
  { id: 'UB-202', ticket_number: 'UB-202', uuid: 'u-202', subj: 'Lab equipment issue', dept: 'Physics', fac: 'Prof Newton', student_name: 'Priya Patel', creator_name: 'Priya Patel', date: '2026-11-19', pri: 'medium', status: 'in_progress' },
  { id: 'UB-203', ticket_number: 'UB-203', uuid: 'u-203', subj: 'Library card lost', dept: 'Library Services', fac: 'Unassigned', student_name: 'Ananya Verma', creator_name: 'Ananya Verma', date: '2026-11-18', pri: 'low', status: 'resolved' }
];
S.fq = '';
S.fs = 'All';
S.detail = null;
`);

// 3A: Faculty Portal Ticket View Structure
evalInCtx("S.role = 'faculty'; S.view = 'tix';");
const facTixHtml = evalInCtx("facultyView('tix')");
assert(facTixHtml.includes('ticket-header'), 'Faculty ticket view must have ticket-header container');
assert(facTixHtml.includes('Faculty Tickets'), 'Faculty ticket heading must be present');
assert(facTixHtml.includes('ticket-sticky-bar'), 'Faculty ticket view must have ticket-sticky-bar container');
assert(facTixHtml.includes('id="qsr"'), 'Faculty search input #qsr must be inside ticket section');
assert(facTixHtml.includes('id="qfl"'), 'Faculty status select #qfl must be inside ticket section');
assert(facTixHtml.includes('UB-201') && facTixHtml.includes('UB-202') && facTixHtml.includes('UB-203'), 'All tickets rendered');

// 3B: Authority Portal Ticket View Structure
evalInCtx("S.role = 'authority'; S.view = 'tix';");
const authTixHtml = evalInCtx("authorityPortalView('tix')");
assert(authTixHtml.includes('ticket-header'), 'Authority ticket view must have ticket-header container');
assert(authTixHtml.includes('Authority Portal · Tickets'), 'Authority ticket heading must be present');
assert(authTixHtml.includes('ticket-sticky-bar'), 'Authority ticket view must have ticket-sticky-bar container');
assert(authTixHtml.includes('id="qsr"'), 'Authority search input #qsr must be inside ticket section');
assert(authTixHtml.includes('id="qfl"'), 'Authority status select #qfl must be inside ticket section');

// 3C: Search by ticket title
evalInCtx("S.fq = 'assignment';");
let searchRes = evalInCtx('facultyTicketTable()');
assert(searchRes.includes('UB-201'), 'Search by title matches UB-201');
assert(!searchRes.includes('UB-202') && !searchRes.includes('UB-203'), 'Non-matching tickets filtered out');

// 3D: Search by ticket ID
evalInCtx("S.fq = 'UB-202';");
searchRes = evalInCtx('facultyTicketTable()');
assert(searchRes.includes('UB-202'), 'Search by ticket ID matches UB-202');
assert(!searchRes.includes('UB-201'), 'Other tickets filtered out');

// 3E: Search by student name
evalInCtx("S.fq = 'Ananya';");
searchRes = evalInCtx('facultyTicketTable()');
assert(searchRes.includes('UB-203'), 'Search by student name matches UB-203');
assert(!searchRes.includes('UB-201') && !searchRes.includes('UB-202'), 'Other tickets filtered out');

// 3F: Clearing search restores full list
evalInCtx("S.fq = '';");
searchRes = evalInCtx('facultyTicketTable()');
assert(searchRes.includes('UB-201') && searchRes.includes('UB-202') && searchRes.includes('UB-203'), 'Clearing search restores all tickets');

// 3G: Search works alongside status filter
evalInCtx("S.fq = 'Lab'; S.fs = 'In Progress';");
searchRes = evalInCtx('facultyTicketTable()');
assert(searchRes.includes('UB-202'), 'Search and filter combination matches UB-202');

evalInCtx("S.fq = 'Lab'; S.fs = 'Submitted';");
searchRes = evalInCtx('facultyTicketTable()');
assert(!searchRes.includes('UB-202'), 'Status mismatch correctly yields empty list');

// 3H: Opening ticket detail preserves toolbar & structure
evalInCtx(`
S.detail = {
  ticket: S.tickets[0]
};
S.fq = '';
S.fs = 'All';
`);
const facWithDetailHtml = evalInCtx("facultyView('tix')");
assert(facWithDetailHtml.includes('ticket-sticky-bar'), 'Sticky bar remains stable when ticket detail opens');
assert(facWithDetailHtml.includes('ticket-header'), 'Header remains stable when ticket detail opens');
assert(facWithDetailHtml.includes('id="tdetail"'), 'Ticket detail section rendered below');

console.log('✓ Requirement 3 verified: Search bar position fixed with sticky toolbar, multi-criteria search validated.');

console.log('================================================================');
console.log('ALL STUDENT, FACULTY & AUTHORITY PORTAL VERIFICATION CHECKS PASSED!');
console.log('================================================================');
process.exit(0);
