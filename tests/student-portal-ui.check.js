// Regression checks for the Student portal in index.html. Run with: node tests/student-portal-ui.check.js
// They read the page source and check the rules that matter: the Help contact, the Student labels, and
// the chat history rules. Fixture values only; nothing is sent anywhere.
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');

function functionSource(name) {
  const start = html.indexOf(`function ${name}(`);
  assert.notStrictEqual(start, -1, `${name} exists`);
  const end = html.indexOf('\n}', start);
  return html.slice(start, end + 2);
}

// 1. Help & Support: only the configured Management contact. No assistant shortcut, no other help text.
const help = functionSource('helpView');
assert.ok(!/Open AI Assistant/.test(help), 'Help has no AI Assistant shortcut');
assert.ok(!/data-v="chat"/.test(help), 'Help has no link to the assistant');
assert.ok(/mailto:/.test(help) && /supportEmail\(\)/.test(help), 'Help uses the configured support address');
assert.ok(/not been configured yet/.test(help), 'Help says so when no approved address is set');
assert.ok(!/Ask UniBuddy first/.test(help), 'Old Help text is removed');

// The support address is accepted only if it is a plain email address.
const supportSrc = functionSource('supportEmail');
function support(value) {
  const window = { UB_CONFIG: { supportEmail: value } };
  return new Function('window', supportSrc + '\nreturn supportEmail();')(window);
}
assert.strictEqual(support('office@example.edu'), 'office@example.edu');
assert.strictEqual(support(''), '', 'empty means not configured');
assert.strictEqual(support('not an email'), '', 'malformed values are not shown');
assert.strictEqual(support('a@b"><script>'), '', 'values with markup are not shown');

// 2. Student profile labels: Institute and Course. Other roles keep Campus and Department.
const profile = functionSource('profileView');
assert.ok(/S\.role==='student'\?'Institute':'Campus'/.test(profile), 'Student sees Institute instead of Campus');
assert.ok(/S\.role==='student'\?'Course':'Department'/.test(profile), 'Student sees Course instead of Department');
assert.ok(/S\.role==='student'\?'Assigned to your institute':'Assigned to your campus'/.test(profile), 'Student value text says institute');
assert.ok(/S\.role==='management'\?'':/.test(profile), 'Management profile still hides both fields');

// 3. Chat history: the server returns the last 72 hours; the page does not hide conversations by start date.
const load = functionSource('loadConversations');
assert.ok(!/withinChatWindow\(c\./.test(load), 'conversations are not re-filtered by start date on the page');
assert.ok(/withinChatWindow\(m\.created_at\)/.test(html), 'messages keep the 72-hour display guard');

// 4. Runtime config: the support address is a public setting, empty until an approved address is set.
const config = fs.readFileSync(path.join(__dirname, '..', 'runtime-config.js'), 'utf8');
assert.ok(/supportEmail:\s*""/.test(config), 'supportEmail is present and empty until approved');

console.log('student-portal-ui checks passed');
