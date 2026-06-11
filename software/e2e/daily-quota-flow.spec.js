/**
 * Sprint v1.1.5 - generic variables / persistence / delay units regression.
 *
 * 怎么测：
 * - 用真实浏览器点击节点面板，确认 CONDITION / RECORD / DELAY 配置项是通用变量模型。
 * - 运行“每日定额投喂 / 可持久斯金纳箱”流程：3 次投喂达到 100% 日定额，20 秒冷却代表压缩 20 小时。
 * - 读取内部 variable_state 辅助确认持久变量跨服务重启保留。
 * - 默认实时事件日志只验流程事件，不把 raw signal 当成实验人员日志。
 */
const { test, expect } = require('@playwright/test');
const fs = require('fs');
const path = require('path');
const sqlite3 = require('node:sqlite');
const { execFileSync, spawn } = require('child_process');

test.setTimeout(240_000);

const DB_PATH = path.join(__dirname, '..', 'data_store', 'behavior_box.db');
const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:8001';
const SERVER_PORT = new URL(BASE_URL).port || '8000';

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

function delayParams(value, unit = 'seconds') {
  return { duration_value: value, duration_unit: unit };
}

function dailyQuotaFlow({ quota = 3, cooldownValue = 20, cooldownUnit = 'seconds', loopIterations = 12, loopTimeoutS = 100 } = {}) {
  return {
    id: 'daily_quota_generic_variables',
    name: '第5链路-每日定额投喂-通用变量',
    nodes: {
      start: node('start', 'start', '开始', {}, 40, 220),
      set_quota: node('set_quota', 'record', '设置日定额', {
        event_name: '设置日定额',
        variable_name: 'daily_quota_count',
        variable_op: 'set',
        variable_value: quota,
        variable_persistent: true,
      }, 210, 220),
      entry_merge: node('entry_merge', 'record', '入口汇合', { event_name: '入口汇合' }, 390, 220),
      cooling: node('cooling', 'condition', '冷却中?', {
        source: 'variable',
        variable_name: 'quota_locked',
        operator: 'eq',
        value: 1,
      }, 570, 260),
      quota_left: node('quota_left', 'condition', '仍有额度?', {
        source: 'variable',
        variable_name: 'feeds_today',
        operator: 'lt',
        compare_source: 'variable',
        compare_variable_name: 'daily_quota_count',
      }, 750, 110),
      lever: node('lever', 'trigger', '等待压杆', { signal_id: 'manual:trigger' }, 930, 80),
      feed: node('feed', 'execute', '出粮1颗', { actuator_id: 'actuator:feeder', action: 'high' }, 1110, 80),
      record_feed: node('record_feed', 'record', '记录投喂成功', {
        event_name: '投喂成功',
        variable_name: 'feeds_today',
        variable_op: 'add',
        variable_value: 1,
        variable_persistent: true,
      }, 1290, 80),
      quota_reached: node('quota_reached', 'condition', '达到日定额?', {
        source: 'variable',
        variable_name: 'feeds_today',
        operator: 'gte',
        compare_source: 'variable',
        compare_variable_name: 'daily_quota_count',
      }, 1470, 80),
      record_continue: node('record_continue', 'record', '继续等待', { event_name: '继续等待' }, 1650, 20),
      lock_quota: node('lock_quota', 'record', '开始冷却', {
        event_name: '开始冷却',
        variable_name: 'quota_locked',
        variable_op: 'set',
        variable_value: 1,
        variable_persistent: true,
      }, 1650, 150),
      cooldown_delay: node('cooldown_delay', 'delay', '20秒冷却', delayParams(cooldownValue, cooldownUnit), 750, 350),
      reset_feeds: node('reset_feeds', 'record', '重置投喂数', {
        event_name: '重置投喂数',
        variable_name: 'feeds_today',
        variable_op: 'set',
        variable_value: 0,
        variable_persistent: true,
      }, 930, 350),
      unlock_quota: node('unlock_quota', 'record', '解除冷却', {
        event_name: '解除冷却',
        variable_name: 'quota_locked',
        variable_op: 'set',
        variable_value: 0,
        variable_persistent: true,
      }, 1110, 350),
      inc_day: node('inc_day', 'record', '压缩日+1', {
        event_name: '新压缩日',
        variable_name: 'day_index',
        variable_op: 'add',
        variable_value: 1,
        variable_persistent: true,
      }, 1290, 350),
      loop_merge: node('loop_merge', 'record', '循环汇合', { event_name: '循环汇合' }, 1830, 180),
      cycle: node('cycle', 'loop', '压缩日循环', { max_iterations: loopIterations, timeout_s: loopTimeoutS }, 2010, 180),
      end: node('end', 'end', '结束', {}, 2190, 220),
    },
    edges: [
      edge('start', 'out', 'set_quota'),
      edge('set_quota', 'out', 'entry_merge'),
      edge('entry_merge', 'out', 'cooling'),
      edge('cooling', 'true', 'cooldown_delay'),
      edge('cooling', 'false', 'quota_left'),
      edge('quota_left', 'true', 'lever'),
      edge('quota_left', 'false', 'lock_quota'),
      edge('lever', 'out', 'feed'),
      edge('feed', 'out', 'record_feed'),
      edge('record_feed', 'out', 'quota_reached'),
      edge('quota_reached', 'false', 'record_continue'),
      edge('quota_reached', 'true', 'lock_quota'),
      edge('record_continue', 'out', 'loop_merge'),
      edge('lock_quota', 'out', 'loop_merge'),
      edge('cooldown_delay', 'out', 'reset_feeds'),
      edge('reset_feeds', 'out', 'unlock_quota'),
      edge('unlock_quota', 'out', 'inc_day'),
      edge('inc_day', 'out', 'loop_merge'),
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
      notes: 'generic variable daily quota regression',
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

async function cleanupExperiment(page, expId) {
  if (!expId) return;
  await page.request.delete(`/api/experiments/${expId}`).catch(() => {});
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

async function openExperimentEditor(page, expId) {
  const exp = await api(page, `/api/experiments/${expId}`);
  await page.goto('/');
  await page.getByPlaceholder('筛选动物编号或名称...').fill(exp.name);
  const expRow = page.locator('tr').filter({ has: page.getByRole('cell', { name: exp.name, exact: true }) });
  await expect(expRow).toBeVisible();
  await expRow.getByRole('button', { name: /编辑/ }).click();
  await expect(page.locator('#tab-flow')).toBeVisible();
  return exp;
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

async function clickManualTriggerWhileRunning(page, maxClicks, intervalMs = 250) {
  for (let i = 0; i < maxClicks; i++) {
    const state = await api(page, '/api/experiment/state');
    if (state.engine !== 'running') return;
    const btn = page.locator('#btnManualTrigger');
    await expect(btn).toBeEnabled();
    await btn.click();
    await page.waitForTimeout(intervalMs);
  }
}

async function postManualTriggerWhileRunning(page, maxClicks, intervalMs = 250) {
  for (let i = 0; i < maxClicks; i++) {
    const state = await api(page, '/api/experiment/state');
    if (state.engine !== 'running') return;
    await api(page, '/api/experiment/manual-trigger', {
      method: 'POST',
      data: { experiment_id: state.experiment_id || '' },
    });
    await page.waitForTimeout(intervalMs);
  }
}

function readVariableState(scopeId) {
  const db = new sqlite3.DatabaseSync(DB_PATH, { readOnly: true });
  try {
    const rows = db.prepare(
      'SELECT variable_name, value FROM variable_state WHERE scope_id = ? ORDER BY variable_name'
    ).all(scopeId);
    return Object.fromEntries(rows.map(row => [row.variable_name, Number(row.value)]));
  } finally {
    db.close();
  }
}

async function restartServer(page) {
  const projectRoot = path.join(__dirname, '..');
  const resultsDir = path.join(projectRoot, 'test-results');
  fs.mkdirSync(resultsDir, { recursive: true });

  try {
    execFileSync('pkill', ['-f', `server.py --port ${SERVER_PORT}`], { stdio: 'ignore' });
  } catch {
    // Server may already be stopped.
  }
  await page.waitForTimeout(1200);

  const logPath = path.join(resultsDir, 'daily-quota-restart-server.log');
  const logFd = fs.openSync(logPath, 'a');
  const proc = spawn('python3', ['server.py', '--port', SERVER_PORT], {
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
  throw new Error(`server did not restart on ${SERVER_PORT}; see ${logPath}`);
}

test.describe('Sprint v1.1.5 第5链路 - 通用变量 / 持久化 / 时间单位', () => {
  test('前端可配置通用变量和 DELAY 单位，并且旧 quota 字段不再出现', async ({ page }) => {
    const expName = `v115-variable-config-${Date.now()}`;
    const expId = await createExperiment(page, expName, 1);
    try {
      await openExperimentEditor(page, expId);

      await page.locator('.palette-item[data-type="condition"]').click();
      await expect(page.locator('#cfg_source')).toBeVisible();
      await page.locator('#cfg_source').selectOption('variable');
      await expect(page.locator('#cfg_variable_name')).toBeVisible();
      await page.locator('#cfg_variable_name').fill('feeds_today');
      await page.locator('#cfg_operator').selectOption('lt');
      await page.locator('#cfg_compare_source').selectOption('variable');
      await expect(page.locator('#cfg_compare_variable_name')).toBeVisible();
      await page.locator('#cfg_compare_variable_name').fill('daily_quota_count');

      await page.locator('.palette-item[data-type="record"]').click();
      await expect(page.locator('#cfg_variable_name')).toBeVisible();
      await page.locator('#cfg_event_name').fill('变量记录');
      await page.locator('#cfg_variable_name').fill('runtime_score');
      await page.locator('#cfg_variable_op').selectOption('subtract');
      await page.locator('#cfg_variable_value').fill('0');
      await page.locator('#cfg_variable_persistent').check();
      await expect(page.locator('#cfg_state_op')).toHaveCount(0);
      await expect(page.locator('#cfg_daily_quota_count')).toHaveCount(0);
      await expect(page.locator('#cfg_cooldown_s')).toHaveCount(0);

      await page.locator('.palette-item[data-type="delay"]').click();
      await expect(page.locator('#cfg_duration_value')).toBeVisible();
      await page.locator('#cfg_duration_value').fill('0');
      await page.locator('#cfg_duration_unit').selectOption('seconds');
      await page.locator('#cfg_duration_unit').selectOption('minutes');
      await page.locator('#cfg_duration_unit').selectOption('hours');

      await page.screenshot({ path: 'test-results/daily-quota-generic-config.png', fullPage: true });
    } finally {
      await cleanupExperiment(page, expId);
    }
  });

  test('3次投喂达到100%日定额，20秒冷却后进入至少2个压缩日周期', async ({ page }) => {
    const expName = `v115-daily-quota-${Date.now()}`;
    const expId = await createExperiment(page, expName, 2);
    const graph = dailyQuotaFlow({ cooldownValue: 20, loopIterations: 12, loopTimeoutS: 100 });
    try {
      await api(page, `/api/experiments/${expId}/flow/save`, {
        method: 'POST',
        data: { flow: graph },
      });
      await openExperimentEditor(page, expId);
      await page.getByRole('button', { name: /运行流程/ }).click();
      await expect(page.locator('#tab-monitor')).toBeVisible();

      const state = await api(page, '/api/experiment/state');
      expect(state.engine).toBe('running');
      expect(state.session_id).toBeTruthy();

      await clickManualTriggerWhileRunning(page, 9);
      await page.waitForTimeout(21_000);
      await clickManualTriggerWhileRunning(page, 6);
      const events = await waitForSessionDone(page, state.session_id, 125_000);
      const outputEvents = events.filter(e => e.event_type === 'output_executed');
      const recordEvents = events
        .filter(e => e.event_type === 'node_executed')
        .map(e => ({ ...e, payload: parsePayload(e.raw_payload) }))
        .filter(e => e.payload.type === 'record');
      const feedRecords = recordEvents.filter(e => e.node_id === 'record_feed');
      const lockRecords = recordEvents.filter(e => e.node_id === 'lock_quota');
      const resetRecords = recordEvents.filter(e => e.node_id === 'reset_feeds');

      expect(outputEvents.length).toBeGreaterThanOrEqual(6);
      expect(feedRecords.length).toBeGreaterThanOrEqual(6);
      expect(lockRecords.length).toBeGreaterThanOrEqual(2);
      expect(resetRecords.length).toBeGreaterThanOrEqual(2);

      const variables = readVariableState(expId);
      expect(variables.daily_quota_count).toBe(3);
      expect(variables.day_index).toBeGreaterThanOrEqual(2);
      expect(variables.feeds_today).toBeLessThanOrEqual(3);
    } finally {
      await cleanupExperiment(page, expId);
    }
  });

  test('停止实验后仍停留当前实验，默认实时日志不显示 raw signal', async ({ page }) => {
    const expName = `v115-stop-context-${Date.now()}`;
    const expId = await createExperiment(page, expName, 1);
    const graph = dailyQuotaFlow({ cooldownValue: 20, loopIterations: 5, loopTimeoutS: 60 });
    try {
      await api(page, `/api/experiments/${expId}/flow/save`, {
        method: 'POST',
        data: { flow: graph },
      });
      const exp = await openExperimentEditor(page, expId);
      await expect(page.locator('#currentExpBadge')).toContainText(exp.name);
      await page.getByRole('button', { name: /运行流程/ }).click();
      await expect(page.locator('#tab-monitor')).toBeVisible();
      await clickManualTriggerWhileRunning(page, 2);
      await page.waitForTimeout(3500);
      await page.getByRole('button', { name: /停止实验/ }).click();
      await expect(page.locator('#currentExpBadge')).toContainText(exp.name);
      await expect(page.locator('#btnRunFlow')).toBeEnabled();
      await page.locator('.tab[data-tab="flow"]').click();
      await expect(page.locator('#flowCanvas')).toBeVisible();

      const eventLogText = await page.locator('#eventLog').innerText();
      expect(eventLogText).toMatch(/实验已停止|触发|记录|执行|冷却|启动/);
      expect(eventLogText).not.toMatch(/raw signal|mock:0:mock:default|camera_|timer_/i);
    } finally {
      await cleanupExperiment(page, expId);
    }
  });

  test('服务重启后持久变量保留，恢复运行后冷却结束并继续投喂', async ({ page }) => {
    const expName = `v115-daily-quota-restart-${Date.now()}`;
    const expId = await createExperiment(page, expName, 1);
    const graph = dailyQuotaFlow({ cooldownValue: 20, loopIterations: 6, loopTimeoutS: 70 });
    try {
      await api(page, `/api/experiments/${expId}/flow/save`, {
        method: 'POST',
        data: { flow: graph },
      });
      const run = await api(page, '/api/experiment/run-flow', {
        method: 'POST',
        data: { experiment_id: expId, duration: 10 },
      });
      await postManualTriggerWhileRunning(page, 3);

      const events = await waitForSessionDone(page, run.session_id, 35_000);
      const outputCount = events.filter(e => e.event_type === 'output_executed').length;
      expect(outputCount).toBe(3);

      const beforeRestart = readVariableState(expId);
      expect(beforeRestart.daily_quota_count).toBe(3);
      expect(beforeRestart.feeds_today).toBe(3);
      expect(beforeRestart.quota_locked).toBe(1);

      await restartServer(page);
      const afterRestart = readVariableState(expId);
      expect(afterRestart.daily_quota_count).toBe(3);
      expect(afterRestart.feeds_today).toBe(3);
      expect(afterRestart.quota_locked).toBe(1);

      const resumed = await api(page, '/api/experiment/run-flow', {
        method: 'POST',
        data: { experiment_id: expId, duration: 65 },
      });
      await page.waitForTimeout(21_000);
      await postManualTriggerWhileRunning(page, 3);
      const resumedEvents = await waitForSessionDone(page, resumed.session_id, 85_000);
      const resumedOutputCount = resumedEvents.filter(e => e.event_type === 'output_executed').length;
      const resumedRecords = resumedEvents
        .filter(e => e.event_type === 'node_executed')
        .map(e => ({ ...e, payload: parsePayload(e.raw_payload) }))
        .filter(e => e.payload.type === 'record');

      expect(resumedOutputCount).toBeGreaterThanOrEqual(3);
      expect(resumedRecords.some(e => e.node_id === 'reset_feeds')).toBeTruthy();
      expect(readVariableState(expId).day_index).toBeGreaterThanOrEqual(1);
    } finally {
      await cleanupExperiment(page, expId);
    }
  });
});
