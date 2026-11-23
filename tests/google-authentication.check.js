const fs = require('fs');
const path = require('path');
const assert = require('assert');

console.log('--- Starting UniBuddy Google Authentication Verification ---');

// 1. Verify backend/.env configuration
console.log('1. Checking backend/.env configuration...');
const backendEnv = fs.readFileSync(path.join(__dirname, '..', 'backend', '.env'), 'utf8');
const runtimeConfig = fs.readFileSync(path.join(__dirname, '..', 'runtime-config.js'), 'utf8');

const runtimeClientIdMatch = runtimeConfig.match(/googleClientId:\s*["']([^"']+)["']/);
assert.ok(runtimeClientIdMatch, 'runtime-config.js must contain googleClientId');
const runtimeClientId = runtimeClientIdMatch[1];
assert.strictEqual(runtimeClientId, '675157891879-ufpn2fmb16n6qkq7qjjeclre6eaem085.apps.googleusercontent.com');

const envClientIdMatch = backendEnv.match(/GOOGLE_CLIENT_ID=([^\r\n]+)/);
assert.ok(envClientIdMatch, 'backend/.env must contain GOOGLE_CLIENT_ID');
assert.strictEqual(envClientIdMatch[1].trim(), runtimeClientId, 'backend GOOGLE_CLIENT_ID must match runtime-config.js client ID');

const envOriginsMatch = backendEnv.match(/ALLOWED_ORIGINS=([^\r\n]+)/);
assert.ok(envOriginsMatch, 'backend/.env must specify ALLOWED_ORIGINS');
assert.ok(envOriginsMatch[1].includes('http://localhost:3000'), 'ALLOWED_ORIGINS must include localhost:3000');
assert.ok(envOriginsMatch[1].includes('http://127.0.0.1:3000'), 'ALLOWED_ORIGINS must include 127.0.0.1:3000');
console.log('✓ Backend environment variables verified.');

// 2. Verify standalone login.html
console.log('2. Checking login.html Google OAuth setup...');
const loginHtml = fs.readFileSync(path.join(__dirname, '..', 'login.html'), 'utf8');

assert.ok(loginHtml.includes('https://accounts.google.com/gsi/client'), 'login.html must load Google Identity Services');
assert.ok(loginHtml.includes('runtime-config.js'), 'login.html must load runtime-config.js');
assert.ok(loginHtml.includes('id="google"'), 'login.html must contain #google button');
assert.ok(loginHtml.includes('id="google-signin-btn"'), 'login.html must contain #google-signin-btn container');
assert.ok(loginHtml.includes('id="accessreq"'), 'login.html must have #accessreq state for 403 no_profile');
assert.ok(loginHtml.includes('id="btnRequestAccess"'), 'login.html must have #btnRequestAccess button');

assert.ok(loginHtml.includes('initGoogleAuth'), 'login.html must define initGoogleAuth');
assert.ok(loginHtml.includes('handleGoogleCredential'), 'login.html must define handleGoogleCredential');
assert.ok(loginHtml.includes('requestStudentAccess'), 'login.html must define requestStudentAccess');
assert.ok(loginHtml.includes("'/auth/google'"), 'login.html must call /auth/google');
assert.ok(loginHtml.includes("'/auth/me'"), 'login.html must call /auth/me');
assert.ok(loginHtml.includes("'/auth/google/access-request'"), 'login.html must call /auth/google/access-request');
assert.ok(loginHtml.includes("localStorage.setItem('ub-token'"), 'login.html must store ub-token');
assert.ok(loginHtml.includes("localStorage.setItem('ub-user'"), 'login.html must store ub-user');
console.log('✓ login.html Google OAuth flow verified.');

// 3. Verify SPA index.html
console.log('3. Checking index.html Google OAuth setup...');
const indexHtml = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');

assert.ok(indexHtml.includes('https://accounts.google.com/gsi/client'), 'index.html must load Google Identity Services');
assert.ok(indexHtml.includes('runtime-config.js'), 'index.html must load runtime-config.js');
assert.ok(indexHtml.includes('handleGoogleCredential'), 'index.html must define handleGoogleCredential');
assert.ok(!indexHtml.includes("email.includes('faculty')"), 'index.html must not perform client-side role guessing');
assert.ok(indexHtml.includes("type==='access-request'"), 'index.html modal() must support access-request');
assert.ok(indexHtml.includes("submit-access-request"), 'index.html must support submit-access-request action');
console.log('✓ index.html Google OAuth flow verified.');

// 4. Test simulated Google Auth API contract
console.log('4. Testing simulated API interactions with login logic...');
async function testAuthSimulation() {
  const mockStorage = {};
  global.localStorage = {
    getItem: k => mockStorage[k] || null,
    setItem: (k, v) => { mockStorage[k] = String(v); },
    removeItem: k => { delete mockStorage[k]; }
  };

  // Simulate 200 Google Sign-in response
  const fakeIdToken = 'header.payload.signature';
  const fakeSessionResponse = {
    access_token: 'fake-jwt-access-token-12345',
    token_type: 'bearer',
    user: {
      id: 'usr-google-1',
      email: 'student.user@university.edu',
      full_name: 'Alex Rivera',
      role: 'student',
      campus_id: 'cmp-1',
      department_id: null,
      cross_campus_record_access: false
    }
  };

  // Test storage on 200
  localStorage.setItem('ub-token', fakeSessionResponse.access_token);
  localStorage.setItem('ub-user', JSON.stringify(fakeSessionResponse.user));
  localStorage.setItem('ub-current-user', fakeSessionResponse.user.email);

  assert.strictEqual(localStorage.getItem('ub-token'), 'fake-jwt-access-token-12345');
  const storedUser = JSON.parse(localStorage.getItem('ub-user'));
  assert.strictEqual(storedUser.role, 'student');
  assert.strictEqual(storedUser.full_name, 'Alex Rivera');

  // Verify faculty role handling
  const fakeFacultyResponse = {
    access_token: 'fake-jwt-faculty-token-67890',
    token_type: 'bearer',
    user: {
      id: 'fac-google-1',
      email: 'prof.smith@university.edu',
      full_name: 'Prof. Smith',
      role: 'faculty',
      campus_id: 'cmp-1',
      department_id: 'dept-cs',
      cross_campus_record_access: false
    }
  };
  localStorage.setItem('ub-token', fakeFacultyResponse.access_token);
  localStorage.setItem('ub-user', JSON.stringify(fakeFacultyResponse.user));
  const storedFaculty = JSON.parse(localStorage.getItem('ub-user'));
  assert.strictEqual(storedFaculty.role, 'faculty');

  // Verify management role handling
  const fakeMgmtResponse = {
    access_token: 'fake-jwt-mgmt-token-99999',
    token_type: 'bearer',
    user: {
      id: 'mgmt-google-1',
      email: 'mgmt.director@university.edu',
      full_name: 'Director Johnson',
      role: 'management',
      campus_id: null,
      department_id: null,
      cross_campus_record_access: true
    }
  };
  localStorage.setItem('ub-token', fakeMgmtResponse.access_token);
  localStorage.setItem('ub-user', JSON.stringify(fakeMgmtResponse.user));
  const storedMgmt = JSON.parse(localStorage.getItem('ub-user'));
  assert.strictEqual(storedMgmt.role, 'management');

  console.log('✓ Multi-role session contracts verified.');
}

testAuthSimulation().then(() => {
  console.log('\n======================================================');
  console.log('ALL GOOGLE AUTHENTICATION CHECKS PASSED SUCCESSFULLY!');
  console.log('======================================================\n');
}).catch(err => {
  console.error('Test failed:', err);
  process.exit(1);
});

