/**
 * Sprint v1.1.3 门禁：五条典型链路能搭、能跑、能记。
 *
 * 怎么测：
 * - 每条链路先通过 API 保存到实验，模拟实验人员选择已有范式。
 * - 浏览器进入实验，点击“运行流程”启动。
 * - 后端辅助读取内部事件，确认流程触发并产生 RECORD 链路事件。
 * - CSV / 导出 / 图表不参与本轮判断。
 */
const { test, expect } = require('@playwright/test');

test.setTimeout(300_000);

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

function flow(name, nodes, edges) {
  return {
    id: name.replace(/[^\w]+/g, '_'),
    name,
    nodes: Object.fromEntries(nodes.map(n => [n.id, n])),
    edges,
  };
}

function fr1Flow() {
  return flow('范式1-FR1操作性条件反射', [
    node('start', 'start', '开始', {}, 40, 200),
    node('lever', 'trigger', '压杆', { signal_id: 'mock:default' }, 220, 200),
    node('wait', 'delay', '短等待', { duration_s: 0.1 }, 400, 200),
    node('feed', 'execute', '给食奖励', { actuator_id: 'actuator:feeder', action: 'high' }, 580, 200),
    node('record', 'record', '记录压杆奖励', { event_name: '压杆奖励' }, 760, 200),
    node('loop', 'loop', '循环上限', { max_iterations: 2, timeout_s: 20 }, 940, 200),
    node('end', 'end', '结束', {}, 1120, 200),
  ], [
    edge('start', 'out', 'lever'),
    edge('lever', 'out', 'wait'),
    edge('wait', 'out', 'feed'),
    edge('feed', 'out', 'record'),
    edge('record', 'out', 'loop'),
    edge('loop', 'body', 'lever'),
    edge('loop', 'exit', 'end'),
  ]);
}

function socialChoiceFlow() {
  return flow('范式2-社会性自我给药选择', [
    node('start', 'start', '开始', {}, 40, 220),
    node('iti', 'delay', 'ITI', { duration_s: 0.1 }, 200, 220),
    node('trial', 'execute', '试次开始', { actuator_id: 'actuator:light', action: 'high' }, 360, 220),
    node('choice', 'fork', '选择分叉', {}, 520, 220),
    node('social_nose', 'trigger', '社交鼻触', { signal_id: 'mock:default' }, 700, 110),
    node('social_delay', 'delay', '社交短等待', { duration_s: 0.1 }, 880, 110),
    node('open_door', 'execute', '开门见同伴', { actuator_id: 'actuator:light', action: 'high' }, 1060, 110),
    node('food_nose', 'trigger', '食物鼻触', { signal_id: 'mock:default' }, 700, 330),
    node('food_delay', 'delay', '食物短等待', { duration_s: 0.1 }, 880, 330),
    node('feed', 'execute', '给食', { actuator_id: 'actuator:feeder', action: 'high' }, 1060, 330),
    node('record_choice', 'record', '记录选择', { event_name: '选择事件' }, 1240, 220),
    node('loop', 'loop', '下一试次', { max_iterations: 1, timeout_s: 20 }, 1420, 220),
    node('end', 'end', '结束', {}, 1600, 220),
  ], [
    edge('start', 'out', 'iti'),
    edge('iti', 'out', 'trial'),
    edge('trial', 'out', 'choice'),
    edge('choice', 'continue', 'social_nose'),
    edge('social_nose', 'out', 'social_delay'),
    edge('social_delay', 'out', 'open_door'),
    edge('open_door', 'out', 'record_choice'),
    edge('choice', 'stop', 'food_nose'),
    edge('food_nose', 'out', 'food_delay'),
    edge('food_delay', 'out', 'feed'),
    edge('feed', 'out', 'record_choice'),
    edge('record_choice', 'out', 'loop'),
    edge('loop', 'body', 'iti'),
    edge('loop', 'exit', 'end'),
  ]);
}

function fiveCsrttFlow() {
  return flow('范式3-5CSRTT', [
    node('start', 'start', '开始', {}, 40, 220),
    node('iti', 'delay', 'ITI', { duration_s: 0.1 }, 200, 220),
    node('light', 'execute', '随机亮灯', { actuator_id: 'actuator:light', action: 'high' }, 360, 220),
    node('fork', 'fork', '反应或遗漏', {}, 520, 220),
    node('nose', 'trigger', '鼻触', { signal_id: 'mock:default' }, 700, 80),
    node('correct_cond', 'condition', '正确孔?', { source: 'trigger_count', operator: 'gte', value: 1 }, 880, 80),
    node('reward_delay', 'delay', '正确等待', { duration_s: 0.1 }, 1060, 40),
    node('reward', 'execute', '给食', { actuator_id: 'actuator:feeder', action: 'high' }, 1240, 40),
    node('record_correct', 'record', '记录正确', { event_name: '正确' }, 1420, 40),
    node('punish_wrong', 'execute', '错误惩罚', { actuator_id: 'actuator:buzzer', action: 'high' }, 1060, 160),
    node('record_wrong', 'record', '记录错误', { event_name: '错误' }, 1240, 160),
    node('timeout_delay', 'delay', '无反应超时', { duration_s: 6 }, 700, 360),
    node('punish_omit', 'execute', '遗漏惩罚', { actuator_id: 'actuator:buzzer', action: 'high' }, 880, 360),
    node('record_omit', 'record', '记录遗漏', { event_name: '遗漏' }, 1060, 360),
    node('trial_end', 'delay', '试次结束', { duration_s: 0.1 }, 1600, 220),
    node('loop', 'loop', '下一试次', { max_iterations: 1, timeout_s: 30 }, 1780, 220),
    node('end', 'end', '结束', {}, 1960, 220),
  ], [
    edge('start', 'out', 'iti'),
    edge('iti', 'out', 'light'),
    edge('light', 'out', 'fork'),
    edge('fork', 'continue', 'nose'),
    edge('nose', 'out', 'correct_cond'),
    edge('correct_cond', 'true', 'reward_delay'),
    edge('reward_delay', 'out', 'reward'),
    edge('reward', 'out', 'record_correct'),
    edge('record_correct', 'out', 'trial_end'),
    edge('correct_cond', 'false', 'punish_wrong'),
    edge('punish_wrong', 'out', 'record_wrong'),
    edge('record_wrong', 'out', 'trial_end'),
    edge('fork', 'stop', 'timeout_delay'),
    edge('timeout_delay', 'out', 'punish_omit'),
    edge('punish_omit', 'out', 'record_omit'),
    edge('record_omit', 'out', 'trial_end'),
    edge('trial_end', 'out', 'loop'),
    edge('loop', 'body', 'iti'),
    edge('loop', 'exit', 'end'),
  ]);
}

function signTrackingFlow() {
  return flow('范式4-SignTracking目标追踪', [
    node('start', 'start', '开始', {}, 40, 220),
    node('iti', 'delay', 'ITI', { duration_s: 0.8 }, 200, 220),
    node('cue', 'execute', '插入杠杆+亮灯', { actuator_id: 'actuator:light', action: 'high' }, 380, 220),
    node('cs', 'delay', 'CS等待', { duration_s: 0.8 }, 560, 220),
    node('feed', 'execute', '自动给食', { actuator_id: 'actuator:feeder', action: 'high' }, 740, 220),
    node('record_trial', 'record', '记录试次结束', { event_name: '试次结束' }, 920, 220),
    node('loop', 'loop', '下一试次', { max_iterations: 2, timeout_s: 20 }, 1100, 220),
    node('end', 'end', '结束', {}, 1280, 220),
    node('sign_sniffer', 'sniffer', '杠杆接近探针', { signal_id: 'mock:timer', event_name: 'sign-tracking' }, 380, 420),
    node('goal_sniffer', 'sniffer', '食槽接近探针', { signal_id: 'mock:timer', event_name: 'goal-tracking' }, 560, 420),
  ], [
    edge('start', 'out', 'iti'),
    edge('iti', 'out', 'cue'),
    edge('cue', 'out', 'cs'),
    edge('cs', 'out', 'feed'),
    edge('feed', 'out', 'record_trial'),
    edge('record_trial', 'out', 'loop'),
    edge('loop', 'body', 'iti'),
    edge('loop', 'exit', 'end'),
  ]);
}

function dailyQuotaSmokeFlow() {
  return flow('范式5-每日定额投喂-smoke', [
    node('start', 'start', '开始', {}, 40, 220),
    node('entry_merge', 'record', '记录入口汇合', { event_name: '入口汇合' }, 200, 220),
    node('quota_available', 'condition', '额度可用?', { source: 'quota_available', operator: 'eq', value: 1, daily_quota_count: 3 }, 380, 220),
    node('cooling', 'condition', '冷却中?', { source: 'quota_locked', operator: 'eq', value: 1, daily_quota_count: 3 }, 560, 340),
    node('lever', 'trigger', '等待压杆', { signal_id: 'mock:default' }, 560, 80),
    node('feed', 'execute', '出粮1颗', { actuator_id: 'actuator:feeder', action: 'high' }, 740, 80),
    node('record_feed', 'record', '记录投喂成功', { event_name: '投喂成功', counter_name: 'feeds_today', counter_op: '+1', state_op: 'feed_success', daily_quota_count: 3 }, 920, 80),
    node('quota_reached', 'condition', '达到日定额?', { source: 'quota_reached', operator: 'eq', value: 1, daily_quota_count: 3 }, 1100, 80),
    node('record_continue', 'record', '记录继续等待', { event_name: '继续等待' }, 1280, 20),
    node('start_cooldown', 'record', '记录开始冷却', { event_name: '开始冷却', state_op: 'start_cooldown', daily_quota_count: 3, cooldown_s: 0.2 }, 1280, 140),
    node('cooldown_delay', 'delay', '短冷却', { duration_s: 0.2 }, 740, 340),
    node('new_day_reset', 'record', '记录新日重置', { event_name: '新日重置', state_op: 'new_day_reset', daily_quota_count: 3 }, 920, 340),
    node('loop_merge', 'record', '记录循环汇合', { event_name: '循环汇合' }, 1460, 160),
    node('loop', 'loop', '压缩日循环', { max_iterations: 4, timeout_s: 50 }, 1640, 160),
    node('end', 'end', '结束', {}, 1820, 220),
  ], [
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
    edge('loop_merge', 'out', 'loop'),
    edge('loop', 'body', 'entry_merge'),
    edge('loop', 'exit', 'end'),
  ]);
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

async function createExperiment(page, name) {
  const created = await api(page, '/api/experiments', {
    method: 'POST',
    data: {
      name: `${name}-${Date.now()}`,
      subject_id: `mouse-${Date.now()}`,
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

function parsePayload(raw) {
  if (!raw) return {};
  if (typeof raw === 'object') return raw;
  try {
    return JSON.parse(raw);
  } catch {
    return {};
  }
}

async function startNodeCount(page) {
  return page.evaluate(() => Array.from(document.querySelectorAll('#flowNodes .flow-node'))
    .filter((el) => el.querySelector('.node-body')?.textContent?.trim() === 'start')
    .length);
}

async function waitForDone(page, sessionId, timeoutMs = 70_000) {
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    const state = await api(page, '/api/experiment/state');
    const events = await api(page, `/api/sessions/${sessionId}/events`);
    if (state.engine !== 'running') return events.events || [];
    await page.waitForTimeout(1000);
  }
  throw new Error(`session ${sessionId} did not finish within ${timeoutMs}ms`);
}

async function runFlowFromBrowser(page, expId, flowData) {
  await api(page, `/api/experiments/${expId}/flow/save`, {
    method: 'POST',
    data: { flow: flowData },
  });
  await page.goto('/');
  const exp = await api(page, `/api/experiments/${expId}`);
  await page.locator('#expFilter').fill(exp.name);
  await expect(page.getByText(exp.name)).toBeVisible();
  await page.locator('tr').filter({ hasText: exp.name }).getByRole('button', { name: /编辑/ }).click();
  await expect(page.locator('#tab-flow')).toBeVisible();
  await expect.poll(() => startNodeCount(page), { timeout: 5_000 }).toBe(1);
  await page.getByRole('button', { name: /运行流程/ }).click();
  await expect(page.locator('#tab-monitor')).toBeVisible();
  const state = await api(page, '/api/experiment/state');
  expect(state.engine).toBe('running');
  return waitForDone(page, state.session_id);
}

test('五条典型链路能前端运行并写入 RECORD 内部事件', async ({ page }) => {
  const cases = [
    { name: 'FR1', graph: fr1Flow(), minRecords: 2, needsTrigger: true },
    { name: '社会性选择', graph: socialChoiceFlow(), minRecords: 1, needsTrigger: true },
    { name: '5-CSRTT', graph: fiveCsrttFlow(), minRecords: 1, needsTrigger: true },
    { name: 'SignTracking', graph: signTrackingFlow(), minRecords: 2, needsSniffer: true },
    { name: '每日定额投喂', graph: dailyQuotaSmokeFlow(), minRecords: 6, needsTrigger: true, quota: true },
  ];

  for (const c of cases) {
    const expId = await createExperiment(page, `v113-${c.name}`);
    try {
      const events = await runFlowFromBrowser(page, expId, c.graph);
      const nodeEvents = events
        .filter(e => e.event_type === 'node_executed')
        .map(e => ({ ...e, payload: parsePayload(e.raw_payload) }));
      const recordEvents = nodeEvents.filter(e => e.payload.type === 'record');
      const triggerEvents = events.filter(e => e.event_type === 'node_triggered');
      const snifferEvents = events.filter(e => e.event_type === 'sniffer_captured');

      expect(recordEvents.length, `${c.name} RECORD count`).toBeGreaterThanOrEqual(c.minRecords);
      if (c.needsTrigger) expect(triggerEvents.length, `${c.name} trigger count`).toBeGreaterThanOrEqual(1);
      if (c.needsSniffer) expect(snifferEvents.length, `${c.name} sniffer count`).toBeGreaterThanOrEqual(1);
      if (c.quota) {
        expect(recordEvents.filter(e => e.node_id === 'record_feed').length).toBeGreaterThanOrEqual(3);
        expect(recordEvents.some(e => e.node_id === 'start_cooldown')).toBeTruthy();
      }
    } finally {
      await cleanupExperiment(page, expId);
    }
  }
});
