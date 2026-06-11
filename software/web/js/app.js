const WS_URL = `ws://${location.host}/ws`;
let ws = null;
let currentSessionId = '';
let monitorEventKeys = new Set();

function toast(msg, type = 'info') {
  const container = document.getElementById('toastContainer');
  const el = document.createElement('div');
  el.className = 'toast-item toast-' + type;
  el.textContent = msg;
  container.appendChild(el);
  setTimeout(() => { el.style.opacity = '0'; el.style.transition = 'opacity 0.3s'; setTimeout(() => el.remove(), 300); }, 3000);
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function log(msg, type = 'info') {
  const el = document.getElementById('eventLog');
  if (!el) return;
  const ts = new Date().toLocaleTimeString();
  el.innerHTML += `<span class="${type}">[${ts}] ${msg}</span>\n`;
  el.scrollTop = el.scrollHeight;
}

function parseMonitorPayload(raw) {
  if (!raw) return {};
  if (typeof raw === 'string') {
    try {
      return JSON.parse(raw);
    } catch (e) {
      return {};
    }
  }
  return raw;
}

function monitorSafeText(value, fallback = '') {
  const text = value === undefined || value === null || value === '' ? fallback : String(value);
  return escapeHtml(text);
}

function monitorVariableOpLabel(op) {
  const labels = {
    add: '加',
    subtract: '减',
    set: '设为',
  };
  return labels[op] || op || '更新';
}

function monitorActuatorLabel(actuatorId, explicitLabel = '') {
  if (explicitLabel) return explicitLabel;
  const id = String(actuatorId || '').trim();
  if (!id) return '未指定执行器';

  if (typeof _cachedActuators !== 'undefined' && Array.isArray(_cachedActuators)) {
    const found = _cachedActuators.find((item) => (item.source_id || item.id) === id);
    if (found && (found.display_name || found.label)) return found.display_name || found.label;
  }

  const labels = {
    'actuator:feeder': '给食器（出粮器）',
    feeder: '给食器（出粮器）',
    'actuator:shock': '电击器',
    shock: '电击器',
    'actuator:light': '灯光',
    light: '灯光',
    'actuator:buzzer': '蜂鸣器',
    buzzer: '蜂鸣器',
  };
  return labels[id] || id;
}

function monitorRecordLabel(data, eventName) {
  const recordName = eventName || data.node_label || data.node_id || '未命名事件';
  const safeRecordName = monitorSafeText(recordName);
  const variableName = (data.variable_name || '').trim();
  if (!variableName) return `📝 记录事件: ${safeRecordName}`;

  const opLabel = monitorVariableOpLabel(data.variable_op);
  const value = data.variable_value ?? 0;
  const result = data.variable_result;
  const persistent = data.variable_persistent ? '（持久）' : '';
  const resultText = result === undefined || result === null ? '' : ` → 当前=${monitorSafeText(result)}`;
  return `📝 记录事件: ${safeRecordName}；变量 ${monitorSafeText(variableName)} ${monitorSafeText(opLabel)} ${monitorSafeText(value)}${resultText}${persistent}`;
}

function monitorConditionLabel(data) {
  const opLabels = {
    eq: '等于',
    neq: '不等于',
    gt: '大于',
    lt: '小于',
    gte: '大于等于',
    lte: '小于等于',
  };
  const result = data.result ? '✅ 真' : '❌ 假';
  const subject = data.variable_name ? `变量 ${monitorSafeText(data.variable_name)}` : 'TRIGGER 累计计数';
  if (data.actual_value !== undefined && data.expected_value !== undefined) {
    return `🔀 条件判断: ${subject} ${monitorSafeText(opLabels[data.operator] || data.operator || '')} ${monitorSafeText(data.expected_value)}，当前=${monitorSafeText(data.actual_value)} → ${result}`;
  }
  return `🔀 条件判断: ${result}`;
}

function monitorEventKey(event) {
  const sessionId = event.session_id || currentSessionId || '';
  const eventId = event.event_id || event.id;
  if (eventId !== undefined && eventId !== null && eventId !== '') {
    return `${sessionId}:event:${eventId}`;
  }
  const data = event.data || parseMonitorPayload(event.raw_payload);
  const kind = event.kind || event.event_type || '';
  return [
    sessionId,
    kind,
    event.node_id || data.node_id || '',
    data.type || '',
    data.event_name || data.signal_id || '',
    data.iteration || '',
    event.ts_ms || event.timestamp || ''
  ].join(':');
}

function renderMonitorEventOnce(event) {
  const key = monitorEventKey(event);
  if (monitorEventKeys.has(key)) return false;
  monitorEventKeys.add(key);

  const data = event.data || parseMonitorPayload(event.raw_payload);
  const kind = event.kind || event.event_type || '';
  const nodeType = data.type || kind;
  const eventName = data.event_name || data.signal_id || '';

  if (kind === 'node_executed') {
    markEngineNode(event.node_id || data.node_id);
    let label = '';
    if (nodeType === 'trigger') label = '⚡ 触发节点';
    else if (nodeType === 'record') label = monitorRecordLabel(data, eventName || data.node_id || event.node_id);
    else if (nodeType === 'record_end') label = '⏹ 记录终止: ' + monitorSafeText(eventName || data.node_id || event.node_id);
    else if (nodeType === 'execute') label = '🛠 执行动作: ' + monitorSafeText(monitorActuatorLabel(data.actuator_id, data.actuator_label));
    else if (nodeType === 'delay') label = '⏱ 延时 ' + (data.duration_s || '') + '秒';
    else if (nodeType === 'and') label = '📦 逻辑与输出';
    else if (nodeType === 'not') label = '❌ 逻辑非放行';
    else if (nodeType === 'fork') label = '🔀 逻辑分叉';
    else if (nodeType === 'condition') label = monitorConditionLabel(data);
    else label = '🔹 ' + monitorSafeText(nodeType || kind);
    log(label, 'info');
  } else if (kind === 'node_triggered') {
    markEngineNode(event.node_id || data.node_id);
    log('⚡ 触发: ' + monitorSafeText(eventName || data.node_id || event.node_id), 'success');
  } else if (kind === 'sniffer_captured') {
    log('👁 探针捕获: ' + monitorSafeText(eventName || data.signal_id || ''), 'info');
  } else if (kind === 'loop_iteration') {
    markEngineNode(event.node_id || data.node_id);
    log('🔄 循环 第' + (data.iteration || '?') + '次', 'info');
  } else if (kind === 'manual_trigger') {
    log('手动触发已记录', 'success');
  } else if (kind && kind.startsWith('camera_')) {
    const eventLabel = data.event === 'leave' ? '离开' : (data.event === 'enter' ? '进入' : (data.event || '事件'));
    log('摄像头：' + escapeHtml(data.zone || '区域') + ' ' + escapeHtml(eventLabel), 'success');
  } else if (kind === 'loop_exit') {
    log('🔄 循环退出: ' + monitorSafeText(data.reason || data.iterations + '次迭代' || '达到条件'), 'info');
  } else if (kind === 'loop_timeout') {
    log('⏰ 循环超时 (' + (data.timeout_s || '?') + '秒),强制退出', 'warn');
  }
  return true;
}

function markEngineNode(nodeId) {
  if (nodeId && typeof markRuntimeNode === 'function') {
    markRuntimeNode(nodeId);
  }
}

function setBtnStop(disabled) {
  const btn = document.getElementById('btnStop');
  if (btn) btn.disabled = disabled;
  setManualTriggerButton(disabled);
}

function setManualTriggerButton(disabled) {
  const btn = document.getElementById('btnManualTrigger');
  if (btn) btn.disabled = disabled;
}

function connectWS() {
  ws = new WebSocket(WS_URL);
  ws.onopen = () => log('连接已建立', 'success');
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'mock_complete' || msg.type === 'flow_complete') {
      const recCount = msg.record_count;
      if (recCount !== undefined) {
        log(`实验完成: ${recCount} 条记录事件（共 ${msg.event_count} 条事件）`, 'success');
        toast(`实验完成，${recCount} 条记录事件已保存`, 'success');
      } else {
        log(`实验完成: ${msg.event_count} 条数据已记录`, 'success');
        toast(`实验完成，${msg.event_count} 条数据已记录`, 'success');
      }
      setBtnStop(true);
      renderExperimentList();
    } else if (msg.type === 'manual_trigger') {
      log('手动触发已发送', 'success');
    } else if (msg.type === 'camera_event') {
      if (msg.fed_to_flow) {
        const zone = escapeHtml(msg.zone || '区域');
        const eventLabel = msg.event === 'leave' ? '离开' : (msg.event === 'enter' ? '进入' : escapeHtml(msg.event || '事件'));
        log(`摄像头：${zone} ${eventLabel}`, 'success');
      } else if (window.DEBUG_RAW_SIGNAL_LOG === true) {
        console.debug('camera event ignored by flow', msg);
      }
    } else if (msg.type === 'signal') {
      // 原始信号只保留为调试信息，不进入默认实验人员实时事件日志。
      if (window.DEBUG_RAW_SIGNAL_LOG === true) console.debug('raw signal', msg);
    } else if (msg.type === 'engine_event') {
      // 引擎执行事件（TRIGGER 触发 / RECORD 记录 / DELAY 延时等） → 事件日志
      renderMonitorEventOnce({
        event_id: msg.event_id,
        session_id: msg.session_id,
        event_type: msg.kind,
        kind: msg.kind,
        data: msg.data || {},
        node_id: (msg.data || {}).node_id
      });
    }
  };
  ws.onclose = () => {
    log('连接已断开，5秒后重连', 'warn');
    setTimeout(connectWS, 5000);
  };
  ws.onerror = () => {};
}
connectWS();

document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    // P0-6: 摄像头标签页灰显时拦截点击
    if (tab.dataset.tab === 'camera' && tab.classList.contains('tab-disabled')) {
      toast('请先在实验管理中「编辑」或「启动」一个启用了摄像头的实验', 'warn');
      return;
    }
    // 流程标签页无实验时拦截点击（与摄像头标签页一致）
    if (tab.dataset.tab === 'flow' && tab.classList.contains('tab-disabled')) {
      toast('请先在实验管理中「编辑」一个实验', 'warn');
      return;
    }
    if (tab.dataset.tab !== 'camera' && typeof releaseCamera === 'function') {
      releaseCamera();
    }
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById('tab-' + tab.dataset.tab).classList.add('active');
    if (tab.dataset.tab === 'flow' && typeof clampAllFlowNodes === 'function') {
      requestAnimationFrame(() => {
        if (typeof refreshFlowViewport === 'function') refreshFlowViewport();
        clampAllFlowNodes();
      });
    }
    if (tab.dataset.tab === 'experiment') {
      renderExperimentList();
    }
  });
});

async function api(path, options = {}) {
  const resp = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

// === Modal ===

function showModal(title, bodyHtml) {
  document.getElementById('modalTitle').textContent = title;
  document.getElementById('modalBody').innerHTML = bodyHtml;
  document.getElementById('appModal').style.display = 'flex';
}

function hideModal() {
  document.getElementById('appModal').style.display = 'none';
}

// === Experiment Management ===

function showCreateForm() {
  document.getElementById('createExpCard').style.display = 'block';
}

function hideCreateForm() {
  document.getElementById('createExpCard').style.display = 'none';
}

function onStartModeChangeRadio() {
  const show = document.querySelector('input[name="startModeGroup"]:checked').value === 'timer';
  document.getElementById('timerConfig').style.display = show ? 'block' : 'none';
}

function onTimerTypeChange() {
  const isFixed = document.querySelector('input[name="timerType"]:checked').value === 'fixed';
  document.getElementById('fixedTimeArea').style.display = isFixed ? 'block' : 'none';
  document.getElementById('delayTimeArea').style.display = isFixed ? 'none' : 'block';
}

function onTriggerCameraChange() {
  const checked = document.getElementById('expTriggerCamera').checked;
  if (checked) {
    toast('请创建实验后切换到"摄像头"标签页配置检测区域', 'info');
  }
}

function onTriggerHardwareChange() {
  const checked = document.getElementById('expTriggerHardware').checked;
  document.getElementById('hardwareCountArea').style.display = checked ? 'block' : 'none';
}

async function browseSavePath() {
  const btn = document.querySelector('[onclick="browseSavePath()"]');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ 等待选择...'; }

  try {
    const resp = await api('/api/browse-folder', { method: 'POST' });
    const path = resp.path || '';
    if (path) {
      document.getElementById('expSavePath').value = path;
      toast('已选择: ' + path, 'success');
    }
  } catch (e) {
    toast('打开目录选择器失败: ' + e.message, 'error');
  }
  if (btn) { btn.disabled = false; btn.textContent = '📂 浏览'; }
}

async function createExperiment() {
  const name = document.getElementById('expName').value.trim();
  const subjectId = document.getElementById('expSubjectId').value.trim();
  if (!name) { toast('请输入实验名称', 'warn'); return; }
  if (!subjectId) { toast('请输入动物编号', 'warn'); return; }

  const durationUnlimited = document.getElementById('expDurationUnlimited').checked;
  const triggersUnlimited = document.getElementById('expTriggersUnlimited').checked;
  const maxDuration = durationUnlimited ? 0 : (parseInt(document.getElementById('expDuration').value) || 0);
  const maxTriggers = triggersUnlimited ? 0 : (parseInt(document.getElementById('expMaxTriggers').value) || 0);

  if (maxDuration === 0 && maxTriggers === 0) {
    toast('最长运行时间和最大触发次数不能同时为0或不限（实验永不自动停止）', 'warn');
    return;
  }

  const startMode = document.querySelector('input[name="startModeGroup"]:checked').value;
  let timerConfig = {};
  if (startMode === 'timer') {
    const isFixed = document.querySelector('input[name="timerType"]:checked').value === 'fixed';
    if (isFixed) {
      const fixedDate = document.getElementById('expFixedDate').value;
      const fixedTime = document.getElementById('expFixedTime').value;
      if (!fixedDate || !fixedTime) { toast('请选择启动日期和时间', 'warn'); return; }
      timerConfig = { type: 'fixed', datetime: fixedDate + 'T' + fixedTime };
    } else {
      const delayMin = parseInt(document.getElementById('expDelayMinutes').value) || 30;
      timerConfig = { type: 'delay', minutes: delayMin };
    }
  }

  const hardwareCount = document.getElementById('expTriggerHardware').checked
    ? (parseInt(document.getElementById('expHardwareCount').value) || 0) : 0;

  const savePath = document.getElementById('expSavePath').value.trim();

  const data = {
    name,
    subject_id: subjectId,
    species: document.getElementById('expSpecies').value,
    subject_notes: document.getElementById('expSubjectNotes').value.trim(),
    notes: document.getElementById('expNotes').value.trim(),
    max_duration_min: maxDuration,
    max_trigger_count: maxTriggers,
    trigger_camera: document.getElementById('expTriggerCamera').checked,
    trigger_hardware: hardwareCount > 0,
    hardware_count: hardwareCount,
    start_mode: startMode,
    timer_config: timerConfig,
    save_path: savePath,
  };
  try {
    const result = await api('/api/experiments', { method: 'POST', body: JSON.stringify(data) });
    toast(`实验「${name}」已创建`, 'success');
    hideCreateForm();
    renderExperimentList();
  } catch (e) {
    toast('创建失败: ' + e.message, 'error');
  }
}

async function renderExperimentList() {
  try {
    const data = await api('/api/experiments');
    const filter = (document.getElementById('expFilter').value || '').toLowerCase();

    if (data.experiments.length === 0) {
      document.getElementById('experimentList').innerHTML = '<div class="empty-state"><p>还没有实验记录，点击上方"新建实验"开始</p></div>';
      return;
    }

    let filtered = data.experiments;
    if (filter) {
      filtered = data.experiments.filter(e =>
        (e.subject_id || '').toLowerCase().includes(filter) ||
        (e.name || '').toLowerCase().includes(filter)
      );
    }

    let camStatuses = {};
    try {
      const camResp = await api('/api/experiments/camera-statuses');
      camStatuses = camResp.statuses || {};
    } catch (e) { /* ignore */ }

    const statusMap = {
      idle: '等待启动', created: '等待启动',
      running: '运行中 ●',
      completed: '已完成',
      stopped: '手动停止',
      error: '异常停止',
    };

    let html = `<table>
      <tr>
        <th style="width:32px"><input type="checkbox" id="selectAll" onchange="toggleSelectAll(this.checked)"></th>
        <th>动物编号</th>
        <th>实验名称</th>
        <th>触发源</th>
        <th>摄像头配置</th>
        <th>状态</th>
        <th>已运行</th>
        <th>事件数</th>
        <th>操作</th>
      </tr>`;
    for (const exp of filtered) {
      const sources = [];
      if (exp.trigger_camera) sources.push('摄像头');
      if (exp.trigger_hardware) sources.push('下位机');
      const statusText = statusMap[exp.status] || statusMap.idle;

      let camText = '—';
      const camStatus = camStatuses[exp.id];
      if (exp.trigger_camera) {
        if (camStatus === 'completed') camText = '✅';
        else camText = '⚠️';
      }

      html += `<tr>
        <td style="width:32px"><input type="checkbox" class="exp-checkbox" data-exp-id="${exp.id}" data-exp-name="${escapeHtml(exp.name)}" onchange="updateBatchDeleteBar()"></td>
        <td>${escapeHtml(exp.subject_id) || '—'}</td>
        <td>${escapeHtml(exp.name)}</td>
        <td style="font-size:12px">${sources.join('、') || '手动'}</td>
        <td style="font-size:12px;text-align:center" title="${camStatus === 'completed' ? '摄像头已配置' : camStatus === 'pending' ? '摄像头未配置完成' : ''}">${camText}</td>
        <td>${statusText}</td>
        <td style="font-size:12px">${exp.elapsed_min || '—'}</td>
        <td>${exp.event_count || 0}</td>
        <td style="white-space:nowrap">
          <button class="btn btn-sm" onclick="enterExperiment('${exp.id}')">📝 编辑</button>
          <button class="btn btn-sm btn-primary" onclick="startExpRun('${exp.id}')">▶ 启动</button>
          <button class="btn btn-sm" onclick="viewExperiment('${exp.id}')">📂 详情</button>
          <button class="btn btn-sm btn-success" onclick="exportExperiment('${exp.id}')">📥 导出</button>
          <button class="btn btn-sm btn-danger" onclick="deleteExperiment('${exp.id}')" style="color:#F44336">🗑 删除</button>
        </td>
      </tr>`;
    }
    html += `</table>`;
    document.getElementById('experimentList').innerHTML = html;
    updateBatchDeleteBar();
  } catch (e) {
    document.getElementById('experimentList').innerHTML = '<p style="color:var(--text-secondary)">加载失败，请刷新重试</p>';
  } finally {
    const overlay = document.getElementById('loadingOverlay');
    if (overlay) {
      overlay.style.opacity = '0';
      setTimeout(() => { overlay.style.display = 'none'; }, 500);
    }
  }
}

function toggleSelectAll(checked) {
  document.querySelectorAll('.exp-checkbox').forEach(cb => cb.checked = checked);
  updateBatchDeleteBar();
}

function updateBatchDeleteBar() {
  const checked = document.querySelectorAll('.exp-checkbox:checked');
  const bar = document.getElementById('batchDeleteBar');
  if (!bar) return;
  if (checked.length === 0) {
    bar.style.display = 'none';
    return;
  }
  bar.style.display = 'flex';
  bar.querySelector('.batch-count').textContent = `已选 ${checked.length} 个`;
}

async function batchDeleteExperiments() {
  const checked = document.querySelectorAll('.exp-checkbox:checked');
  if (checked.length === 0) { toast('请先勾选要删除的实验', 'warn'); return; }

  const names = [];
  checked.forEach(cb => {
    const n = cb.dataset.expName;
    if (n) names.push(n);
  });
  let msg = '确定要删除以下实验吗？实验数据（含事件记录和导出文件）将一并删除，不可恢复。\n\n';
  if (names.length <= 10) {
    msg += names.map(n => '  • ' + n).join('\n');
  } else {
    msg += names.slice(0, 10).map(n => '  • ' + n).join('\n');
    msg += `\n  ...等 ${names.length} 个`;
  }

  if (!confirm(msg)) return;

  const ids = [];
  checked.forEach(cb => ids.push(cb.dataset.expId));

  try {
    const result = await api('/api/experiments/batch-delete', {
      method: 'POST',
      body: JSON.stringify({ experiment_ids: ids }),
    });
    toast(`已删除 ${result.deleted} 个实验`, 'warn');
    renderExperimentList();
  } catch (e) {
    toast('批量删除失败: ' + e.message, 'error');
  }
}

async function enterExperiment(expId) {
  try {
    const exp = await api(`/api/experiments/${expId}`);
    toast(`已进入实验: ${exp.name}`, 'info');

    const badge = document.getElementById('currentExpBadge');
    if (badge) {
      badge.textContent = `📋 当前实验：${exp.name}（${exp.subject_id || '—'}）`;
      badge.style.display = 'block';
    }

    // G3-FIN-1: 设置流程编辑器的当前实验 ID
    if (typeof currentExperimentId !== 'undefined') {
      // 在 flow-editor.js 中定义的变量
      currentExperimentId = expId;
      // 更新流程编辑器访问状态
      if (typeof updateFlowEditorAccess === 'function') {
        updateFlowEditorAccess();
      }
      // D-30: 重新加载信号源（带 experiment_id，触发摄像头 zone 注册）
      if (typeof loadSignalSources === 'function') {
        _cachedSources = null;  // 清除缓存，强制重取
        loadSignalSources();
      }
    }

    // G3-FIN-1: 自动加载实验关联的流程
    if (typeof loadFlowFromExperiment === 'function') {
      await loadFlowFromExperiment(expId);
    }

    if (exp.trigger_camera) {
      if (typeof setCameraExperiment === 'function') {
        setCameraExperiment(expId, exp.name, true);
      }
      document.querySelector('[data-tab="camera"]').click();
      toast('已切换到摄像头标签页，请配置检测区域和事件', 'info');
    } else {
      // P0-6: 无摄像头实验仍跟踪上下文，但摄像头标签页灰显
      if (typeof setCameraExperiment === 'function') {
        setCameraExperiment(expId, exp.name, false);
      }
      document.querySelector('[data-tab="flow"]').click();
      toast('该实验未启用摄像头，已切换到流程编辑器', 'info');
    }
    renderExperimentList();
  } catch (e) {
    toast('进入实验失败: ' + e.message, 'error');
  }
}

async function startExpRun(expId) {
  const exp = await api(`/api/experiments/${expId}`);
  toast(`正在启动实验: ${exp.name}`, 'info');
  log(`启动实验: ${exp.name} (${exp.subject_id})`, 'info');
  setBtnStop(false);
  const count = exp.max_trigger_count || 0;

  const badge = document.getElementById('currentExpBadge');
  if (badge) {
    badge.textContent = `📋 当前实验：${exp.name}（${exp.subject_id || '—'}）`;
    badge.style.display = 'block';
  }

  if (exp.trigger_camera) {
    if (typeof setCameraExperiment === 'function') {
      setCameraExperiment(expId, exp.name, true);
    }
    toast('实验已启动，如需摄像头检测请切换到摄像头标签页手动开始', 'info');
  } else {
    if (typeof setCameraExperiment === 'function') {
      setCameraExperiment(expId, exp.name, false);
    }
  }

  try {
    const result = await api(`/api/experiment/start-mock?count=${count}&subject_id=${encodeURIComponent(exp.subject_id)}&exp_name=${encodeURIComponent(exp.name)}&notes=${encodeURIComponent(exp.notes || '')}&max_duration_min=${exp.max_duration_min || 0}&experiment_id=${encodeURIComponent(expId)}`, { method: 'POST' });
    toast(`实验已启动`, 'success');
    log(`实验已启动`, 'success');
    startMonitorPoll(result.session_id);
  } catch (e) {
    toast('启动失败: ' + e.message, 'error');
    setBtnStop(true);
  }
}

async function viewExperiment(expId) {
  try {
    const [exp, sessionsData] = await Promise.all([
      api(`/api/experiments/${expId}`),
      api(`/api/experiments/${expId}/sessions`),
    ]);
    const folderPath = exp.folder_path || '';
    const sessions = sessionsData.sessions || [];
    let html = '<table style="width:100%">';
    const rows = [
      ['实验名称', escapeHtml(exp.name)],
      ['动物编号', escapeHtml(exp.subject_id)],
      ['物种/品系', escapeHtml(exp.species) || '—'],
      ['最长运行', exp.max_duration_min ? `${exp.max_duration_min} 分钟` : '不限'],
      ['最大触发次数', exp.max_trigger_count ? `${exp.max_trigger_count} 次` : '不设上限'],
      ['启动方式', exp.start_mode === 'manual' ? '手动' : '定时'],
      ['动物备注', escapeHtml(exp.subject_notes) || '—'],
      ['实验备注', escapeHtml(exp.notes) || '—'],
      ['创建时间', new Date(exp.created_at).toLocaleString()],
    ];
    rows.forEach(([k, v]) => { html += `<tr><td style="font-weight:600;width:120px;padding:4px 8px">${k}</td><td style="padding:4px 8px">${v}</td></tr>`; });
    if (folderPath) {
      html += `<tr><td style="font-weight:600;padding:4px 8px">保存位置</td><td style="padding:4px 8px">${folderPath}<br><span style="font-size:11px">数据导出目录：${folderPath}/exports/</span></td></tr>`;
    }
    if (sessions.length > 0) {
      html += `<tr><td style="font-weight:600;padding:4px 8px">运行记录</td><td style="padding:4px 8px;font-size:12px">`;
      sessions.forEach(s => {
        html += `<div>[${s.state}] ${s.name || s.id.slice(0,12)} — ${new Date(s.created_at * 1000).toLocaleString()}</div>`;
      });
      html += `</td></tr>`;
    }
    html += '</table>';
    if (folderPath) {
      html += `<div style="margin-top:12px;text-align:center"><button class="btn btn-sm" onclick="openFolder('${expId}')">📂 打开文件夹</button></div>`;
    }
    showModal('实验详情', html);
  } catch (e) {
    toast('加载失败: ' + e.message, 'error');
  }
}

function openFolder(expId) {
  fetch('/api/experiments/' + expId + '/open-folder', { method: 'POST' }).catch(() => {});
}

async function exportExperiment(expId) {
  try {
    const sessionsData = await api(`/api/experiments/${expId}/sessions`);
    const sessions = sessionsData.sessions || [];
    if (sessions.length === 0) {
      toast('没有运行数据可导出，请先启动实验', 'warn');
      return;
    }
    const latest = sessions[0];
    const exportData = await api(`/api/sessions/${latest.id}/export`);
    toast(`数据已导出至 ${exportData.csv_path}`, 'success');
    log(`CSV 导出完成: ${exportData.csv_path}`, 'success');
  } catch (e) {
    toast('导出失败: ' + e.message, 'error');
  }
}

async function deleteExperiment(expId) {
  let name = '此实验';
  try {
    const exp = await api(`/api/experiments/${expId}`);
    name = exp.name;
  } catch (e) { /* ignore */ }
  if (!confirm(`确定要删除实验"${name}"吗？实验数据（含事件记录和导出文件）将一并删除，不可恢复。`)) return;
  try {
    await api(`/api/experiments/${expId}`, { method: 'DELETE' });
    toast('实验已删除', 'warn');
    renderExperimentList();
  } catch (e) {
    toast('删除失败: ' + e.message, 'error');
  }
}

// === Stop ===

async function stopExperiment() {
  toast('正在停止实验...', 'warn');
  log('正在停止实验...', 'warn');
  if (typeof stopCameraDetection === 'function') {
    stopCameraDetection();
  }
  if (typeof stopMonitorCameraPreview === 'function') {
    stopMonitorCameraPreview();
  }
  try {
    await api('/api/experiment/stop', { method: 'POST' });
    toast('实验已停止', 'warn');
    log('实验已停止', 'warn');
  } catch (e) {
    toast('停止失败: ' + e.message, 'error');
  }
  setBtnStop(true);
}

async function manualTrigger() {
  const btn = document.getElementById('btnManualTrigger');
  if (btn) btn.disabled = true;
  try {
    await api('/api/experiment/manual-trigger', {
      method: 'POST',
      body: JSON.stringify({ experiment_id: currentExperimentId, session_id: currentSessionId }),
    });
    toast('手动触发已发送', 'success');
  } catch (e) {
    toast('手动触发失败: ' + e.message, 'error');
    log('手动触发失败: ' + e.message, 'error');
  } finally {
    try {
      const state = await api('/api/experiment/state');
      setManualTriggerButton(state.engine !== 'running');
    } catch (e) {
      setManualTriggerButton(true);
    }
  }
}

let monitorInterval = null;

function startMonitorPoll(sessionId) {
  const keepPrefix = `${sessionId}:`;
  monitorEventKeys = new Set([...monitorEventKeys].filter(key => key.startsWith(keepPrefix)));
  currentSessionId = sessionId;
  if (monitorInterval) clearInterval(monitorInterval);
  const start = Date.now();
  let lastEventCount = 0;
  monitorInterval = setInterval(async () => {
    try {
      const state = await api('/api/experiment/state');
      document.getElementById('monStatus').textContent = state.engine === 'running' ? '运行中 ●' : (state.session === 'completed' ? '已完成' : '等待启动');
      if (state.session === 'completed' || state.session === 'none' || state.engine !== 'running') {
        clearInterval(monitorInterval);
        monitorInterval = null;
        setBtnStop(true);
        if (typeof stopMonitorCameraPreview === 'function') stopMonitorCameraPreview();
      } else {
        setManualTriggerButton(false);
      }
    } catch (e) { /* ignore */ }
    const elapsed = Math.floor((Date.now() - start) / 1000);
    document.getElementById('monDuration').textContent = elapsed + 's';
    if (sessionId) {
      try {
        const ev = await api(`/api/sessions/${sessionId}/events`);
        document.getElementById('monEvents').textContent = ev.events.length;
        // 将新增的引擎事件渲染到实时日志（轮询补充 WebSocket 可能遗漏的事件）
        if (ev.events.length > lastEventCount) {
          for (let i = lastEventCount; i < ev.events.length; i++) {
            const e2 = ev.events[i];
            renderMonitorEventOnce(e2);
          }
          lastEventCount = ev.events.length;
        }
      } catch (e) { /* ignore */ }
    }
  }, 1000);
}

function loadFlowFile(filename) {
  fetch(`/api/flows/${filename}`)
    .then(r => r.json())
    .then(data => {
      loadFlowData(data);
      document.querySelector('[data-tab="flow"]').click();
      toast('流程已加载', 'success');
    })
    .catch(e => toast('加载失败: ' + e.message, 'error'));
}

async function runFlow() {
  const btn = document.getElementById('btnRunFlow');
  const origText = btn ? btn.textContent : '▶ 运行流程';

  const data = getFlowData();
  if (!data || !data.nodes || Object.keys(data.nodes).length === 0) {
    toast('请先在画布上添加节点', 'warn');
    return;
  }
  if (!currentExperimentId) {
    toast('请先在实验列表中选择一个实验（点击"📝 编辑"）', 'warn');
    return;
  }

  // Disable button during operation
  if (btn) { btn.disabled = true; btn.textContent = '启动中...'; }
  log('正在保存并启动流程...', 'info');

  try {
    // Step 1: Save flow first
    await api(`/api/experiments/${currentExperimentId}/flow/save`, {
      method: 'POST',
      body: JSON.stringify({ flow: data }),
    });
    toast('✅ 流程已保存，正在启动实验...', 'success');

    const expInfo = await api(`/api/experiments/${currentExperimentId}`);
    const duration = Math.max(1, Math.min(86400, (parseInt(expInfo.max_duration_min || 0) || 1) * 60));

    // Step 2: Start the experiment
    const runResult = await api('/api/experiment/run-flow', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ experiment_id: currentExperimentId, duration }),
    });

    setBtnStop(false);
    toast('✅ 实验已启动，已切换到监控面板', 'success');
    log('实验已启动', 'info');
    startMonitorPoll(runResult.session_id);
    document.querySelector('[data-tab="monitor"]').click();
    // 运行监控只读摄像头预览（仅启用摄像头且已配区域的实验）
    if (typeof startMonitorCameraPreview === 'function') {
      try {
        const exp = await api(`/api/experiments/${currentExperimentId}`);
        startMonitorCameraPreview(currentExperimentId, !!exp.trigger_camera);
      } catch (e) { /* 预览失败不影响实验 */ }
    }
  } catch (e) {
    toast('❌ 运行失败：' + e.message, 'error');
    log('运行失败: ' + e.message, 'error');
    setBtnStop(true);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = origText; }
  }
}

// === Device ===
async function connectDevice() {
  const host = document.getElementById('deviceHost').value;
  const port = parseInt(document.getElementById('devicePort').value) || 8080;
  toast(`正在连接控制盒 ${host}:${port}...`, 'info');
  document.getElementById('btnDeviceConnect').disabled = true;
  try {
    const data = await api('/api/device/connect', { method: 'POST', body: JSON.stringify({ host, port }) });
    if (data.ok) {
      toast('控制盒已连接', 'success');
      document.getElementById('deviceStatus').textContent = `✅ 已连接: ${data.device_id || host}`;
      document.getElementById('deviceStatus').style.color = '#4CAF50';
      document.getElementById('btnDeviceConnect').disabled = true;
      document.getElementById('btnDeviceDisconnect').disabled = false;
    } else {
      toast('连接失败（硬件未就绪是正常的）', 'warn');
      document.getElementById('deviceStatus').textContent = '❌ 连接失败';
      document.getElementById('deviceStatus').style.color = '#F44336';
      document.getElementById('btnDeviceConnect').disabled = false;
    }
  } catch (e) {
    toast('连接失败：' + e.message, 'warn');
    document.getElementById('deviceStatus').textContent = '❌ 连接失败';
    document.getElementById('btnDeviceConnect').disabled = false;
  }
}

async function disconnectDevice() {
  try {
    await api('/api/device/disconnect', { method: 'POST' });
    toast('控制盒已断开', 'warn');
    document.getElementById('deviceStatus').textContent = '控制盒未连接';
    document.getElementById('deviceStatus').style.color = 'var(--text-secondary)';
    document.getElementById('btnDeviceConnect').disabled = false;
    document.getElementById('btnDeviceDisconnect').disabled = true;
  } catch (e) {
    toast('断开失败: ' + e.message, 'error');
  }
}

// Init
renderExperimentList();

// Bug #10: 页面加载时检查是否有运行中的实验，恢复监控轮询
(async function restoreMonitorOnLoad() {
  try {
    const state = await api('/api/experiment/state');
    if (state.engine === 'running' && state.session_id) {
      currentSessionId = state.session_id;
      startMonitorPoll(state.session_id);
      setBtnStop(false);
      // Switch to monitor tab
      const monitorTab = document.querySelector('[data-tab="monitor"]');
      if (monitorTab) monitorTab.click();
      // 恢复运行监控只读摄像头预览
      if (state.experiment_id && typeof startMonitorCameraPreview === 'function') {
        try {
          const exp = await api(`/api/experiments/${state.experiment_id}`);
          startMonitorCameraPreview(state.experiment_id, !!exp.trigger_camera);
        } catch (e) { /* ignore */ }
      }
    }
  } catch (e) {
    // 服务不可用时静默失败
  }
})();
