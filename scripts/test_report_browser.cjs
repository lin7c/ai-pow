// Development-only browser checks. Runtime reports have no dependencies.
const assert = require('node:assert/strict');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {chromium} = require('playwright');

(async () => {
  const browser = await chromium.launch({headless: true,
    ...(process.env.CHROME_PATH ? {executablePath: process.env.CHROME_PATH} : {})});
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 1060}, reducedMotion: 'reduce'});
    const errors = [], requests = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('request', request => {if (/^https?:/.test(request.url())) requests.push(request.url());});
    const folder = path.resolve(process.argv[2] || 'docs/demo');
    const data = () => page.evaluate(() => JSON.parse(document.querySelector('#report-data').textContent));

    await page.goto(pathToFileURL(path.join(folder, 'index.html')).href);
    await page.locator('#view-iteration').waitFor();
    // Each view carries exactly one headline: the commit score or the project total.
    assert.equal(await page.locator('#view-latest').isVisible(), false, 'iteration view hides the commit score');
    assert.equal(await page.locator('#view-iteration').isVisible(), true);
    assert.equal(await page.locator('#view-iteration .total-figure').count(), 1);
    assert.equal(await page.locator('#view-iteration .score-figure').count(), 0, 'no commit score here');
    assert.equal(await page.evaluate(() => scrollY), 0, 'the page does not jump on load');
    assert.equal(await page.locator('.row').count(), 7, 'latest commit plus its history');
    assert.equal(await page.locator('.row.is-latest').count(), 1);
    assert.equal(await page.locator('#view-iteration .panel').count(), 8, 'pooled repository totals');

    const totals = await page.evaluate(() => {
      const d = JSON.parse(document.querySelector('#report-data').textContent);
      const rows = [d.current, ...d.history];
      const ops = rows.reduce((t, p) => t + p.score.evidence.artifact.operations, 0);
      const kept = rows.reduce((t, p) => t + p.score.evidence.artifact.retained, 0);
      return {sum: rows.reduce((t, p) => t + Number(p.score.value), 0), total: Number(d.iteration.value),
              pooled: kept / ops, reported: Number(d.lifetime.artifact_survival),
              mean: rows.reduce((t, p) => t + p.score.evidence.artifact.retained / p.score.evidence.artifact.operations, 0) / rows.length};
    });
    assert.ok(Math.abs(totals.sum - totals.total) < 1e-6, 'the total is the exact sum of commit scores');
    assert.ok(Math.abs(totals.pooled - totals.reported) < 1e-4, 'lifetime ratios are pooled');
    assert.ok(Math.abs(totals.mean - totals.reported) > 1e-4, 'pooled is not the mean of per-commit ratios');

    await page.locator('.row').first().click();
    assert.equal(await page.locator('#commit-dialog').isVisible(), true);
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#commit-dialog').isVisible(), false);
    await page.selectOption('#grade-filter', 'S');
    assert.equal(await page.locator('.row').count(), 0);
    await page.selectOption('#grade-filter', 'all');

    await page.locator('#tab-latest').click();
    assert.equal(await page.locator('#view-iteration').isVisible(), false, 'latest view hides the project total');
    assert.equal(await page.locator('#view-latest').isVisible(), true);
    assert.equal(await page.locator('#view-latest .score-figure').count(), 1);
    assert.equal(await page.locator('#view-latest .total-figure').count(), 0, 'no project total here');
    assert.equal(await page.locator('#view-latest .panel').count(), 8, 'proof vector plus proof identity');
    assert.equal(await page.locator('.dim').count(), 3, 'retention-v2 scores three dimensions');
    assert.equal(await page.locator('.strip div').count(), 5, 'commit, diff, interval, human, machine');
    const tree = await page.locator('#view-latest .tree').first().textContent();
    assert.ok(/├─|└─/.test(tree), 'the agent structure is drawn as a tree');
    assert.ok(!/…/.test(tree), 'no truncation marker when nothing was truncated');
    const facts = await page.locator('#view-latest').textContent();
    for (const label of ['Interval', 'Actually paid', 'Failed tool results', 'Sessions', 'Of which cache reads'])
      assert.ok(facts.includes(label), `the vector shows ${label}`);
    if (process.env.REPORT_SCREENSHOT) await page.screenshot({path: process.env.REPORT_SCREENSHOT, fullPage: true});

    for (const width of [375, 720, 1024]) {
      await page.setViewportSize({width, height: 900});
      for (const tab of ['#tab-iteration', '#tab-latest']) {
        await page.locator(tab).click();
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true,
                     `Overflow at ${width}px`);
      }
    }

    await page.setViewportSize({width: 1440, height: 1060});
    await page.goto(pathToFileURL(path.join(folder, 'latest.html')).href);
    await page.locator('#view-latest').waitFor();
    assert.equal(await page.locator('#tab-iteration').isDisabled(), true, 'a latest-only export cannot show a total');
    assert.equal(await page.locator('#view-iteration').isVisible(), false);
    const latest = await data();
    assert.equal(latest.history.length, 0);
    assert.equal(latest.iteration, null);
    assert.equal(latest.lifetime, null);
    assert.deepEqual(errors, []);
    assert.deepEqual(requests, []);
    console.log('Report browser checks passed: separated views, vector, totals, filters, dialog, privacy, offline.');
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exitCode = 1;});
