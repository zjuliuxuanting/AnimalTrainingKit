/**
 * Sprint v1.2.0 G3 收尾验证：
 *  1. 新建面板已无 RECORD_END
 *  2. 旧含 record_end 流程加载后迁移为 record+end（API 边界已验，这里验编辑器不崩）
 *  3. 连线右键删除 + Delete 删除
 *  4. START 左上 / END 右侧，整理流程后仍成立
 *  5. 五条正式链路列表干净
 *
 * 端口固定 8001。
 */
const { test, expect } = require('@playwright/test');

test.use({ baseURL: 'http://localhost:8001' });
test.setTimeout(90_000);

async function gotoApp(page) {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#nodePalette', { state: 'attached', timeout: 15000 });
  await page.waitForTimeout(800);
}

test('1. 新建面板无 RECORD_END', async ({ page }) => {
  await gotoApp(page);
  const recordEnd = await page.locator('.palette-item[data-type="record_end"]').count();
  expect(recordEnd).toBe(0);
  // record 仍在
  expect(await page.locator('.palette-item[data-type="record"]').count()).toBe(1);
});

test('5. 五条正式链路列表干净', async ({ page }) => {
  await gotoApp(page);
  const exps = await page.request.get('/api/experiments').then(r => r.json());
  const names = exps.experiments.map(e => e.name).sort();
  expect(names).toEqual([
    'C1_FR1_操作性条件反射',
    'C2_社会性选择',
    'C3_5CSRTT',
    'C4_SignTracking',
    'C5_每日定额投喂',
  ]);
});

test('4. START 左上 / END 右侧（整理流程后）', async ({ page }) => {
  await gotoApp(page);
  const exps = await page.request.get('/api/experiments').then(r => r.json());
  const c1 = exps.experiments.find(e => e.name.startsWith('C1'));
  // 进入实验，加载流程
  await page.evaluate((id) => enterExperiment(id), c1.id);
  await page.waitForTimeout(1500);
  // 切到流程页
  await page.locator('[data-tab="flow"]').click();
  await page.waitForTimeout(500);
  // 整理流程
  const hasAutoLayout = await page.evaluate(() => typeof autoLayoutFlow === 'function');
  expect(hasAutoLayout).toBeTruthy();
  await page.evaluate(() => autoLayoutFlow());
  await page.waitForTimeout(800);

  const pos = await page.evaluate(() => {
    const nodes = flowNodes;
    let start = null, end = null;
    for (const id in nodes) {
      if (nodes[id].type === 'start') start = parseFloat(nodes[id].el.style.left) || 0;
      if (nodes[id].type === 'end') end = parseFloat(nodes[id].el.style.left) || 0;
    }
    return { start, end };
  });
  expect(pos.start).not.toBeNull();
  expect(pos.end).not.toBeNull();
  // START 必须在 END 左侧
  expect(pos.start).toBeLessThan(pos.end);
});

test('3. 连线可点击选中并 Delete 删除', async ({ page }) => {
  await gotoApp(page);
  const exps = await page.request.get('/api/experiments').then(r => r.json());
  const c1 = exps.experiments.find(e => e.name.startsWith('C1'));
  await page.evaluate((id) => enterExperiment(id), c1.id);
  await page.waitForTimeout(1500);
  await page.locator('[data-tab="flow"]').click();
  await page.waitForTimeout(500);

  const before = await page.evaluate(() => flowEdges.length);
  expect(before).toBeGreaterThan(0);
  // 点击第一条连线选中（派发冒泡 click 到 SVG path，触发文档级选中监听）
  const firstEdgeId = await page.evaluate(() => flowEdges[0].id);
  await page.evaluate((eid) => {
    const path = document.querySelector(`path[data-edge-id="${eid}"]`);
    path.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
  }, firstEdgeId);
  await page.waitForTimeout(200);
  // 焦点不在输入框，按 Delete 删除选中连线
  await page.evaluate(() => document.body.focus());
  await page.keyboard.press('Delete');
  await page.waitForTimeout(300);
  const after = await page.evaluate(() => flowEdges.length);
  expect(after).toBe(before - 1);
});
