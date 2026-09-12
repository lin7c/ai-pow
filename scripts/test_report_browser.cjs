// Development-only browser checks. The generated pages have no dependencies.
const assert = require('node:assert/strict');
const fs = require('node:fs');
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
    const reports = fs.readdirSync(path.join(folder, 'reports')).filter(f => f.endsWith('.html'));
    assert.ok(reports.length >= 2, 'a run view per recorded commit');
    const scoreLeads = async (label, expected) => {
      const hero = page.locator('.score-hero');
      assert.equal(await hero.locator('h2').textContent(), label);
      const value = await hero.locator('.score-value').textContent();
      assert.ok(value.startsWith(Number(expected).toLocaleString('en-US', {maximumFractionDigits: 1})));
      const box = await hero.boundingBox();
      assert.ok(box.y < 260, 'primary score is visible immediately');
      assert.equal(await page.locator('details[open]').count(), 0, 'secondary metrics start collapsed');
      for (const summary of await page.locator('details > summary').all()) {
        await summary.click();
        assert.equal(await summary.evaluate(el => el.parentElement.open), true);
      }
    };

    // ---- Repository dashboard ----------------------------------------------
    await page.goto(pathToFileURL(path.join(folder, 'index.html')).href);
    await page.locator('.score-hero').waitFor();
    assert.equal(await page.evaluate(() => scrollY), 0, 'the page does not jump on load');
    assert.equal(await page.locator('.stat').count(), 8, 'eight supporting metrics remain available');
    const chainText = await page.locator('#content').textContent();
    assert.ok(/T-1 \+ this commit/.test(chainText), 'the dashboard states the iteration rule');
    const chain = await page.evaluate(() => JSON.parse(document.querySelector('#report-data').textContent));
    assert.equal(chain.chain_verified, true, 'the ledger linkage is checked');
    assert.equal(chain.chain_length, chain.history.length, 'every recorded commit is a chain row');
    // T = T-1 + contribution, read straight off the rendered rows.
    const running = chain.history.map(r => Number(r.total)).reverse();
    const adds = chain.history.map(r => Number(r.score.value)).reverse();
    running.forEach((value, i) => assert.ok(Math.abs(value - (i ? running[i - 1] : 0) - adds[i]) < 1e-6,
                                            `row ${i} is not previous + contribution`));
    assert.equal(await page.locator('.panel svg').count() >= 4, true, 'trend charts are drawn');
    await scoreLeads('Total score', chain.iteration.value);
    const rowCount = await page.evaluate(() => JSON.parse(document.querySelector('#report-data').textContent).history.length);
    assert.equal(await page.locator('tbody tr').count() >= rowCount, true, 'one table row per commit');
    const totals = await page.evaluate(() => {
      const d = JSON.parse(document.querySelector('#report-data').textContent);
      const ops = d.history.reduce((t, p) => t + p.operations, 0);
      const kept = d.history.reduce((t, p) => t + p.retained, 0);
      return {sum: d.history.reduce((t, p) => t + Number(p.score.value), 0), total: Number(d.iteration.value),
              pooled: kept / ops, reported: Number(d.lifetime.artifact_survival),
              mean: d.history.reduce((t, p) => t + p.retained / p.operations, 0) / d.history.length};
    });
    assert.ok(Math.abs(totals.sum - totals.total) < 1e-6, 'the total is the exact sum of commit scores');
    assert.ok(Math.abs(totals.pooled - totals.reported) < 1e-4, 'lifetime ratios are pooled');
    assert.ok(Math.abs(totals.mean - totals.reported) > 1e-4, 'pooled is not the mean of per-commit ratios');

    // ---- Commit run view ----------------------------------------------------
    const href = await page.locator('tbody a').first().getAttribute('href');
    const proofFile = path.basename(href);
    assert.ok(fs.existsSync(path.join(folder, 'reports', proofFile)), 'the linked run view exists');
    await page.locator('tbody a').first().click();
    await page.locator('.score-hero').waitFor();
    assert.equal(await page.locator('.stat').count(), 6, 'six supporting metrics remain available');
    assert.equal(await page.locator('.stat .spark svg').count(), 6, 'each rate carries its own trend');
    const runText = await page.locator('#content').textContent();
    assert.ok(/baseline/.test(runText), 'rates are compared with the project baseline');
    assert.ok(await page.locator('.delta').count() >= 3, 'the comparison is shown per rate');
    await scoreLeads('Iteration score', await page.evaluate(() => JSON.parse(document.querySelector('#report-data').textContent).current.score.value));
    assert.equal(await page.locator('#waterfall svg').count(), 1, 'the session timeline is drawn');
    assert.ok(await page.locator('.tree').count() > 0, 'the agent topology is drawn');
    assert.ok(/├─|└─/.test(await page.locator('.tree').first().textContent()), 'as a tree');
    assert.ok(await page.locator('tbody tr').count() > 0, 'per-file work is listed');
    assert.equal(await page.locator('.prov div').count(), 3, 'observed / derived / inferred');
    const text = await page.locator('#content').textContent();
    for (const label of ['Human steering', 'Unit cost', 'Retention', 'Throughput', 'Autonomy',
                         'Cache read share', 'Actually paid', 'Failed results', 'Coverage gaps'])
      assert.ok(text.includes(label), `the run view shows ${label}`);
    if (process.env.REPORT_SCREENSHOT) await page.screenshot({path: process.env.REPORT_SCREENSHOT, fullPage: true});

    for (const width of [375, 720, 1024]) {
      await page.setViewportSize({width, height: 900});
      for (const file of ['index.html', ...reports.map(name => path.join('reports', name))]) {
        await page.goto(pathToFileURL(path.join(folder, file)).href);
        await page.locator('.score-hero').waitFor();
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true,
                     `${file} overflows at ${width}px`);
      }
    }
    await page.evaluate(() => dispatchEvent(new Event('beforeprint')));
    assert.equal(await page.locator('details:not([open])').count(), 0, 'print includes all evidence');
    await page.evaluate(() => dispatchEvent(new Event('afterprint')));
    assert.equal(await page.locator('details[open]').count(), 0, 'print restores collapsed state');
    assert.deepEqual(errors, []);
    assert.deepEqual(requests, []);
    console.log('Browser checks passed: score hierarchy, exact values, expandable evidence, mobile, privacy, offline.');
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exitCode = 1;});
