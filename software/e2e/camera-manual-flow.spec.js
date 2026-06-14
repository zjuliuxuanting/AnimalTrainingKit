/**
 * Sprint v1.1.5 / G3 closeout: camera + flow integration and manual trigger.
 *
 * 怎么测：
 * - 浏览器进入真实实验和流程编辑页，点击“运行流程”启动。
 * - 点击运行监控里的“手动触发”按钮，确认流程 TRIGGER -> RECORD。
 * - 从浏览器页面内发送 camera-event，模拟 camera.js 上报 zone enter/leave。
 * - 验证切换实验/停止实验后，摄像头事件不会串到当前流程。
 */
const { test, expect } = require('@playwright/test');

test.setTimeout(120_000);

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

function simpleRecordFlow(name, signalId, withDelay = false) {
  const nodes = {
    start: node('start', 'start', '开始', {}, 40, 180),
    trigger: node('trigger', 'trigger', '等待触发', { signal_id: signalId }, 240, 180),
    record: node('record', 'record', '记录事件', { event_name: name }, withDelay ? 600 : 420, 180),
    end: node('end', 'end', '结束', {}, withDelay ? 780 : 600, 180),
  };
  const edges = [
    edge('start', 'out', 'trigger'),
  ];
  if (withDelay) {
    nodes.delay = node('delay', 'delay', '短延时', { duration_value: 0, duration_unit: 'seconds' }, 420, 180);
    edges.push(edge('trigger', 'out', 'delay'));
    edges.push(edge('delay', 'out', 'record'));
  } else {
    edges.push(edge('trigger', 'out', 'record'));
  }
  edges.push(edge('record', 'out', 'end'));
  return {
    id: name.replace(/[^\w]+/g, '_'),
    name,
    nodes,
    edges,
  };
}

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

async function createExperiment(page, name, triggerCamera = false) {
  const created = await api(page, '/api/experiments', {
    method: 'POST',
    data: {
      name,
      subject_id: `mouse-${Date.now()}`,
      species: 'mouse',
      max_duration_min: 1,
      max_trigger_count: 0,
      trigger_manual: true,
      trigger_camera: triggerCamera,
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

async function saveCameraZone(page, expId, zoneName = 'ZoneA') {
  await api(page, '/api/camera/config', {
    method: 'POST',
    data: {
      experiment_id: expId,
      config: {
        zones: [{
          name: zoneName,
          x: 20,
          y: 20,
          width: 120,
          height: 120,
          events: {
            enter: { enabled: true, role: 'trigger' },
            leave: { enabled: true, role: 'trigger' },
          },
        }],
      },
    },
  });
}

async function openExperimentEditor(page, expId) {
  const exp = await api(page, `/api/experiments/${expId}`);
  await page.goto('/');
  await page.locator('#expFilter').fill(exp.name);
  const expRow = page.locator('tr').filter({ has: page.getByRole('cell', { name: exp.name, exact: true }) });
  await expect(expRow).toBeVisible();
  await expRow.getByRole('button', { name: /编辑/ }).click();
  await page.locator('.tab[data-tab="flow"]').click();
  await expect(page.locator('#flowCanvas')).toBeVisible();
  return exp;
}

async function runFlowFromBrowser(page, expId, graph) {
  await api(page, `/api/experiments/${expId}/flow/save`, {
    method: 'POST',
    data: { flow: graph },
  });
  await openExperimentEditor(page, expId);
  await page.getByRole('button', { name: /运行流程/ }).click();
  await expect(page.locator('#tab-monitor')).toBeVisible();
  await expect(page.locator('#btnManualTrigger')).toBeEnabled();
  const state = await api(page, '/api/experiment/state');
  expect(state.engine).toBe('running');
  expect(state.session_id).toBeTruthy();
  return state.session_id;
}

async function sendCameraEventFromBrowser(page, expId, zone, event) {
  return page.evaluate(async ({ expId: browserExpId, zone: browserZone, event: browserEvent }) => {
    const response = await fetch('/api/experiment/camera-event', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        experiment_id: browserExpId,
        zone: browserZone,
        event: browserEvent,
        ts: Date.now(),
      }),
    });
    return response.json();
  }, { expId, zone, event });
}

function parsePayload(raw) {
  if (!raw) return {};
  if (typeof raw === 'object') return raw;
  try {
    return JSON.parse(raw);
  } catch {
    return {};
  }
}

async function waitForRecord(page, sessionId, timeoutMs = 8_000) {
  const startedAt = Date.now();
  let lastEvents = [];
  while (Date.now() - startedAt < timeoutMs) {
    const events = await api(page, `/api/sessions/${sessionId}/events`);
    lastEvents = events.events || [];
    const record = lastEvents.find((ev) => {
      if (ev.event_type !== 'node_executed') return false;
      return parsePayload(ev.raw_payload).type === 'record';
    });
    if (record) return { record, events: lastEvents };
    await page.waitForTimeout(250);
  }
  throw new Error(`record event not found; events=${lastEvents.length}`);
}

test('manual trigger button drives TRIGGER -> RECORD and sources hide mock/timer', async ({ page }) => {
  const expId = await createExperiment(page, `g3-manual-${Date.now()}`, false);
  try {
    const sources = await api(page, `/api/sources?experiment_id=${encodeURIComponent(expId)}`);
    const sourceIds = sources.sources.map(s => s.id);
    expect(sourceIds).toContain('manual:trigger');
    expect(sourceIds.some(id => id.startsWith('mock:') || id.startsWith('timer:'))).toBeFalsy();

    const sessionId = await runFlowFromBrowser(page, expId, simpleRecordFlow('人工事件', 'manual:trigger'));
    await page.locator('#btnManualTrigger').click();
    const { events } = await waitForRecord(page, sessionId);
    expect(events.some(e => e.event_type === 'manual')).toBeTruthy();
    await expect(page.locator('#eventLog')).toContainText('手动触发');
  } finally {
    await api(page, '/api/experiment/stop', { method: 'POST' }).catch(() => {});
    await cleanupExperiment(page, expId);
  }
});

test('camera zone enter drives TRIGGER -> RECORD', async ({ page }) => {
  const expId = await createExperiment(page, `g3-camera-enter-${Date.now()}`, true);
  try {
    await saveCameraZone(page, expId, 'ZoneA');
    const sessionId = await runFlowFromBrowser(page, expId, simpleRecordFlow('摄像头进入', 'camera:ZoneA:enter'));
    const result = await sendCameraEventFromBrowser(page, expId, 'ZoneA', 'enter');
    expect(result.fed_to_flow).toBeTruthy();
    const { events } = await waitForRecord(page, sessionId);
    expect(events.some(e => e.event_type === 'node_triggered')).toBeTruthy();
    await expect(page.locator('#eventLog')).toContainText('摄像头');
  } finally {
    await api(page, '/api/experiment/stop', { method: 'POST' }).catch(() => {});
    await cleanupExperiment(page, expId);
  }
});

test('camera zone enter drives TRIGGER -> DELAY -> RECORD', async ({ page }) => {
  const expId = await createExperiment(page, `g3-camera-delay-${Date.now()}`, true);
  try {
    await saveCameraZone(page, expId, 'ZoneA');
    const sessionId = await runFlowFromBrowser(page, expId, simpleRecordFlow('摄像头延时记录', 'camera:ZoneA:enter', true));
    const result = await sendCameraEventFromBrowser(page, expId, 'ZoneA', 'enter');
    expect(result.fed_to_flow).toBeTruthy();
    const { events } = await waitForRecord(page, sessionId);
    const delayEvent = events.find(e => e.event_type === 'node_executed' && parsePayload(e.raw_payload).type === 'delay');
    expect(delayEvent).toBeTruthy();
  } finally {
    await api(page, '/api/experiment/stop', { method: 'POST' }).catch(() => {});
    await cleanupExperiment(page, expId);
  }
});

test('camera events do not cross experiments and do not trigger after stop', async ({ page }) => {
  const expA = await createExperiment(page, `g3-camera-a-${Date.now()}`, true);
  const expB = await createExperiment(page, `g3-camera-b-${Date.now()}`, true);
  try {
    await saveCameraZone(page, expA, 'ZoneA');
    await saveCameraZone(page, expB, 'ZoneA');
    const sessionId = await runFlowFromBrowser(page, expA, simpleRecordFlow('摄像头隔离', 'camera:ZoneA:enter'));

    const wrong = await sendCameraEventFromBrowser(page, expB, 'ZoneA', 'enter');
    expect(wrong.fed_to_flow).toBeFalsy();
    await page.waitForTimeout(600);
    let events = await api(page, `/api/sessions/${sessionId}/events`);
    expect((events.events || []).some(e => e.event_type === 'node_triggered')).toBeFalsy();

    const right = await sendCameraEventFromBrowser(page, expA, 'ZoneA', 'enter');
    expect(right.fed_to_flow).toBeTruthy();
    await waitForRecord(page, sessionId);

    await page.getByRole('button', { name: /停止实验/ }).click();
    const stopped = await sendCameraEventFromBrowser(page, expA, 'ZoneA', 'enter');
    expect(stopped.fed_to_flow).toBeFalsy();
  } finally {
    await api(page, '/api/experiment/stop', { method: 'POST' }).catch(() => {});
    await cleanupExperiment(page, expA);
    await cleanupExperiment(page, expB);
  }
});
