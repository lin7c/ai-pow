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
    await page.goto(pathToFileURL(path.join(folder, 'index.html')).href);
    await page.locator('.score-number').waitFor();
    assert.equal(await page.locator('.history-row').count(), 6);
    assert.equal(await page.locator('.history-section').last().isVisible(), true);
    assert.equal(await page.locator('.ladder-card').isVisible(), true);
    assert.equal(await page.locator('.vblock').count(), 6);
    assert.equal(await page.locator('.component').count(), 3, 'retention-v2 scores three dimensions');
    assert.equal(await page.locator('.tree div').count() > 0, true, 'agent structure is drawn');
    assert.equal(await page.locator('.lifetime').isVisible(), true);
    const pooled = await page.evaluate(() => {
      const d = JSON.parse(document.querySelector('#report-data').textContent);
      const rows = [d.current, ...d.history];
      const ops = rows.reduce((t, p) => t + p.score.evidence.artifact.operations, 0);
      const kept = rows.reduce((t, p) => t + p.score.evidence.artifact.retained, 0);
      return {expected: kept / ops, reported: Number(d.lifetime.artifact_survival),
              mean: rows.reduce((t, p) => t + p.score.evidence.artifact.retained / p.score.evidence.artifact.operations, 0) / rows.length};
    });
    assert.ok(Math.abs(pooled.expected - pooled.reported) < 0.0001, 'lifetime ratio is pooled');
    assert.ok(Math.abs(pooled.mean - pooled.reported) > 0.0001, 'pooled ratio is not the mean of ratios');
    await page.locator('#chart-scores').click();
    assert.equal(await page.locator('#chart-label').textContent(), 'COMMIT SCORE / 100');
    await page.locator('#chart-ladder').click();
    assert.equal(await page.locator('#chart-label').textContent(), 'CUMULATIVE SCORE / COMMIT-SUM-V1');
    const totals = await page.evaluate(() => {const d=JSON.parse(document.querySelector('#report-data').textContent); return {sum:[d.current,...d.history].reduce((v,p)=>v+Number(p.score.value),0),total:Number(d.iteration.value)};});
    assert.ok(Math.abs(totals.sum-totals.total)<0.000001);
    await page.locator('#latest').click();
    assert.equal(await page.locator('.history-section').last().isVisible(), false);
    assert.equal(await page.locator('.ladder-card').isVisible(), false);
    assert.equal(await page.locator('.lifetime').isVisible(), false);
    await page.locator('#iteration').click();
    await page.locator('.history-row').first().click();
    assert.equal(await page.locator('#commit-dialog').isVisible(), true);
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#commit-dialog').isVisible(), false);
    await page.selectOption('#grade-filter', 'S');
    assert.equal(await page.locator('.history-row').count(), 0);
    await page.selectOption('#grade-filter', 'all');
    if (process.env.REPORT_SCREENSHOT) await page.screenshot({path: process.env.REPORT_SCREENSHOT, fullPage: true});
    for (const width of [375, 720, 1024]) {
      await page.setViewportSize({width, height: 900});
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `Overflow at ${width}px`);
    }
    await page.goto(pathToFileURL(path.join(folder, 'latest.html')).href);
    await page.locator('.score-number').waitFor();
    assert.equal(await page.locator('.history-section').last().isVisible(), false);
    assert.equal(await page.locator('#iteration').isDisabled(), true);
    assert.equal(await page.evaluate(() => JSON.parse(document.querySelector('#report-data').textContent).history.length), 0);
    assert.deepEqual(errors, []);
    assert.deepEqual(requests, []);
    console.log('Report browser checks passed: desktop, mobile, modes, filters, dialog, privacy, offline.');
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exitCode = 1;});
