/**
 * Sprint v1.1.3 - 第 5 链路压缩验收
 *
 * 怎么测：
 * 1. 浏览器进入实验，点击前端节点面板创建 CONDITION / RECORD，确认可配置
 *    daily_quota_count、state_op、cooldown_s。
 * 2. 保存一张合法的“每日定额投喂 / 可持久斯金纳箱”流程到实验。
 * 3. 通过前端“运行流程”按钮启动，观察监控页进入运行状态。
 * 4. 后端辅助校验：3 次投喂锁定额度、20 秒冷却后进入下一压缩日，
 *    至少 2 个压缩日周期，服务重启后 quota_state 仍保留。
 */
const { test, expect } = require('@playwright/test');
const fs = require('fs');
const path = require('path');
const sqlite3 = require('node:sqlite');
const { execFileSync, spawn } = require('child_process');

test.setTimeout(180_000);

const DB_PATH = path.join(__dirname, '..', 'data_store', 'behavior_box.db');

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

function dailyQuotaFlow({ quota = 3, cooldownS = 20, loopIterations = 30, loopTimeoutS = 130 } = {}) {
  return {
    id: 'daily_quota_v113',
    name: '第5链路-每日定额投喂',
    nodes: {
      start: node('start', 'start', '开始', {}, 40, 220),
      quota_available: node('quota_available', 'condition', '额度可用?', {
        source: 'quota_available',
        operator: 'eq',
        value: 1,
        daily_quota_count: quota,
      }, 210, 200),
      cooling: node('cooling', 'condition', '冷却中?', {
        source: 'quota_locked',
        operator: 'eq',
        value: 1,
        daily_quota_count: quota,
      }, 390, 320),
      lever: node('lever', 'trigger', '等待压杆', {
        signal_id: 'mock:default',
        timeout_s: 0,
      }, 390, 110),
      feed: node('feed', 'execute', '出粮1颗', {
        actuator_id: 'actuator:feeder',
        action: 'high',
        duration_ms: 100,
      }, 570, 110),
      record_feed: node('record_feed', 'record', '记录投喂成功', {
        event_name: '投喂成功',
        counter_name: 'feeds_today',
        counter_op: '+1',
        state_op: 'feed_success',
        daily_quota_count: quota,
      }, 740, 110),
      quota_reached: node('quota_reached', 'condition', '达到日定额?', {
        source: 'quota_reached',
        operator: 'eq',
        value: 1,
        daily_quota_count: quota,
      }, 920, 110),
      record_continue: node('record_continue', 'record', '记录继续等待', {
        event_name: '继续等待',
      }, 1090, 70),
      start_cooldown: node('start_cooldown', 'record', '记录开始冷却', {
        event_name: '开始冷却',
        state_op: 'start_cooldown',
        daily_quota_count: quota,
        cooldown_s: cooldownS,
      }, 1090, 170),
      cooldown_delay: node('cooldown_delay', 'delay', '20秒冷却', {
        duration_s: cooldownS,
      }, 570, 320),
      new_day_reset: node('new_day_reset', 'record', '记录新日重置', {
        event_name: '新日重置',
        state_op: 'new_day_reset',
        daily_quota_count: quota,
      }, 740, 320),
      entry_merge: node('entry_merge', 'record', '记录入口汇合', {
        event_name: '入口汇合',
      }, 920, 320),
      loop_merge: node('loop_merge', 'record', '记录循环汇合', {
        event_name: '循环汇合',
      }, 1260, 180),
      cycle: node('cycle', 'loop', '压缩日循环', {
        max_iterations: loopIterations,
        timeout_s: loopTimeoutS,
      }, 1430, 180),
      end: node('end', 'end', '结束', {}, 1600, 220),
    },
    edges: [
      edge('start', 'out', 'entry_merge'),
      edge('entry_merge', 'out', 'quota_available'),
      edge('quota_available', 'true', 'lever'),
      edge('quota_available', 'false', 'cooling'),
      edge('cooling', 'true', 'cooldown_delay'),
      edge('cooling', 'false', 'loop_merge'),
      edge('cooldown_delay', 'out', 'new_day_reset'),
      edge('new_day_reset', 'out', 'loop_merge'),
      edge('lever', 'out', 'feed'),
      edge('feed', 'out', 'record_feed'),
      edge('record_feed', 'out', 'quota_reached'),
      edge('quota_reached', 'false', 'record_continue'),
      edge('quota_reached', 'true', 'start_cooldown'),
      edge('record_continue', 'out', 'loop_merge'),
      edge('start_cooldown', 'out', 'loop_merge'),
      edge('loop_merge', 'out', 'cycle'),
      edge('cycle', 'body', 'entry_merge'),
      edge('cycle', 'exit', 'end'),
    ],
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

async function createExperiment(page, name, maxDurationMin = 2) {
  const created = await api(page, '/api/experiments', {
    method: 'POST',
    data: {
      name,
      subject_id: `hamster-${Date.now()}`,
      species: 'hamster',
      notes: 'Sprint v1.1.3 第5链路压缩验收',
      max_duration_min: maxDurationMin,
      max_trigger_count: 0,
      trigger_manual: true,
      trigger_camera: false,
      trigger_hardware: false,
      start_mode: 'manual',
    },
  });
  return created.id;
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

async function waitForSessionDone(page, sessionId, timeoutMs) {
  const startedAt = Date.now();
  let lastEvents = [];
  while (Date.now() - startedAt < timeoutMs) {
    const state = await api(page, '/api/experiment/state');
    const events = await api(page, `/api/sessions/${sessionId}/events`);
    lastEvents = events.events || [];
    if (state.engine !== 'running') return lastEvents;
    await page.waitForTimeout(1000);
  }
  throw new Error(`session ${sessionId} did not finish in ${timeoutMs}ms; events=${lastEvents.length}`);
}

function readQuotaState(scopeId) {
  const db = new sqlite3.DatabaseSync(DB_PATH, { readOnly: true });
  try {
    const row = db.prepare('SELECT * FROM quota_state WHERE scope_id = ?').get(scopeId);
    return row || null;
  } finally {
    db.close();
  }
}

function getSessionEvents(sessionId) {
  const db = new sqlite3.DatabaseSync(DB_PATH, { readOnly: true });
  try {
    return db.prepare('SELECT * FROM events WHERE session_id = ? ORDER BY ts_ms ASC').all(sessionId);
  } finally {
    db.close();
  }
}

async function restartServer(page) {
  const projectRoot = path.join(__dirname, '..');
  const resultsDir = path.join(projectRoot, 'test-results');
  fs.mkdirSync(resultsDir, { recursive: true });

  try {
    execFileSync('pkill', ['-f', 'server.py --port 8000'], { stdio: 'ignore' });
  } catch {
    // Server may already be stopped.
  }
  await page.waitForTimeout(1200);

  const logPath = path.join(resultsDir, 'daily-quota-restart-server.log');
  const logFd = fs.openSync(logPath, 'a');
  const proc = spawn('python3', ['server.py', '--port', '8000'], {
    cwd: projectRoot,
    detached: true,
    stdio: ['ignore', logFd, logFd],
  });
  proc.unref();
  fs.writeFileSync(path.join(resultsDir, 'daily-quota-restart-server.pid'), String(proc.pid));

  for (let i = 0; i < 40; i++) {
    try {
      const response = await page.request.fetch('/api/experiment/state', { timeout: 1000 });
      if (response.ok()) return proc.pid;
    } catch {
      // Wait for uvicorn to bind.
    }
    await page.waitForTimeout(500);
  }
  throw new Error(`server did not restart; see ${logPath}`);
}

test.describe('Sprint v1.1.3 第5链路 - 每日定额投喂', () => {
  test('前端可配置 quota 参数，并能运行 3 次/20 秒/2 周期压缩验收', async ({ page }) => {
    const expName = `v113-daily-quota-${Date.now()}`;
    const expId = await createExperiment(page, expName, 2);
    const flow = dailyQuotaFlow();

    await api(page, `/api/experiments/${expId}/flow/save`, {
      method: 'POST',
      data: { flow },
    });

    await page.goto('/');
    await page.getByPlaceholder('筛选动物编号或名称...').fill(expName);
    await expect(page.getByText(expName)).toBeVisible();
    await page.getByRole('button', { name: /编辑/ }).first().click();
    await expect(page.locator('#tab-flow')).toBeVisible();

    await page.locator('.palette-item[data-type="condition"]').click();
    await expect(page.locator('#cfg_source')).toBeVisible();
    await page.locator('#cfg_source').selectOption('quota_available');
    await expect(page.locator('#cfg_daily_quota_count')).toBeVisible();
    await page.locator('#cfg_daily_quota_count').fill('3');

    await page.locator('.palette-item[data-type="record"]').click();
    await expect(page.locator('#cfg_state_op')).toBeVisible();
    await page.locator('#cfg_state_op').selectOption('feed_success');
    await expect(page.locator('#cfg_daily_quota_count')).toBeVisible();
    await expect(page.locator('#cfg_cooldown_s')).toBeVisible();
    await page.locator('#cfg_cooldown_s').fill('20');

    await page.evaluate((flowData) => {
      loadFlowData(flowData);
    }, flow);
    await api(page, `/api/experiments/${expId}/flow/save`, {
      method: 'POST',
      data: { flow },
    });
    await page.getByRole('button', { name: /运行流程/ }).click();
    await expect(page.locator('#tab-monitor')).toBeVisible();

    const state = await api(page, '/api/experiment/state');
    expect(state.engine).toBe('running');
    expect(state.session_id).toBeTruthy();

    const events = await waitForSessionDone(page, state.session_id, 150_000);
    const outputEvents = events.filter(e => e.event_type === 'output_executed');
    const nodeEvents = events.filter(e => e.event_type === 'node_executed').map(e => ({
      ...e,
      payload: parsePayload(e.raw_payload),
    }));
    const recordEvents = nodeEvents.filter(e => e.payload.type === 'record');
    const feedRecords = recordEvents.filter(e => e.node_id === 'record_feed');
    const resetRecords = recordEvents.filter(e => e.node_id === 'new_day_reset');
    const startCooldownRecords = recordEvents.filter(e => e.node_id === 'start_cooldown');

    expect(outputEvents.length).toBeGreaterThanOrEqual(6);
    expect(outputEvents.length % 3).toBe(0);
    expect(feedRecords.length).toBeGreaterThanOrEqual(6);
    expect(startCooldownRecords.length).toBeGreaterThanOrEqual(2);
    expect(resetRecords.length).toBeGreaterThanOrEqual(2);
    expect(recordEvents.length).toBeGreaterThan(feedRecords.length);

    const stateAfterRun = readQuotaState(expId);
    expect(stateAfterRun).toBeTruthy();
    expect(Number(stateAfterRun.daily_quota_count)).toBe(3);
    expect(Number(stateAfterRun.day_index)).toBeGreaterThanOrEqual(3);
  });

  test('服务重启后额度和冷却状态保留', async ({ page }) => {
    const expName = `v113-daily-quota-restart-${Date.now()}`;
    const expId = await createExperiment(page, expName, 1);
    const flow = dailyQuotaFlow({ loopIterations: 8, loopTimeoutS: 70 });

    await api(page, `/api/experiments/${expId}/flow/save`, {
      method: 'POST',
      data: { flow },
    });
    const run = await api(page, '/api/experiment/run-flow', {
      method: 'POST',
      data: { experiment_id: expId, duration: 18 },
    });

    const events = await waitForSessionDone(page, run.session_id, 35_000);
    const outputCount = events.filter(e => e.event_type === 'output_executed').length;
    expect(outputCount).toBe(3);

    const stateBeforeRestart = readQuotaState(expId);
    expect(stateBeforeRestart).toBeTruthy();
    expect(Number(stateBeforeRestart.feeds_today)).toBe(3);
    expect(Number(stateBeforeRestart.quota_locked)).toBe(1);
    expect(Number(stateBeforeRestart.cooldown_until)).toBeGreaterThan(Date.now() / 1000);

    await restartServer(page);
    const stateAfterRestart = readQuotaState(expId);
    expect(stateAfterRestart).toBeTruthy();
    expect(Number(stateAfterRestart.feeds_today)).toBe(3);
    expect(Number(stateAfterRestart.daily_quota_count)).toBe(3);
    expect(Number(stateAfterRestart.quota_locked)).toBe(1);
    expect(Number(stateAfterRestart.cooldown_until)).toBe(Number(stateBeforeRestart.cooldown_until));

    const resumed = await api(page, '/api/experiment/run-flow', {
      method: 'POST',
      data: { experiment_id: expId, duration: 55 },
    });
    const resumedEvents = await waitForSessionDone(page, resumed.session_id, 75_000);
    const resumedOutputCount = resumedEvents.filter(e => e.event_type === 'output_executed').length;
    const resumedRecords = resumedEvents
      .filter(e => e.event_type === 'node_executed')
      .map(e => ({ ...e, payload: parsePayload(e.raw_payload) }))
      .filter(e => e.payload.type === 'record');

    expect(resumedOutputCount).toBeGreaterThanOrEqual(3);
    expect(resumedRecords.some(e => e.node_id === 'new_day_reset')).toBeTruthy();
    expect(Number(readQuotaState(expId).day_index)).toBeGreaterThanOrEqual(2);
  });
});
