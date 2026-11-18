// Regression checks for sign-in routing and Management data in index.html.
// Run with: node tests/auth-routing.check.js
// These read the page source. The browser behaviour was checked separately with simulated backend answers.
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');

function functionSource(name) {
  const start = html.indexOf(`function ${name}(`) >= 0 ? html.indexOf(`function ${name}(`) : html.indexOf(`async function ${name}(`);
  assert.notStrictEqual(start, -1, `${name} exists`);
  const end = html.indexOf('\n}', start);
  return html.slice(start, end + 2);
}

// 1. A role is never worked out from email text, and no email address is hard-coded in the page.
assert.ok(!/includes\('(faculty|authority|management|admin|dean)'\)/.test(html), 'no role is inferred from words in the email');
assert.ok(!/jaysinghf204|tarun\.s26366/.test(html), 'no staff or management login address is written into the public page');

// 2. Only a backend-confirmed user is saved as the session user.
assert.ok(!/localStorage\.setItem\('ub-user'/.test(html), 'the old provisional role key is not written');
const saves = html.match(/saveSessionUser\(/g) || [];
assert.strictEqual(saves.length, 2, 'saveSessionUser is called only where the backend answer is shown (definition + showPortal)');
const showPortal = functionSource('showPortal');
assert.ok(/saveSessionUser\(user\)/.test(showPortal), 'showPortal saves the backend answer');

// 3. Sign-in: a repeat sign-in may show the previously confirmed session for the same Google email only.
const signIn = functionSource('handleGoogleCredential');
assert.ok(/known\.email===email/.test(signIn), 'a saved session is used only for the same Google email');
assert.ok(/backToLogin\(/.test(signIn), 'a failed sign-in returns to the login screen');
assert.ok(!/S\.role=(?!known\.role|null)/.test(signIn.replace(/S\.role=known\.role/g, '')), 'no role is set from anything but the saved session or the backend');
assert.ok(/showPortal\(me\)/.test(signIn) && /me=res\.data\.user/.test(signIn), 'the portal opens only from the backend answer');
assert.ok(/\/auth\/google/.test(signIn), 'the Google sign-in request is unchanged');

// 4. Reload: no session token means no portal, whatever was saved before.
const restore = functionSource('restoreSession');
assert.ok(/if\(!token\)\{clearSession\(\);R\(\);return\}/.test(restore), 'no token: the login screen, never a stored role');
assert.ok(/localStorage\.removeItem\('ub-user'\)/.test(restore), 'a role saved by an older page is removed');
assert.ok(/r\.status===401\|\|r\.status===403/.test(restore), 'a refused session returns to login');

// 5. Management: a failed analytics load is shown, the last figures are kept, and the user can retry.
const load = html.slice(html.indexOf('async function loadViewData'), html.indexOf('\n}\n', html.indexOf('async function loadViewData')));
assert.ok(/S\.analyticsError=/.test(load) && /S\.analyticsAt=Date\.now\(\)/.test(load), 'loadViewData records the result of the analytics request');
assert.ok(/data-a="retry-analytics"/.test(html), 'Management offers a retry');
assert.ok(/a=='retry-analytics'/.test(html), 'the retry is wired');
assert.ok(/visibilitychange/.test(html) && /S\.role==='management'&&S\.view==='x'/.test(html), 'Management figures refresh when the tab comes back');

console.log('auth-routing checks passed');
