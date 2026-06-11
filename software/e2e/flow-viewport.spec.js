/**
 * Sprint v1.1.4 / G3.1: flow viewport and canvas ergonomics regression.
 *
 * 怎么测：
 * - 用 API 准备一个横向很长、带分支的流程，浏览器进入真实流程编辑页。
 * - 真实点击/滚轮操作视口工具条、远端节点和整理按钮。
 * - 严格按 DOM 节点类型统计 START，确认没有第二个 start 块。
 */
const { test, expect } = require('@playwright/test');

test.setTimeout(120_000);

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

function node(id, node_type, label, params, x, y) {
  return { id, node_type, label, params: params || {}, x, y };
}

function edge(source_node, source_port, target_node) {
  return {
    id: `e_${source_node}_${source_port}_${target_node}`,
    source_node,
    source_port,
    target_node,
    target_port: 'in',
    condition: '',
  };
}

function viewportFlow() {
  return {
    id: 'g31_viewport_flow',
    name: 'G3.1 视口回归流程',
    nodes: Object.fromEntries([
      node('start', 'start', '开始', {}, 40, 220),
      node('trigger_a', 'trigger', '远端触发', { signal_id: 'manual:trigger' }, 520, 40),
      node('delay_a', 'delay', '等待', { duration_value: 0, duration_unit: 'seconds' }, 900, 300),
      node('condition_a', 'condition', '是否继续?', { source: 'trigger_count', operator: 'gte', value: 1 }, 1280, 100),
      node('record_true', 'record', '记录真分支', { event_name: '真分支' }, 1660, 40),
      node('record_false', 'record', '远端记录', { event_name: '远端记录' }, 1900, 360),
      node('join_loop', 'loop', '收尾循环', { max_iterations: 1, timeout_s: 10 }, 2180, 180),
      node('end', 'end', '结束', {}, 2460, 220),
    ].map(n => [n.id, n])),
    edges: [
      edge('start', 'out', 'trigger_a'),
      edge('trigger_a', 'out', 'delay_a'),
      edge('delay_a', 'out', 'condition_a'),
      edge('condition_a', 'true', 'record_true'),
      edge('condition_a', 'false', 'record_false'),
      edge('record_true', 'out', 'join_loop'),
      edge('record_false', 'out', 'join_loop'),
      edge('join_loop', 'exit', 'end'),
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

async function startNodeCount(page) {
  return page.evaluate(() => Array.from(document.querySelectorAll('#flowNodes .flow-node'))
    .filter((el) => el.querySelector('.node-body')?.textContent?.trim() === 'start')
    .length);
}

async function canvasScrollState(page) {
  return page.locator('#flowCanvas').evaluate(el => ({
    clientWidth: el.clientWidth,
    clientHeight: el.clientHeight,
    scrollWidth: el.scrollWidth,
    scrollHeight: el.scrollHeight,
    scrollLeft: el.scrollLeft,
    scrollTop: el.scrollTop,
  }));
}

async function viewportState(page) {
  return page.evaluate(() => (
    typeof getFlowViewportState === 'function'
      ? getFlowViewportState()
      : { scale: window.__flowViewportScale || 1, mode: 'missing' }
  ));
}

async function nodeLayoutSnapshot(page) {
  return page.evaluate(() => {
    const nodes = {};
    document.querySelectorAll('#flowNodes .flow-node').forEach((el) => {
      const id = el.id.replace(/^node_/, '');
      nodes[id] = {
        x: Number.parseFloat(el.style.left || '0'),
        y: Number.parseFloat(el.style.top || '0'),
        width: el.getBoundingClientRect().width,
        body: el.querySelector('.node-body')?.textContent?.trim(),
      };
    });
    return {
      nodes,
      edgePairs: flowEdges.map(e => `${e.source}:${e.sourcePort}->${e.target}`).sort(),
      params: Object.fromEntries(Object.entries(flowNodes).map(([id, n]) => [id, n.params || {}])),
    };
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

async function selectedNodeVisibleInCanvas(page) {
  return page.evaluate(() => {
    const selectedId = typeof getSelectedFlowNodeId === 'function' ? getSelectedFlowNodeId() : selectedNodeId;
    const selected = selectedId ? flowNodes[selectedId]?.el : null;
    const canvas = document.getElementById('flowCanvas');
    if (!selected || !canvas) return false;
    const nodeRect = selected.getBoundingClientRect();
    const canvasRect = canvas.getBoundingClientRect();
    return nodeRect.left >= canvasRect.left + 4 &&
      nodeRect.right <= canvasRect.right - 4 &&
      nodeRect.top >= canvasRect.top + 4 &&
      nodeRect.bottom <= canvasRect.bottom - 4;
  });
}

test('G3.1 视口工具条、远端点击、Fit/100、定位和整理流程可用', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 720 });
  const expName = `g31-viewport-${Date.now()}`;
  const expId = await createExperiment(page, expName);
  try {
    await api(page, `/api/experiments/${expId}/flow/save`, {
      method: 'POST',
      data: { flow: viewportFlow() },
    });

    await openExperimentEditor(page, expId);
    await expect.poll(() => startNodeCount(page), { timeout: 5_000 }).toBe(1);

    await expect(page.getByRole('button', { name: /回到全局/ })).toBeVisible();
    await expect(page.getByRole('button', { name: /100%/ })).toBeVisible();
    await expect(page.getByRole('button', { name: /75%/ })).toBeVisible();
    await expect(page.getByRole('button', { name: /定位选中/ })).toBeVisible();
    await expect(page.getByRole('button', { name: /整理流程/ })).toBeVisible();

    const beforeScroll = await canvasScrollState(page);
    expect(beforeScroll.scrollWidth).toBeGreaterThan(beforeScroll.clientWidth);

    const canvasBox = await page.locator('#flowCanvas').boundingBox();
    expect(canvasBox).toBeTruthy();
    await page.mouse.move(canvasBox.x + canvasBox.width / 2, canvasBox.y + canvasBox.height / 2);
    await page.mouse.click(canvasBox.x + canvasBox.width / 2, canvasBox.y + canvasBox.height / 2);
    await page.mouse.wheel(1400, 0);
    let afterWheel = await canvasScrollState(page);
    if (afterWheel.scrollLeft <= beforeScroll.scrollLeft) {
      await page.keyboard.down('Shift');
      await page.mouse.wheel(0, 1400);
      await page.keyboard.up('Shift');
      afterWheel = await canvasScrollState(page);
    }
    expect(afterWheel.scrollLeft).toBeGreaterThan(beforeScroll.scrollLeft);

    const farNode = page.locator('#flowNodes .flow-node').filter({ hasText: '远端记录' }).first();
    await farNode.scrollIntoViewIfNeeded();
    const farBox = await farNode.boundingBox();
    expect(farBox).toBeTruthy();
    await page.mouse.click(farBox.x + Math.min(60, farBox.width / 2), farBox.y + 16);
    await expect(page.locator('#flowConfigPanel')).toBeVisible();
    // v2.4 起节点类型不可编辑：自定义名称改存于 #cfgDisplayName（旧 #cfgLabel 已移除）
    await expect(page.locator('#cfgDisplayName')).toHaveValue('远端记录');
    expect(await selectedNodeVisibleInCanvas(page)).toBeTruthy();

    await page.getByRole('button', { name: /回到全局/ }).click();
    const fitState = await viewportState(page);
    expect(fitState.mode).toBe('fit');
    expect(fitState.scale).toBeLessThanOrEqual(1);

    await page.getByRole('button', { name: /100%/ }).click();
    await expect.poll(() => viewportState(page)).toMatchObject({ scale: 1, mode: '100' });

    await page.getByRole('button', { name: /定位选中/ }).click();
    expect(await selectedNodeVisibleInCanvas(page)).toBeTruthy();

    const beforeLayout = await nodeLayoutSnapshot(page);
    await page.getByRole('button', { name: /整理流程/ }).click();
    const afterLayout = await nodeLayoutSnapshot(page);
    expect(afterLayout.edgePairs).toEqual(beforeLayout.edgePairs);
    expect(afterLayout.params).toEqual(beforeLayout.params);
    expect(afterLayout.nodes.start.x).toBeLessThan(afterLayout.nodes.trigger_a.x);
    expect(afterLayout.nodes.end.x).toBeGreaterThan(afterLayout.nodes.join_loop.x);
    expect(await nodeOverlaps(page)).toEqual([]);
    expect(await startNodeCount(page)).toBe(1);

    await page.getByRole('button', { name: /100%/ }).click();
    await page.setViewportSize({ width: 900, height: 650 });
    await page.waitForTimeout(200);
    await expect(page.getByRole('button', { name: /回到全局/ })).toBeVisible();
    const smallLayout = await nodeLayoutSnapshot(page);
    expect(Math.min(...Object.values(smallLayout.nodes).map(n => n.width))).toBeGreaterThanOrEqual(100);

    await page.screenshot({ path: '/tmp/behavior_box_g31_viewport.png', fullPage: true });
  } finally {
    await cleanupExperiment(page, expId);
  }
});
