const fs = require('fs');
const path = require('path');
const assert = require('assert');
const vm = require('vm');

const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');

// Extract script
const scriptMatch = html.match(/<script>([\s\S]*?)<\/script>\s*<\/body>/i);
assert.ok(scriptMatch, 'Main script block found');
const scriptContent = scriptMatch[1];

const mockStorage = {};
function createMockElement(id = '', tag = 'div') {
  return {
    id,
    tagName: tag.toUpperCase(),
    innerHTML: '',
    textContent: '',
    value: '',
    files: [],
    dataset: {},
    classList: {
      add: () => {},
      remove: () => {},
      contains: () => false,
      toggle: () => {}
    },
    style: {},
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

const mockApp = createMockElement('app');

const sandbox = {
  window: {
    location: { hostname: 'localhost' },
    UB_CONFIG: {
      apiBase: 'http://127.0.0.1:8010/api/v1',
      googleClientId: 'test-client-id.apps.googleusercontent.com',
      supportEmail: 'support@unibuddy.edu'
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
    },
    google: {
      accounts: {
        id: {
          initialize: () => {},
          renderButton: () => {},
          prompt: () => {}
        }
      }
    }
  },
  document: {
    createElement: tag => createMockElement('', tag),
    getElementById: id => (id === 'app' ? mockApp : createMockElement(id)),
    querySelector: sel => {
      if (sel === '#app') return mockApp;
      return createMockElement(sel.replace(/^[#.]/, ''));
    },
    querySelectorAll: () => [],
    addEventListener: () => {}
  },
  navigator: { userAgent: 'NodeTest', clipboard: { writeText: async () => {} } },
  URL: { createObjectURL: () => 'blob:mock-url', revokeObjectURL: () => {} },
  localStorage: {
    getItem: k => mockStorage[k] || null,
    setItem: (k, v) => { mockStorage[k] = String(v); },
    removeItem: k => { delete mockStorage[k]; }
  },
  console,
  setTimeout,
  clearTimeout,
  setInterval,
  clearInterval,
  Date,
  Math,
  JSON,
  Array,
  Object,
  Promise,
  performance: { now: () => Date.now() },
  encodeURIComponent,
  decodeURIComponent,
  fetch: () => Promise.resolve({ ok: true, json: () => Promise.resolve({}) })
};

sandbox.window.document = sandbox.document;
sandbox.window.window = sandbox.window;
sandbox.window.self = sandbox.window;
sandbox.global = sandbox;

const ctx = vm.createContext(sandbox);
vm.runInContext(scriptContent, ctx);

function evalInCtx(expr) {
  return vm.runInContext(expr, ctx);
}

console.log('Testing Faculty Publish Improvements and Ticket Notifications...\n');

// 1. Academic Targeting Constants & Mappings
console.log('--- Test 1: Academic Options & Dynamic Section Mapping ---');
const UB_COURSES = evalInCtx('UB_COURSES');
const UB_BATCH_YEARS = evalInCtx('UB_BATCH_YEARS');
const getSectionsForCourse = evalInCtx('getSectionsForCourse');

assert.ok(Array.isArray([...UB_COURSES]), 'UB_COURSES array defined');
assert.deepStrictEqual([...UB_BATCH_YEARS], ['2023', '2024', '2025', '2026'], 'Batch years defined exactly as 2023, 2024, 2025, 2026');

const csAiSections = getSectionsForCourse('CS and AI');
assert.deepStrictEqual([...csAiSections], ['Section A', 'Section B', 'Section C', 'Section D'], 'CS and AI sections match Section A-D');

const csDsSections = getSectionsForCourse('CS and DS');
assert.deepStrictEqual([...csDsSections], ['Section 1', 'Section 2', 'Section 3', 'Section 4', 'Section 5'], 'CS and DS sections match Section 1-5');

const designSections = getSectionsForCourse('Design');
assert.deepStrictEqual([...designSections], ['Section 1', 'Section 2', 'Section 3', 'Section 4', 'Section 5'], 'Design sections match Section 1-5');

const bbaSections = getSectionsForCourse('BBA');
assert.deepStrictEqual([...bbaSections], ['Section 1', 'Section 2', 'Section 3', 'Section 4', 'Section 5'], 'BBA sections match Section 1-5');

assert.deepStrictEqual([...getSectionsForCourse('NonExistent')], [], 'Unknown course has empty sections');
console.log('✓ Course and Dynamic Section mappings are 100% correct.');

// 2. Publish Forms: Academic Year Removed, Dynamic Controls Available
console.log('\n--- Test 2: Publish Section: Academic Year Removed, Batch/Course/Section Present ---');
evalInCtx("S.role = 'faculty'; S.pubType = 'pdf'; S.pubCourse = ''; S.pubSection = ''; S.pubBatch = '';");

const pdfHtml = evalInCtx('publishView()');
assert.ok(!pdfHtml.includes('Academic year'), 'Academic year is NOT present in PDF publishing form');
assert.ok(!pdfHtml.includes('id="pf-acad"'), 'pf-acad select is NOT present in PDF publishing form');
assert.ok(pdfHtml.includes('id="pf-batch"'), 'pf-batch select is present');
assert.ok(pdfHtml.includes('id="pf-course"'), 'pf-course select is present');
assert.ok(pdfHtml.includes('id="pf-section"'), 'pf-section select is present');
assert.ok(pdfHtml.includes('Select Batch Year'), 'Placeholder "Select Batch Year" is present');
assert.ok(pdfHtml.includes('Select Course'), 'Placeholder "Select Course" is present');
assert.ok(pdfHtml.includes('Select Section'), 'Placeholder "Select Section" is present');
assert.ok(pdfHtml.includes('disabled'), 'Section dropdown is disabled when no course is chosen');

evalInCtx("S.pubType = 'announcement';");
const annHtml = evalInCtx('publishView()');
assert.ok(!annHtml.includes('Academic year'), 'Academic year is NOT present in Announcement publishing form');
assert.ok(!annHtml.includes('id="pf-acad"'), 'pf-acad select is NOT present in Announcement publishing form');
assert.ok(annHtml.includes('id="pf-batch"'), 'pf-batch select is present in Announcement publishing form');
assert.ok(annHtml.includes('id="pf-course"'), 'pf-course select is present in Announcement publishing form');
assert.ok(annHtml.includes('id="pf-section"'), 'pf-section select is present in Announcement publishing form');
console.log('✓ Academic Year completely removed; Batch, Course, Section properly rendered.');

// 3. Dynamic Section Options on Course Selection
console.log('\n--- Test 3: Dynamic Section Dropdown Updates ---');
evalInCtx("S.pubCourse = 'CS and AI';");
const csAiFormHtml = evalInCtx('publishView()');
assert.ok(!csAiFormHtml.includes('disabled required><option value="">Select Section</option></select>'), 'Section dropdown is not disabled when CS and AI is chosen');
assert.ok(csAiFormHtml.includes('Section A') && csAiFormHtml.includes('Section D'), 'Section A-D present for CS and AI');
assert.ok(!csAiFormHtml.includes('Section 5'), 'Numeric Section 5 is NOT present for CS and AI');

evalInCtx("S.pubCourse = 'Design';");
const designFormHtml = evalInCtx('publishView()');
assert.ok(designFormHtml.includes('Section 1') && designFormHtml.includes('Section 5'), 'Section 1-5 present for Design');
assert.ok(!designFormHtml.includes('Section A'), 'Section A is NOT present for Design');
console.log('✓ Dynamic Section options update correctly based on selected Course.');

// 4. Targeted Visibility in Student Portal
console.log('\n--- Test 4: Targeted Visibility in Student Portal ---');
evalInCtx("S.role = 'student'; S.user = { email: 'student@unibuddy.demo', role: 'student', batch_year: '2025', course: 'CS and AI', section: 'Section A' };");
mockStorage['ub_prof'] = JSON.stringify({ batch: '2025', course: 'CS and AI', section: 'Section A' });

const isItemVisibleToStudent = evalInCtx('isItemVisibleToStudent');

const matchedDoc = { uuid: 'd-1', title: 'CS & AI Section A Syllabus', batch_year: 2025, course: 'CS and AI', section: 'Section A' };
const wrongBatchDoc = { uuid: 'd-2', title: 'Batch 2023 Notice', batch_year: 2023, course: 'CS and AI', section: 'Section A' };
const wrongCourseDoc = { uuid: 'd-3', title: 'Design Handbook', batch_year: 2025, course: 'Design', section: 'Section 1' };
const wrongSectionDoc = { uuid: 'd-4', title: 'CS & AI Section B Notice', batch_year: 2025, course: 'CS and AI', section: 'Section B' };
const untargetedDoc = { uuid: 'd-5', title: 'General University Policy' };

assert.strictEqual(isItemVisibleToStudent(matchedDoc), true, 'Matched doc is visible to student');
assert.strictEqual(isItemVisibleToStudent(wrongBatchDoc), false, 'Wrong batch doc is hidden from student');
assert.strictEqual(isItemVisibleToStudent(wrongCourseDoc), false, 'Wrong course doc is hidden from student');
assert.strictEqual(isItemVisibleToStudent(wrongSectionDoc), false, 'Wrong section doc is hidden from student');
assert.strictEqual(isItemVisibleToStudent(untargetedDoc), true, 'Untargeted general doc is visible to student');

const matchedAnn = { id: 'a-1', title: 'CS & AI Exam Alert', batch_year: 2025, course: 'CS and AI', section: 'Section A' };
const wrongAnn = { id: 'a-2', title: 'BBA Notice', batch_year: 2024, course: 'BBA', section: 'Section 2' };
const generalAnn = { id: 'a-3', title: 'Campus Holiday Announcement' };

assert.strictEqual(isItemVisibleToStudent(matchedAnn), true, 'Targeted announcement matching student is visible');
assert.strictEqual(isItemVisibleToStudent(wrongAnn), false, 'Announcement targeted to other course/batch is hidden');
assert.strictEqual(isItemVisibleToStudent(generalAnn), true, 'General announcement is visible to student');

// Non-student role sees everything
evalInCtx("S.role = 'faculty';");
assert.strictEqual(isItemVisibleToStudent(wrongAnn), true, 'Faculty can see all announcements');
assert.strictEqual(isItemVisibleToStudent(wrongCourseDoc), true, 'Faculty can see all documents');
console.log('✓ Targeted visibility correctly differentiates students vs staff.');

// 5. Faculty Ticket Notifications
console.log('\n--- Test 5: Faculty Ticket Notifications in Notification Bell ---');
evalInCtx("S.role = 'faculty'; S.spBellOpen = true;");
delete mockStorage['ub_sp_read_tickets'];

const tickets = [
  {
    id: 'UB-201',
    uuid: 't-201',
    subj: 'Lab System Hardware Issue',
    dept: 'Computer Science',
    student_name: 'Aarav Sharma',
    status: 'submitted',
    created_at: new Date(Date.now() - 3600000).toISOString(),
    desc: 'System 14 GPU is overheating during training runs.'
  },
  {
    id: 'UB-202',
    uuid: 't-202',
    subj: 'Urgent Examination Timetable Clash',
    dept: 'Examination Cell',
    student_name: 'Priya Patel',
    status: 'in_progress',
    created_at: new Date(Date.now()).toISOString(),
    desc: 'Two examinations scheduled simultaneously at 10 AM.'
  }
];

evalInCtx(`S.tickets = ${JSON.stringify(tickets)};`);

const headerHtml = evalInCtx("portalHeader('faculty', 'tix', 'light')");
assert.ok(headerHtml.includes('Student Ticket Notifications'), 'Header bell dropdown shows Student Ticket Notifications');
assert.ok(headerHtml.includes('UB-202'), 'Newest ticket UB-202 is present');
assert.ok(headerHtml.includes('UB-201'), 'Ticket UB-201 is present');
assert.ok(headerHtml.indexOf('UB-202') < headerHtml.indexOf('UB-201'), 'Newest ticket appears FIRST (sorted newest first)');
assert.ok(headerHtml.includes('Priya Patel'), 'Student name Priya Patel displayed');
assert.ok(headerHtml.includes('Examination Cell'), 'Department Examination Cell displayed');
assert.ok(headerHtml.includes('Urgent Examination Timetable Clash'), 'Subject displayed');
assert.ok(headerHtml.includes('Two examinations scheduled simultaneously'), 'Preview description displayed');
assert.ok(headerHtml.includes('data-a="open-tix-notif"'), 'Card has open-tix-notif action');
assert.ok(headerHtml.includes('New'), 'Unread badge displayed on card');

// Mark ticket as read
evalInCtx("spMarkTicketRead('t-202');");
const readTickets = evalInCtx('spReadTicketsSet()');
assert.ok(readTickets.includes('t-202'), 't-202 successfully marked as read');

const updatedHeaderHtml = evalInCtx("portalHeader('faculty', 'tix', 'light')");
assert.ok(updatedHeaderHtml.includes('1 unread'), 'Unread count updated to 1');
console.log('✓ Faculty Ticket Notifications verified with correct details, sorting, and read state.');

console.log('\n======================================================');
console.log('ALL FACULTY PUBLISH & TICKET NOTIFICATION TESTS PASSED!');
console.log('======================================================');
process.exit(0);
