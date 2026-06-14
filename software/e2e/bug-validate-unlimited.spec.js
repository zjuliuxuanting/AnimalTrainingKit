// Ad-hoc browser verification for two bug fixes (port 8001):
//  Bug1: flow validate must pass camera zone signal when experiment_id present
//  Bug2: create experiment with 不限时间 + 不设上限 must not error
const { test, expect } = require('@playwright/test');

const BASE = 'http://localhost:8001';

test('Bug2: 不限时间 + 不设上限 同时勾选可创建实验', async ({ page }) => {
  const name = 'e2e-bug2-' + Date.now();
  await page.goto(BASE);
  await page.click('button:has-text("新建实验")');
  await page.fill('#expName', name);
  await page.fill('#expSubjectId', 'M-E2E');
  await page.check('#expDurationUnlimited');
  await page.check('#expTriggersUnlimited');
  await page.click('button:has-text("创建实验")');
  // success toast, no warn block
  await expect(page.locator('.toast-item', { hasText: '已创建' })).toBeVisible({ timeout: 5000 });

  // cleanup via API
  const list = await page.evaluate(async (b) => (await (await fetch(b + '/api/experiments')).json()).experiments, BASE);
  const exp = list.find(e => e.name === name);
  expect(exp).toBeTruthy();
  expect(exp.max_duration_min).toBe(0);
  expect(exp.max_trigger_count).toBe(0);
  await page.evaluate(async ({ b, id }) => fetch(b + '/api/experiments/' + id, { method: 'DELETE' }), { b: BASE, id: exp.id });
});
