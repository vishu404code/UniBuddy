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
    addEventListener: () => {},
    activeElement: null
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
  JSON,
  Array,
  Object,
  Promise,
  performance: { now: () => Date.now() },
  encodeURIComponent,
  decodeURIComponent,
  fetch: () => Promise.resolve({ ok: true, json: () => Promise.resolve({}) })
};

sandbox.window.window = sandbox.window;
sandbox.window.document = sandbox.document;
sandbox.global = sandbox;

const ctx = vm.createContext(sandbox);
vm.runInContext(scriptContent, ctx);

function evalInCtx(expr) {
  return vm.runInContext(expr, ctx);
}

function runTests() {
  console.log('Starting Faculty Portal Fixes Verification...');

  // 1. Authenticate as Faculty
  evalInCtx("loginAsRole('faculty')");
  assert.strictEqual(evalInCtx('S.role'), 'faculty', 'User role should be faculty');

  // Requirement 1: Role display in Settings section
  evalInCtx("S.view = 'settings'; R();");
  const settingsHtml = mockApp.innerHTML;
  assert.ok(settingsHtml.includes('<label>Role</label><input value="Faculty" readonly>'), 'Settings must display Role as Faculty');
  assert.ok(!settingsHtml.includes('<input value="Student" readonly>'), 'Faculty Settings must NOT display Student');

  // Also check Profile section
  evalInCtx("S.view = 'profile'; R();");
  const profileHtml = mockApp.innerHTML;
  assert.ok(profileHtml.includes('Faculty'), 'Faculty profile must display Faculty');
  assert.ok(profileHtml.includes('<label>Role</label><input value="Faculty" readonly>'), 'Faculty profile must have Role as Faculty');

  // Requirement 2: Profile picture shape - Perfect circle CSS
  const avCssMatch = html.match(/\.sp-app \.av\{([^}]+)\}/);
  assert.ok(avCssMatch, '.sp-app .av CSS rule must exist');
  const avCss = avCssMatch[1];
  assert.ok(avCss.includes('border-radius:50%'), 'Avatar must have border-radius: 50%');
  assert.ok(avCss.includes('aspect-ratio:1/1'), 'Avatar must have aspect-ratio: 1/1');
  assert.ok(html.includes('.sp-app .av img,.sp-app .av svg{width:100%;height:100%;aspect-ratio:1/1;object-fit:cover'), 'Avatar image/svg must have object-fit: cover');

  // Requirement 3: Faculty Avatar
  const facAvatarSvg = evalInCtx("facAvatar()");
  assert.ok(facAvatarSvg, 'facAvatar() must return SVG');
  assert.ok(!facAvatarSvg.includes('M32 9L10 18'), 'facAvatar must NOT contain graduation mortarboard cap');
  
  // Verify userAvatar returns faculty avatar for faculty role
  const renderedAvatar = evalInCtx("userAvatar('faculty', 'sm')");
  assert.ok(!renderedAvatar.includes('M32 9L10 18'), 'userAvatar for faculty must not be student cap');
  assert.strictEqual(renderedAvatar, facAvatarSvg, 'userAvatar for faculty must be facAvatar()');

  // Requirement 4: Remove in-page Publish buttons in Documents and Announcements
  evalInCtx("S.view = 'docs'; R();");
  const docsMain = mockApp.innerHTML;
  assert.ok(!docsMain.includes('Publish</button>'), 'docsView must NOT contain an in-page Publish button');

  evalInCtx("S.view = 'ann'; R();");
  const annMain = mockApp.innerHTML;
  assert.ok(!annMain.includes('Publish</button>'), 'annView must NOT contain an in-page Publish button');

  // Sidebar still has Publish
  assert.ok(mockApp.innerHTML.includes('data-v="publish"'), 'Sidebar must have Publish navigation button');

  // Requirement 5: Contact Support Button with Gmail URL and zero plain text email visibility
  evalInCtx("S.view = 'help'; R();");
  const helpHtml = mockApp.innerHTML;
  assert.ok(helpHtml.includes('https://mail.google.com/mail/?view=cm&fs=1&to=vishnukumawat6674%40gmail.com&su=Faculty%20Portal%20Support%20Request&body='), 'Contact Support button opening prefilled Gmail compose must exist');
  assert.ok(helpHtml.includes('target="_blank"'), 'Gmail link must open in new tab');
  assert.ok(helpHtml.includes('rel="noopener noreferrer"'), 'Gmail link must have noopener noreferrer');

  // Privacy constraint: vishnukumawat6674 must NEVER appear anywhere outside the href attribute!
  // Strip all href and data attributes and check that the email is never in plain text / UI
  const textWithoutAttributes = helpHtml.replace(/\b(href|data-[a-z0-9-]+)="[^"]*"/gi, '');
  assert.ok(!textWithoutAttributes.includes('vishnukumawat6674'), 'Support email address must NOT appear anywhere in plain UI text');
  assert.ok(!textWithoutAttributes.includes('gmail.com'), 'Email domain must NOT appear anywhere in plain UI text');

  // Requirement 6: Sidebar icons for Tickets and Publish
  assert.ok(evalInCtx("SP_P.ticket"), 'SP_P.ticket must be defined');
  assert.ok(evalInCtx("SP_P.send"), 'SP_P.send must be defined');
  assert.ok(html.includes("['tix', 'ticket', 'Tickets']"), 'Faculty nav must use ticket icon');
  assert.ok(html.includes("['publish', 'send', 'Publish']"), 'Faculty nav must use send icon');

  // Requirement 7: Remove sidebar collapse arrow
  assert.ok(!mockApp.innerHTML.includes('id="col"'), 'Collapse arrow (#col) must NOT exist');
  assert.ok(!mockApp.innerHTML.includes('data-a="sp-col"'), 'Collapse arrow data-a="sp-col" must NOT exist');
  assert.ok(!html.includes("sp-app ${isCol ? 'col' : ''}"), 'sp-app must not have toggleable col class');

  console.log('✓ Requirement 1: Role in Settings displayed as Faculty');
  console.log('✓ Requirement 2: Profile picture shape is a perfect 1:1 circle');
  console.log('✓ Requirement 3: Faculty avatar is educator/faculty, not student cap');
  console.log('✓ Requirement 4: In-page Publish buttons removed from Documents & Announcements');
  console.log('✓ Requirement 5: Contact Support button connects to Gmail with privacy protected (email hidden from UI text)');
  console.log('✓ Requirement 6: Tickets and Publish sidebar icons render crisp SVG paths');
  console.log('✓ Requirement 7: Sidebar collapse arrow removed; sidebar permanently expanded');
  console.log('\n======================================================');
  console.log('ALL 7 FACULTY PORTAL REQUIREMENTS VERIFIED PERFECTLY!');
  console.log('======================================================');
  process.exit(0);
}

runTests();
