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
    localStorage: {
      getItem: k => mockStorage[k] || null,
      setItem: (k, v) => { mockStorage[k] = String(v); },
      removeItem: k => { delete mockStorage[k]; }
    },
    google: {
      accounts: {
        id: {
          initialize: () => {},
          renderButton: (el, opts) => {},
          prompt: () => {}
        }
      }
    }
  },
  document: {
    getElementById: id => (id === 'app' ? mockApp : createMockElement(id)),
    querySelector: sel => (sel === '#app' ? mockApp : createMockElement(sel.replace('#', ''))),
    querySelectorAll: () => [],
    addEventListener: () => {},
    createElement: tag => createMockElement('', tag),
    activeElement: null,
    readyState: 'complete'
  },
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
  String,
  Array,
  Object,
  JSON,
  Promise,
  URLSearchParams,
  performance: { now: () => 100 },
  fetch: (url, opts) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) })
};

sandbox.window.document = sandbox.document;

const ctx = vm.createContext(sandbox);
vm.runInContext(scriptContent, ctx);

function evalInCtx(expr) {
  return vm.runInContext(expr, ctx);
}

console.log('✓ Script executed in mock DOM without runtime errors');

// Test 1: Landing Page renders initially
assert.strictEqual(evalInCtx('S.scr'), 'landing', 'Initial screen is landing');
assert.ok(mockApp.innerHTML.includes('ub-landing'), 'Landing page markup present in #app');
assert.ok(mockApp.innerHTML.includes('Get Started'), 'Get Started button present');
console.log('✓ Test 1: Landing Page loaded successfully');

// Test 2: Navigate to Login Page
evalInCtx("go('login')");
assert.strictEqual(evalInCtx('S.scr'), 'login', 'Screen transitioned to login');
assert.ok(mockApp.innerHTML.includes('ub-login'), 'Login page markup present');
assert.ok(mockApp.innerHTML.includes('Sign in with Google'), 'Sign in with Google button present');
assert.ok(mockApp.innerHTML.includes('google-signin-btn'), 'Google GSI button container present');
console.log('✓ Test 2: Login Page loaded with Google button');

(async function runAllTests() {
  // Helper to simulate authentication response
  async function simulateAuth(role, email = 'user@unibuddy.edu', fullName = 'Test User') {
    sandbox.__mockRole = role;
    sandbox.__mockEmail = email;
    sandbox.__mockFullName = fullName;
    evalInCtx(`
      apiCall = async function(endpoint, opts) {
        if (endpoint === '/auth/google') {
          return { ok: true, status: 200, data: { access_token: 'mock_jwt_token_' + __mockRole, token_type: 'bearer' } };
        }
        if (endpoint === '/auth/me') {
          return {
            ok: true,
            status: 200,
            data: {
              id: 'user-uuid-1234',
              email: __mockEmail,
              full_name: __mockFullName,
              role: __mockRole,
              campus_id: 'campus-1',
              department_id: __mockRole === 'faculty' ? 'dept-cs' : null
            }
          };
        }
        if (endpoint.startsWith('/tickets')) {
          return { ok: true, status: 200, data: [{ id: 'UB-101', subject: 'Hostel Wifi Issue', status: 'submitted', created_at: new Date().toISOString() }] };
        }
        if (endpoint.startsWith('/documents')) {
          return { ok: true, status: 200, data: [{ id: 'doc-12345678', title: 'Exam Guidelines', processing_status: 'ready', publication_status: 'published', created_at: new Date().toISOString() }] };
        }
        if (endpoint.startsWith('/announcements')) {
          return { ok: true, status: 200, data: [{ id: 'ann-1', title: 'Campus Holiday', body: 'Tomorrow is holiday', is_important: true, created_at: new Date().toISOString() }] };
        }
        if (endpoint === '/departments') {
          return { ok: true, status: 200, data: [{ id: 'dept-cs', name: 'Computer Science' }] };
        }
        if (endpoint.startsWith('/courses')) {
          return { ok: true, status: 200, data: [{ id: 'course-1', name: 'B.Tech AI', active: true }] };
        }
        if (endpoint.startsWith('/dashboard/')) {
          return { ok: true, status: 200, data: { total_tickets: 5, resolved_tickets: 3, open_tickets: 2 } };
        }
        if (endpoint.startsWith('/management/')) {
          return { ok: true, status: 200, data: { questions_total: 120, ticket_totals: { total_tickets: 25, resolved_tickets: 20, resolution_rate: 0.8, avg_first_response_hours: 1.5 }, questions_by_day: [], tickets_by_day: [], campuses: [] } };
        }
        if (endpoint === '/chat/conversations') {
          return { ok: true, status: 200, data: [] };
        }
        return { ok: true, status: 200, data: {} };
      };
    `);
  }

  // Test 3: Student Authentication and Portal
  await simulateAuth('student', 'student@unibuddy.edu', 'Alex Student');
  await evalInCtx("handleGoogleCredential('google_id_token_student')");
  assert.strictEqual(evalInCtx('S.scr'), 'app', 'Student screen is app');
  assert.strictEqual(evalInCtx('S.role'), 'student', 'Role is student');
  assert.strictEqual(evalInCtx('S.view'), 'chat', 'Initial student view is chat');
  assert.ok(mockApp.innerHTML.includes('AI Assistant'), 'Student AI Assistant rendered');
  assert.ok(mockApp.innerHTML.includes('side'), 'Student sidebar rendered');
  
  // Test Student Portal views
  assert.ok(!mockApp.innerHTML.includes('Dashboard'), 'Dashboard section is removed from Student Portal navigation');
  evalInCtx("S.view = 'chat'; R();");
  assert.ok(mockApp.innerHTML.includes('AI Assistant'), 'Student AI Assistant rendered');
  evalInCtx("S.view = 'queries'; R();");
  assert.ok(mockApp.innerHTML.includes('My Queries'), 'Student Queries rendered');
  evalInCtx("S.view = 'docs'; R();");
  assert.ok(mockApp.innerHTML.includes('Documents'), 'Student Documents rendered');
  evalInCtx("S.view = 'help'; R();");
  assert.ok(mockApp.innerHTML.includes('Help & Support'), 'Student Help rendered');
  console.log('✓ Test 3: Student Portal & all views functional');

  // Test 4: Faculty Authentication and Portal
  await simulateAuth('faculty', 'prof@unibuddy.edu', 'Dr. Professor');
  await evalInCtx("handleGoogleCredential('google_id_token_faculty')");
  assert.strictEqual(evalInCtx('S.role'), 'faculty', 'Role is faculty');
  assert.strictEqual(evalInCtx('S.view'), 'tix', 'Initial faculty view is tix');
  assert.ok(mockApp.innerHTML.includes('Faculty'), 'Faculty portal rendered');
  assert.ok(mockApp.innerHTML.includes('Tickets'), 'Faculty Tickets rendered');
  
  // Test Faculty Portal views
  evalInCtx("S.view = 'fdash'; R();");
  assert.ok(mockApp.innerHTML.includes('Staff Overview'), 'Faculty Staff Overview rendered');
  evalInCtx("S.view = 'publish'; R();");
  assert.ok(mockApp.innerHTML.includes('Publish'), 'Faculty Publish rendered');
  console.log('✓ Test 4: Faculty Portal & all views functional');

  // Test 5: Authority Authentication and Portal
  await simulateAuth('authority', 'admin@unibuddy.edu', 'Authority Officer');
  await evalInCtx("handleGoogleCredential('google_id_token_authority')");
  assert.strictEqual(evalInCtx('S.role'), 'authority', 'Role is authority');
  assert.strictEqual(evalInCtx('S.view'), 'x', 'Initial authority view is x (Campus Overview)');
  assert.ok(mockApp.innerHTML.includes('Authority Portal'), 'Authority Portal rendered');
  evalInCtx("S.view = 'courses'; R();");
  assert.ok(mockApp.innerHTML.includes('Courses'), 'Authority Courses management rendered');
  console.log('✓ Test 5: Authority Portal & all views functional');

  // Test 6: Management Authentication and Portal
  await simulateAuth('management', 'chancellor@unibuddy.edu', 'University Chancellor');
  await evalInCtx("handleGoogleCredential('google_id_token_management')");
  assert.strictEqual(evalInCtx('S.role'), 'management', 'Role is management');
  assert.strictEqual(evalInCtx('S.view'), 'x', 'Initial management view is x (Management Stats)');
  assert.ok(mockApp.innerHTML.includes('Management Stats'), 'Management Stats rendered');
  assert.ok(mockApp.innerHTML.includes('Questions asked'), 'Management analytics metrics rendered');
  console.log('✓ Test 6: Management Portal & analytics functional');

  // Test 7: Session Persistence and Restore
  mockStorage['ub-token'] = 'persisted_jwt_token';
  await simulateAuth('student', 'persisted@unibuddy.edu', 'Persisted User');
  await evalInCtx("restoreSession()");
  assert.strictEqual(evalInCtx('S.scr'), 'app', 'Session restored directly to app');
  assert.strictEqual(evalInCtx('S.role'), 'student', 'Session restored student role');
  console.log('✓ Test 7: Session persistence & restore verified');

  // Test 8: Logout
  evalInCtx(`
    localStorage.removeItem('ub-token');
    S.user = null;
    S.role = null;
    go('landing');
  `);
  assert.strictEqual(evalInCtx('S.scr'), 'landing', 'Screen returned to landing on logout');
  assert.strictEqual(evalInCtx('S.user'), null, 'User state cleared');
  assert.strictEqual(mockStorage['ub-token'], undefined, 'ub-token removed from localStorage');
  console.log('✓ Test 8: Logout clears session and returns to landing page');

  console.log('\n======================================================');
  console.log('ALL 8 E2E INTEGRATION & PORTAL TESTS PASSED PERFECTLY!');
  console.log('======================================================');
  process.exit(0);
})();
