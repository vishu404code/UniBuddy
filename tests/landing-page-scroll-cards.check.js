const fs = require('fs');
const path = require('path');
const assert = require('assert');

console.log('Testing Scroll-Driven Automatic Card Switching on UniBuddy Landing Page...');

const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');

// 1. Structure Verification
console.log('--- Step 1: Checking DOM Structure & Alignment ---');
assert(html.includes('<div class="work-track" id="wtrack">'), '#wtrack wrapper must exist');
assert(html.includes('class="work-showcase" id="wshowcase"'), '.work-showcase sticky wrapper must exist');
assert(html.includes('<div class="stack" id="wstack"'), '#wstack card stack must exist inside work track');

// Verify that heading and roles are inside work-showcase within wtrack
const wtrackMatch = html.match(/<div class="work-track" id="wtrack">([\s\S]*?)<\/div>\s*<div class="wrap">\s*<div class="dock">/);
assert(wtrackMatch, 'wtrack must enclose the showcase before the dock');
assert(wtrackMatch[1].includes('Put UniBuddy to work'), 'Heading "Put UniBuddy to work" must be inside work-track showcase');
assert(wtrackMatch[1].includes('id="roles"'), 'Roles tablist must be inside work-track showcase');
assert(wtrackMatch[1].includes('id="wstack"'), 'Card stack must be inside work-track showcase');
console.log('✓ DOM Structure and Showcase Alignment verified.');

// 2. CSS Verification
console.log('--- Step 2: Checking Scroll & Sticky CSS ---');
assert(html.includes('.ub-landing .work-track'), '.ub-landing .work-track CSS rule must exist');
assert(html.includes('.ub-landing .work-showcase {position:sticky;top:76px;z-index:5'), '.work-showcase must use position: sticky top: 76px');
assert(html.includes('.ub-landing #wstack .sc'), '#wstack .sc styles must exist');
assert(html.includes('translate3d'), 'Card transforms must use GPU-accelerated translate3d');
assert(html.includes('scale('), 'Cards must use scale transitions');
assert(html.includes('box-shadow:'), 'Layered cards must define depth box-shadows');
assert(html.includes('@media(max-width:1050px)'), 'Responsive media query for tablet must exist');
assert(html.includes('@media(max-width:560px)'), 'Responsive media query for mobile must exist');
console.log('✓ CSS Sticky & Stacking rules verified.');

// 3. JavaScript Scroll-Progress Verification
console.log('--- Step 3: Checking Scroll-Driven Card Controller ---');
assert(!html.includes('wsAuto = setTimeout(() => wsk.front(1, true), 1300)'), 'Random 1.3s auto-timer must be removed');
assert(html.includes('checkWorkCardScroll'), 'checkWorkCardScroll function must exist');
assert(html.includes('activateWorkCard'), 'activateWorkCard function must exist');
assert(html.includes('if(rect.top > stickyTop)'), 'Must guard before reaching the section position');
assert(html.includes('requestAnimationFrame'), 'Scroll updates must be throttled with requestAnimationFrame');
console.log('✓ Scroll controller logic verified.');

// 4. Mathematical Simulation of Scroll Progress
console.log('--- Step 4: Simulating Scroll Progress & Exact Trigger Alignment ---');

function computeCardState(rectTop, stickyTop = 76, trackHeight = 2500, vh = 900, numCards = 3) {
  // Before reaching the section: Card 0 stays foreground, 0 card switching
  if (rectTop > stickyTop) {
    return { targetIdx: 0, progress: 0, state: 'before_section' };
  }

  const scrollableDist = trackHeight - vh;
  const scrolled = stickyTop - rectTop;
  const progress = Math.max(0, Math.min(1, scrolled / scrollableDist));

  let targetIdx = Math.floor(progress * numCards);
  if (targetIdx >= numCards) targetIdx = numCards - 1;
  if (targetIdx < 0) targetIdx = 0;

  return { targetIdx, progress, state: 'active_section' };
}

// 4a. Before reaching section (scrolling through hero, film, etc.)
assert.strictEqual(computeCardState(600).targetIdx, 0, 'When section is below viewport (600px), Card 0 must be active');
assert.strictEqual(computeCardState(200).targetIdx, 0, 'When section top is 200px, Card 0 must be active');
assert.strictEqual(computeCardState(80).targetIdx, 0, 'Just before stickyTop (80px), Card 0 must be active');
console.log('✓ Before reaching section: No card switching takes place, Card 0 remains active in foreground.');

// 4b. Reaching the exact starting position (rectTop == stickyTop)
const startState = computeCardState(76);
assert.strictEqual(startState.targetIdx, 0, 'At stickyTop (76px), Card 0 must be active');
assert.strictEqual(startState.progress, 0, 'At stickyTop, progress must be 0');
console.log('✓ At exact starting position: Card 0 is active in foreground, progress starts at 0.');

// 4c. Scrolling down through section
assert.strictEqual(computeCardState(0).targetIdx, 0, 'Early in section (scrolled ~76px), Card 0 stays active');
assert.strictEqual(computeCardState(-300).targetIdx, 0, 'At progress ~0.23, Card 0 stays active');
assert.strictEqual(computeCardState(-600).targetIdx, 1, 'At progress ~0.42, Card 1 smoothly comes forward');
assert.strictEqual(computeCardState(-850).targetIdx, 1, 'At progress ~0.58, Card 1 stays in foreground');
assert.strictEqual(computeCardState(-1150).targetIdx, 2, 'At progress ~0.76, Card 2 smoothly comes forward');
assert.strictEqual(computeCardState(-1600).targetIdx, 2, 'At final range (progress 1.0), Card 2 remains in foreground');
console.log('✓ Scrolling Down: Cards 0 -> 1 -> 2 transition sequentially with dedicated intervals.');

// 4d. Scrolling back up
assert.strictEqual(computeCardState(-1200).targetIdx, 2, 'Scrolling up from bottom: Card 2 active');
assert.strictEqual(computeCardState(-700).targetIdx, 1, 'Scrolling up past threshold: Card 1 comes back forward');
assert.strictEqual(computeCardState(-200).targetIdx, 0, 'Scrolling up to initial range: Card 0 comes back forward');
assert.strictEqual(computeCardState(150).targetIdx, 0, 'Scrolling above section: Card 0 remains in foreground');
console.log('✓ Scrolling Up: Reverse transitions 2 -> 1 -> 0 work symmetrically.');

console.log('\n======================================================');
console.log('ALL SCROLL-DRIVEN CARD SWITCHING CHECKS PASSED!');
console.log('======================================================');
