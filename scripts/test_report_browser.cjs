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
    assert.ok(reports.length >= 2, 'a proof page per recorded commit');
    const below = async (selector, reference) => {
      const a = await page.locator(selector).first().boundingBox();
      const b = await page.locator(reference).first().boundingBox();
      return a && b && a.y > b.y + b.height;
    };

    // ---- Repository summary -------------------------------------------------
    await page.goto(pathToFileURL(path.join(folder, 'index.html')).href);
    await page.locator('.five').waitFor();
    assert.equal(await page.evaluate(() => scrollY), 0, 'the page does not jump on load');
    assert.equal(await page.locator('.five div').count(), 5, 'five pooled quantities first');
    assert.equal(await page.locator('.chart-cell svg path').count(), 6, 'six trend lines');
    assert.equal(await page.locator('.level').count(), 3, 'development style levels');
    const rowCount = await page.evaluate(() => JSON.parse(document.querySelector('#report-data').textContent).history.length);
    assert.equal(await page.locator('.row').count(), rowCount, 'one row per recorded commit');
    assert.ok(await below('.total-figure', '.five'), 'the cumulative score is never the first screen');
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

    // ---- Commit proof -------------------------------------------------------
    const href = await page.locator('.row').first().getAttribute('href');
    const proofFile = path.basename(href);
    assert.ok(fs.existsSync(path.join(folder, 'reports', proofFile)), 'the linked proof page exists');
    await page.locator('.row').first().click();
    await page.locator('.five').waitFor();
    assert.ok(href.includes('reports/'), 'each row opens that commit proof');
    assert.equal(await page.locator('.five div').count(), 5, 'five recorded quantities first');
    assert.equal(await page.locator('.ident div').count(), 6, 'identity: commit, parent, time, duration, proof, trace');
    assert.equal(await page.locator('.total-figure').count(), 0, 'no project total on a commit page');
    assert.ok(await below('.derived-score', '.five'), 'the score is never the first screen');
    assert.equal(await page.locator('.prov div').count(), 3, 'observed / derived / inferred');
    assert.ok(await page.locator('.timeline .tl').count() > 0, 'the timeline is drawn');
    assert.ok(await page.locator('table.files tbody tr').count() > 0, 'per-file work is listed');
    const tree = await page.locator('.tree').first().textContent();
    assert.ok(/├─|└─/.test(tree), 'the agent structure is drawn as a tree');
    const text = await page.locator('#content').textContent();
    for (const heading of ['Human', 'Machine', 'Agent', 'Artifact', 'Timeline', 'Result', 'Verification'])
      assert.ok(text.includes(heading), `section ${heading}`);
    for (const label of ['Duration', 'Actual cost', 'Unique sessions', 'Failed results', 'Of which cache reads'])
      assert.ok(text.includes(label), `the proof shows ${label}`);
    if (process.env.REPORT_SCREENSHOT) await page.screenshot({path: process.env.REPORT_SCREENSHOT, fullPage: true});

    // Every generated page, at every width, with the widest recorded labels.
    for (const width of [375, 720, 1024]) {
      await page.setViewportSize({width, height: 900});
      for (const file of ['index.html', ...reports.map(name => path.join('reports', name))]) {
        await page.goto(pathToFileURL(path.join(folder, file)).href);
        await page.locator('.five').waitFor();
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true,
                     `${file} overflows at ${width}px`);
      }
    }
    assert.deepEqual(errors, []);
    assert.deepEqual(requests, []);
    console.log('Report browser checks passed: two pages, quantities first, provenance, privacy, offline.');
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exitCode = 1;});
