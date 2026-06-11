/**
 * Flow editor node boundary regression.
 *
 * 怎么测：
 * - 用 API 准备一个包含越界坐标的流程，再通过浏览器进入实验编辑页加载它。
 * - 通过浏览器连续点击调色板生成大量节点。
 * - 将节点拖到画布外侧，确认最终仍被限制在画布内部。
 */
const { test, expect } = require('@playwright/test');

test.setTimeout(60_000);

async function api(page, url, options = {}) {
  const response = await page.request.fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
  });
  const body = await response.json().catch(() => ({}));
  expect(response.ok(), `${url}: ${JSON.stringify(body)}`).toBeTruthy();
  return body;
}

async function createExperiment(page, name) {
  const created = await api(page, '/api/experiments', {
    method: 'POST',
    data: {
      name,
      subject_id: `${name}-mouse`,
      species: 'mouse',
      max_duration_min: 1,
      max_trigger_count: 0,
      trigger_manual: true,
      trigger_camera: false,
      trigger_hardware: false,
      start_mode: 'manual',
    },
  });
  return created.id;
}

async function cleanupExperiment(page, expId) {
  if (!expId) return;
  await page.request.delete(`/api/experiments/${expId}`).catch(() => {});
}

function outOfBoundsFlow() {
  return {
    id: 'flow_boundary_regression',
    name: '越界节点回归',
    nodes: {
      start: { id: 'start', node_type: 'start', label: '开始', params: {}, x: -500, y: -500 },
      record_far: {
        id: 'record_far',
        node_type: 'record',
        label: '越界记录',
        params: { event_name: '越界记录' },
        x: 9999,
        y: 9999,
      },
      end: { id: 'end', node_type: 'end', label: '结束', params: {}, x: 9999, y: 9999 },
    },
    edges: [
      { id: 'e_start_record', source_node: 'start', source_port: 'out', target_node: 'record_far', target_port: 'in' },
      { id: 'e_record_end', source_node: 'record_far', source_port: 'out', target_node: 'end', target_port: 'in' },
    ],
  };
}

async function openExperimentEditor(page, expId) {
  const exp = await api(page, `/api/experiments/${expId}`);
  await page.goto('/');
  await page.locator('#expFilter').fill(exp.name);
  const expRow = page.locator('tr').filter({ has: page.getByRole('cell', { name: exp.name, exact: true }) });
  await expect(expRow).toBeVisible();
  await expRow.getByRole('button', { name: /编辑/ }).click();
  await expect(page.locator('#flowCanvas')).toBeVisible();
}

async function boundaryViolations(page) {
  return page.evaluate(() => {
    const workspace = document.getElementById('flowWorkspace') || document.getElementById('flowCanvas');
    const workspaceWidth = workspace.scrollWidth || workspace.getBoundingClientRect().width;
    const workspaceHeight = workspace.scrollHeight || workspace.getBoundingClientRect().height;
    return Array.from(document.querySelectorAll('#flowNodes .flow-node'))
      .map((el) => {
        const left = Number.parseFloat(el.style.left || '0');
        const top = Number.parseFloat(el.style.top || '0');
        const right = left + el.offsetWidth;
        const bottom = top + el.offsetHeight;
        return {
          id: el.id,
          left,
          top,
          right,
          bottom,
          workspaceWidth,
          workspaceHeight,
          outside: left < 0 || top < 0 || right > workspaceWidth + 0.5 || bottom > workspaceHeight + 0.5,
        };
      })
      .filter((node) => node.outside);
  });
}

async function nodeOverlaps(page) {
  return page.evaluate(() => {
    const nodes = Array.from(document.querySelectorAll('#flowNodes .flow-node')).map((el) => {
      const left = Number.parseFloat(el.style.left || '0');
      const top = Number.parseFloat(el.style.top || '0');
      return {
        id: el.id,
        left,
        top,
        right: left + el.offsetWidth,
        bottom: top + el.offsetHeight,
      };
    });
    const overlaps = [];
    for (let i = 0; i < nodes.length; i += 1) {
      for (let j = i + 1; j < nodes.length; j += 1) {
        const a = nodes[i];
        const b = nodes[j];
        if (a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top) {
          overlaps.push([a.id, b.id]);
        }
      }
    }
    return overlaps;
  });
}

async function startNodeCount(page) {
  return page.evaluate(() => Array.from(document.querySelectorAll('#flowNodes .flow-node'))
    .filter((el) => el.querySelector('.node-body')?.textContent?.trim() === 'start')
    .length);
}

async function clickOffscreenNodeAndReadConfig(page, nodeText) {
  const canvas = page.locator('#flowCanvas');
  const before = await canvas.evaluate(el => ({
    clientWidth: el.clientWidth,
    scrollWidth: el.scrollWidth,
    scrollLeft: el.scrollLeft,
  }));
  expect(before.scrollWidth, 'flow canvas should be horizontally scrollable').toBeGreaterThan(before.clientWidth);

  const node = page.locator('#flowNodes .flow-node').filter({ hasText: nodeText }).first();
  const canvasBox = await canvas.boundingBox();
  expect(canvasBox).toBeTruthy();
  await page.mouse.move(canvasBox.x + canvasBox.width / 2, canvasBox.y + canvasBox.height / 2);
  await page.mouse.wheel(1200, 0);
  await node.scrollIntoViewIfNeeded();

  const nodeBox = await node.boundingBox();
  expect(nodeBox).toBeTruthy();
  await page.mouse.click(nodeBox.x + Math.min(70, nodeBox.width / 2), nodeBox.y + 18);
  await expect(page.locator('#flowConfigPanel')).toBeVisible();
  // v2.4 起节点类型不可编辑：自定义名称改存于 #cfgDisplayName（旧 #cfgLabel 已移除）
  return page.locator('#cfgDisplayName').inputValue();
}

test('加载、新建、拖拽后的节点都不能越出流程画布', async ({ page }) => {
  const expName = `boundary-${Date.now()}`;
  const expId = await createExperiment(page, expName);
  try {
    await api(page, `/api/experiments/${expId}/flow/save`, {
      method: 'POST',
      data: { flow: outOfBoundsFlow() },
    });

    await openExperimentEditor(page, expId);
    await expect.poll(() => boundaryViolations(page), { timeout: 5_000 }).toEqual([]);
    await expect.poll(() => nodeOverlaps(page), { timeout: 5_000 }).toEqual([]);
    await expect.poll(() => startNodeCount(page), { timeout: 5_000 }).toBe(1);

    const recordPaletteItem = page.locator('.palette-item[data-type="record"]');
    for (let i = 0; i < 110; i += 1) {
      await recordPaletteItem.click();
    }
    expect(await boundaryViolations(page)).toEqual([]);
    expect(await nodeOverlaps(page)).toEqual([]);
    expect(await startNodeCount(page)).toBe(1);

    const conditionPaletteItem = page.locator('.palette-item[data-type="condition"]');
    await conditionPaletteItem.click();
    const dragged = page.locator('#flowNodes .flow-node').last();
    const nodeBox = await dragged.boundingBox();
    const canvasBox = await page.locator('#flowCanvas').boundingBox();
    expect(nodeBox).toBeTruthy();
    expect(canvasBox).toBeTruthy();

    await page.mouse.move(nodeBox.x + 20, nodeBox.y + 20);
    await page.mouse.down();
    await page.mouse.move(canvasBox.x + canvasBox.width + 600, canvasBox.y + canvasBox.height + 600);
    await page.mouse.up();

    expect(await boundaryViolations(page)).toEqual([]);
    expect(await startNodeCount(page)).toBe(1);

    const selectedLabel = await clickOffscreenNodeAndReadConfig(page, '越界记录');
    expect(selectedLabel).toBe('越界记录');
    expect(await startNodeCount(page)).toBe(1);
  } finally {
    await cleanupExperiment(page, expId);
  }
});
