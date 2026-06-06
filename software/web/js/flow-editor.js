/**
 * Flow Editor — Interaction layer for the flow editor.
 *
 * Contains: palette click, connection mousedown, validateFlow, saveFlow,
 * loadFlow, loadFlowFromExperiment, showConfigPanel, validateNodeParams,
 * loadSignalSources, and initialization.
 * Depends on: flow-model.js, flow-canvas.js
 */

// ============================================================================
// Node selection & config panel
// ============================================================================

function selectNode(id) {
  selectedNodeId = id;
  Object.values(flowNodes).forEach(n => n.el.style.borderColor = 'transparent');
  if (id && flowNodes[id]) {
    flowNodes[id].el.style.borderColor = '#1976D2';
    showConfigPanel(id);
  } else {
    document.getElementById('flowConfigPanel').style.display = 'none';
  }
}

function showConfigPanel(id) {
  const n = flowNodes[id];
  if (!n) return;
  const schema = NODE_SCHEMAS[n.type];

  if (n.fixed) {
    document.getElementById('flowConfigPanel').style.display = 'none';
    return;
  }

  if (!schema || schema.fields.length === 0) {
    document.getElementById('flowConfigPanel').style.display = 'none';
    return;
  }

  document.getElementById('flowConfigPanel').style.display = 'block';
  document.getElementById('cfgLabel').value = n.label || schema.label;

  let extra = '';
  const params = n.params || {};

  for (const field of schema.fields) {
    if (field.condition && !field.condition(params)) continue;

    if (field.type === 'select' && field.options === 'dynamic') {
      const options = buildDynamicSelectOptions(field.key, params[field.key]);
      extra += `<label>${field.label}</label><select id="cfg_${field.key}" onchange="updateParam('${id}','${field.key}',this.value)">${options}</select>`;
    } else if (field.type === 'select') {
      const opts = field.options.map(opt => {
        const val = typeof opt === 'object' ? opt.value : opt;
        const lbl = typeof opt === 'object' ? opt.label : opt;
        const sel = params[field.key] === val ? 'selected' : '';
        return `<option value="${val}" ${sel}>${lbl}</option>`;
      }).join('');
      extra += `<label>${field.label}</label><select id="cfg_${field.key}" onchange="updateParam('${id}','${field.key}',this.value)">${opts}</select>`;
    } else if (field.type === 'number') {
      const val = params[field.key] ?? field.default ?? '';
      const step = field.step || 1;
      const unit = field.unit || '';
      const onChangeHandler = `updateParam('${id}','${field.key}',parseFloat(this.value))`;
      extra += `<label>${field.label}${unit ? ' (' + unit + ')' : ''}</label><input type="number" id="cfg_${field.key}" value="${val}" step="${step}" onchange="${onChangeHandler}" oninput="updateParam('${id}','${field.key}',parseFloat(this.value))">`;
    } else if (field.type === 'text') {
      const val = escapeHtml(params[field.key] ?? '');
      extra += `<label>${field.label}</label><input type="text" id="cfg_${field.key}" value="${val}" onchange="updateParam('${id}','${field.key}',this.value)">`;
    }
  }

  if (schema.help) {
    extra += `<p style="color:var(--text-secondary);font-size:11px;margin-top:8px;padding-top:8px;border-top:1px solid var(--border);">💡 ${schema.help}</p>`;
  }

  document.getElementById('cfgExtra').innerHTML = extra;
}

function buildDynamicSelectOptions(fieldKey, selected) {
  // D-30: switch cache based on field key
  if (fieldKey === 'actuator_id') {
    if (_cachedActuators) {
      return _cachedActuators.map(s => {
        const sel = s.id === selected ? 'selected' : '';
        return `<option value="${s.id}" ${sel}>${escapeHtml(s.display_name)}</option>`;
      }).join('');
    }
    return `<option value="actuator:feeder" ${selected === 'actuator:feeder' ? 'selected' : ''}>给食器（出粮器）</option>
      <option value="actuator:shock" ${selected === 'actuator:shock' ? 'selected' : ''}>电击器</option>
      <option value="actuator:light" ${selected === 'actuator:light' ? 'selected' : ''}>灯光</option>
      <option value="actuator:buzzer" ${selected === 'actuator:buzzer' ? 'selected' : ''}>蜂鸣器</option>`;
  }
  if (_cachedSources) {
    return _cachedSources.map(s => {
      const sel = s.id === selected ? 'selected' : '';
      return `<option value="${s.id}" ${sel}>${s.label}</option>`;
    }).join('');
  }
  return `<option value="mock:trigger" ${selected === 'mock:trigger' ? 'selected' : ''}>模拟信号（测试用）</option>
    <option value="camera:区域A:enter" ${selected === 'camera:区域A:enter' ? 'selected' : ''}>摄像头 - 区域 A - 进入</option>
    <option value="camera:区域A:leave" ${selected === 'camera:区域A:leave' ? 'selected' : ''}>摄像头 - 区域 A - 离开</option>`;
}

// ============================================================================
// Parameter update
// ============================================================================

function updateParam(id, key, value) {
  if (flowNodes[id]) {
    if (!flowNodes[id].params) flowNodes[id].params = {};
    flowNodes[id].params[key] = value;
  }

  const n = flowNodes[id];
  if (!n) return;
  const schema = NODE_SCHEMAS[n.type];
  if (!schema) return;

  const affectedFields = [];
  for (const field of schema.fields) {
    if (field.condition && field.key !== key) {
      const condStr = field.condition.toString();
      if (condStr.includes(key)) affectedFields.push(field.key);
    }
  }

  if (affectedFields.length > 0) {
    const focusedEl = document.activeElement;
    const focusedId = focusedEl ? focusedEl.id : null;
    showConfigPanel(id);
    if (focusedId) {
      const restoredEl = document.getElementById(focusedId);
      if (restoredEl && restoredEl !== focusedEl) restoredEl.focus();
    }
  }
}

function updateNodeConfig() {
  const id = selectedNodeId;
  const label = document.getElementById('cfgLabel').value;
  if (id && flowNodes[id] && !flowNodes[id].fixed) {
    flowNodes[id].label = label;
    const hdr = flowNodes[id].el.querySelector('.node-header');
    if (hdr) {
      const span = hdr.querySelector('span');
      const bgColor = hdr.style.background || NODE_SCHEMAS[flowNodes[id].type]?.color || '';
      if (span) hdr.innerHTML = span.outerHTML + ' ' + escapeHtml(label);
      else hdr.textContent = label;
      if (bgColor) hdr.style.background = bgColor;
    }
  }
}

// ============================================================================
// Parameter validation — Schema-driven
// ============================================================================

function validateNodeParams(id) {
  const n = flowNodes[id];
  if (!n) return true;
  const schema = NODE_SCHEMAS[n.type];
  if (!schema) return true;

  const params = n.params || {};
  const errors = [];

  for (const field of schema.fields) {
    if (field.condition && !field.condition(params)) continue;

    if (field.required) {
      if (field.type === 'number') {
        if (params[field.key] === undefined || params[field.key] === null || params[field.key] === '' || isNaN(params[field.key])) {
          errors.push(`${field.label} 不能为空`);
          continue;
        }
      } else if (field.type === 'text' || field.type === 'select') {
        if (!params[field.key] || params[field.key] === '') {
          errors.push(`${field.label} 不能为空`);
          continue;
        }
      }
    }

    if (field.type === 'number' && params[field.key] !== undefined && params[field.key] !== '' && !isNaN(params[field.key])) {
      const val = params[field.key];
      if (field.min !== undefined && val < field.min) {
        const unit = field.unit ? ` ${field.unit}` : '';
        errors.push(`${field.label} 不能小于 ${field.min}${unit}`);
      }
      if (field.max !== undefined && val > field.max) {
        const unit = field.unit ? ` ${field.unit}` : '';
        errors.push(`${field.label} 不能超过 ${field.max}${unit}`);
      }
    }

    if (field.type === 'text' && field.maxLength && params[field.key]) {
      if (params[field.key].length > field.maxLength) {
        errors.push(`${field.label} 不能超过${field.maxLength}个字符`);
      }
    }
  }

  if (errors.length > 0) {
    toast('参数校验失败：' + errors.join('；'), 'error');
    return false;
  }
  return true;
}

// ============================================================================
// Event: Drag move (canvas-level)
// ============================================================================

document.addEventListener('mousemove', (e) => {
  if (dragState) {
    const canvas = document.getElementById('flowCanvas');
    const rect = canvas.getBoundingClientRect();
    const x = Math.max(0, Math.min(rect.width - 140, e.clientX - rect.left - dragState.offsetX));
    const y = Math.max(0, Math.min(rect.height - 60, e.clientY - rect.top - dragState.offsetY));
    dragState.el.style.left = x + 'px';
    dragState.el.style.top = y + 'px';
    updateSvg();
  }
  if (connectingFrom) {
    connectingMousePos = { x: e.clientX, y: e.clientY };
    const canvas = document.getElementById('flowCanvas');
    const rect = canvas.getBoundingClientRect();
    updateConnectingLine(rect);
  }
});

// ============================================================================
// Event: Mouse up — finish drag or connection
// ============================================================================

document.addEventListener('mouseup', (e) => {
  if (dragState) {
    dragState.el.style.zIndex = '10';
    dragState.el.style.boxShadow = '0 2px 8px rgba(0,0,0,0.12)';
    dragState = null;
  }

  if (connectingFrom) {
    const port = e.target.closest('.node-port-in, .node-port-out');
    if (port && port.classList.contains('node-port-in')) {
      const nodeEl = port.closest('.flow-node');
      const toId = getNodeId(nodeEl);
      if (toId && toId !== connectingFrom) {
        const toNode = flowNodes[toId];
        const fromNode = flowNodes[connectingFrom];

        if (toNode && toNode.type === 'start') {
          toast('开始节点没有输入端口，不能连线到它', 'warn');
          connectingFrom = null;
          connectingFromPort = 'out';
          connectingMousePos = null;
          document.getElementById('connectingLine')?.remove();
          return;
        }
        if (fromNode && fromNode.type === 'end') {
          toast('结束节点没有输出端口，不能从它连线', 'warn');
          connectingFrom = null;
          connectingFromPort = 'out';
          connectingMousePos = null;
          document.getElementById('connectingLine')?.remove();
          return;
        }

        const exists = flowEdges.some(ed =>
          ed.source === connectingFrom &&
          ed.sourcePort === connectingFromPort &&
          ed.target === toId
        );
        if (exists) {
          toast('该连线已存在', 'warn');
          connectingFrom = null;
          connectingFromPort = 'out';
          connectingMousePos = null;
          document.getElementById('connectingLine')?.remove();
          return;
        }

        const edgeId = 'edge_' + Math.random().toString(36).slice(2, 8);
        flowEdges.push({ id: edgeId, source: connectingFrom, sourcePort: connectingFromPort, target: toId });
      }
    }
    connectingFrom = null;
    connectingFromPort = 'out';
    connectingMousePos = null;
    document.getElementById('connectingLine')?.remove();
    saveHistory();
    updateSvg();
  }
});

// ============================================================================
// Event: Start connection from output port
// ============================================================================

document.addEventListener('mousedown', (e) => {
  // Check for port-row clicks (Blockly-style dual-output nodes)
  const portRow = e.target.closest('.node-port-row');
  if (portRow) {
    e.stopPropagation();
    const nodeEl = portRow.closest('.flow-node');
    const id = getNodeId(nodeEl);
    if (id) {
      connectingFrom = id;
      connectingFromPort = portRow.dataset.port || 'out';
      connectingMousePos = { x: e.clientX, y: e.clientY };
    }
    return;
  }
  // Legacy single-port clicks
  const port = e.target.closest('.node-port-out');
  if (!port) return;
  e.stopPropagation();
  const nodeEl = port.closest('.flow-node');
  const id = getNodeId(nodeEl);
  if (id) {
    connectingFrom = id;
    connectingFromPort = port.dataset.port || 'out';
    connectingMousePos = { x: e.clientX, y: e.clientY };
  }
});

// ============================================================================
// Palette — click to add new nodes
// ============================================================================

document.getElementById('nodePalette').addEventListener('mousedown', (e) => {
  const item = e.target.closest('.palette-item');
  if (!item) return;
  e.preventDefault();
  const type = item.dataset.type;
  const schema = NODE_SCHEMAS[type];
  if (!schema) return;

  nodeIdCounter++;
  const id = type + '_' + nodeIdCounter;
  const label = item.textContent.trim();

  const defaults = {};
  for (const field of schema.fields) {
    if (field.default !== undefined) defaults[field.key] = field.default;
  }
  // TRIGGER: auto-select first available signal source
  if (type === 'trigger' && _cachedSources && _cachedSources.length > 0 && !defaults.signal_id) {
    defaults.signal_id = _cachedSources[0].id;
  }
  // D-30: EXECUTE: auto-select first available actuator
  if (type === 'execute' && _cachedActuators && _cachedActuators.length > 0 && !defaults.actuator_id) {
    defaults.actuator_id = _cachedActuators[0].source_id;
  }

  const el = createNodeEl(type, label, defaults);
  el.id = 'node_' + id;
  const offsetX = (nodeCreationOffset % 5) * 20;
  const offsetY = Math.floor(nodeCreationOffset / 5) * 20;
  nodeCreationOffset++;
  el.style.left = (200 + offsetX) + 'px';
  el.style.top = (100 + offsetY) + 'px';
  document.getElementById('flowNodes').appendChild(el);
  flowNodes[id] = { el, type, label, params: defaults, fixed: false };
  makeDraggable(el, id);
  selectNode(id);
  saveHistory();
  updateSvg();
});

// ============================================================================
// Delete node (right-click)
// ============================================================================

document.addEventListener('contextmenu', (e) => {
  // Check for edge path first
  const edgePath = e.target.closest('path[data-edge-id]');
  if (edgePath) {
    e.preventDefault();
    const edgeId = edgePath.getAttribute('data-edge-id');
    flowEdges = flowEdges.filter(ed => ed.id !== edgeId);
    if (selectedEdgeId === edgeId) selectedEdgeId = null;
    saveHistory();
    updateSvg();
    return;
  }
  // Check for node
  const nodeEl = e.target.closest('.flow-node');
  if (nodeEl) {
    e.preventDefault();
    const id = getNodeId(nodeEl);
    if (!id) return;
    if (flowNodes[id] && flowNodes[id].fixed) {
      toast('开始和结束节点不可删除', 'warn');
      return;
    }
    flowEdges = flowEdges.filter(ed => ed.source !== id && ed.target !== id);
    delete flowNodes[id];
    nodeEl.remove();
    saveHistory();
    updateSvg();
    if (selectedNodeId === id) { selectedNodeId = null; document.getElementById('flowConfigPanel').style.display = 'none'; }
    return;
  }
});

// ============================================================================
// Edge selection & deletion
// ============================================================================

document.addEventListener('click', (e) => {
  const edgePath = e.target.closest('path[data-edge-id]');
  if (edgePath) {
    const edgeId = edgePath.getAttribute('data-edge-id');
    if (selectedEdgeId === edgeId) {
      selectedEdgeId = null;
    } else {
      selectedEdgeId = edgeId;
    }
    updateSvg();
    e.stopPropagation();
    return;
  }
  if (e.target.id === 'flowCanvas' || e.target.id === 'flowSvg') {
    selectedEdgeId = null;
    updateSvg();
  }
});

document.addEventListener('keydown', (e) => {
  if ((e.key === 'Delete' || e.key === 'Backspace') && selectedEdgeId) {
    const activeEl = document.activeElement;
    if (activeEl && (activeEl.tagName === 'INPUT' || activeEl.tagName === 'TEXTAREA' || activeEl.isContentEditable)) {
      return;
    }
    e.preventDefault();
    const edgeIndex = flowEdges.findIndex(ed => ed.id === selectedEdgeId);
    if (edgeIndex >= 0) {
      flowEdges.splice(edgeIndex, 1);
      selectedEdgeId = null;
      saveHistory();
      updateSvg();
    }
  }
});

// ============================================================================
// Save / Load / Validate
// ============================================================================

function updateFlowEditorAccess() {
  const hasExp = !!currentExperimentId;
  const badge = document.getElementById('flowExpBadge');

  if (badge) {
    if (!hasExp) {
      badge.textContent = '📋 请先在实验管理中「编辑」一个实验';
      badge.style.display = 'block';
      badge.style.background = '#FFF3CD';
      badge.style.color = '#856404';
    } else {
      badge.textContent = '';
      badge.style.display = 'none';
    }
  }

  const flowTab = document.querySelector('[data-tab="flow"]');
  if (flowTab) {
    if (!hasExp) {
      flowTab.classList.add('tab-disabled');
      flowTab.style.opacity = '0.5';
      flowTab.style.pointerEvents = 'none';
      flowTab.title = '请先进入一个实验';
    } else {
      flowTab.classList.remove('tab-disabled');
      flowTab.style.opacity = '';
      flowTab.style.pointerEvents = '';
      flowTab.title = '';
    }
  }

  document.querySelectorAll('#tab-flow .btn').forEach(btn => {
    const text = btn.textContent.trim();
    if (text.includes('撤销') || text.includes('重做')) return;
    btn.disabled = !hasExp;
    btn.style.opacity = hasExp ? '1' : '0.4';
    btn.style.cursor = hasExp ? 'pointer' : 'not-allowed';
    btn.title = hasExp ? '' : '请先进入一个实验';
  });

  const canvas = document.getElementById('flowCanvas');
  if (canvas) canvas.style.pointerEvents = hasExp ? 'auto' : 'none';
  const palette = document.getElementById('nodePalette');
  if (palette) {
    palette.style.pointerEvents = hasExp ? 'auto' : 'none';
    palette.style.opacity = hasExp ? '1' : '0.4';
  }
  const configPanel = document.getElementById('flowConfigPanel');
  if (configPanel) {
    configPanel.style.pointerEvents = hasExp ? 'auto' : 'none';
    configPanel.style.opacity = hasExp ? '1' : '0.4';
  }
}

async function saveFlow() {
  const saveBtn = document.getElementById('btnSaveFlow');
  if (saveBtn) {
    saveBtn.disabled = true;
    saveBtn.textContent = '保存中...';
  }

  try {
    if (!currentExperimentId) {
      toast('请先在实验列表中选择一个实验（点击"📝 编辑"）', 'warn');
      return;
    }

    for (const [id, n] of Object.entries(flowNodes)) {
      if (n.fixed) continue;
      const schema = NODE_SCHEMAS[n.type];
      if (schema && schema.fields.length > 0) {
        if (!validateNodeParams(id)) return;
      }
    }

    const data = getFlowData();
    if (!data.nodes || Object.keys(data.nodes).length === 0) {
      toast('请先从左侧面板拖拽节点到画布', 'warn');
      return;
    }
    try {
      const result = await api(`/api/experiments/${currentExperimentId}/flow/save`, {
        method: 'POST',
        body: JSON.stringify({ flow: data }),
      });
      const expInfo = await api(`/api/experiments/${currentExperimentId}`);
      toast(`流程已保存到实验 [${expInfo.name}]`, 'success');
    } catch (e) {
      toast('保存失败: ' + e.message, 'error');
    }
  } finally {
    if (saveBtn) {
      saveBtn.disabled = false;
      saveBtn.textContent = '保存流程';
    }
  }
}

async function loadFlowFromExperiment(expId) {
  if (!expId) return;
  // Force clear canvas before loading
  flowNodes = {};
  flowEdges = [];
  document.getElementById('flowNodes').innerHTML = '';
  document.getElementById('flowSvg')?.querySelectorAll('path:not(#connectingLine)').forEach(p => p.remove());
  nodeIdCounter = 0;
  try {
    const data = await api(`/api/experiments/${expId}/flow/load`);
    if (data && data.nodes && Object.keys(data.nodes).length > 0) {
      loadFlowData(data);
    } else {
      // No flow data — just show START/END
      initFixedNodes();
      saveHistory();
      updateSvg();
    }
  } catch (e) {
    // Silent fail, show START/END
    initFixedNodes();
    saveHistory();
    updateSvg();
  }
}

async function loadFlow() {
  if (!currentExperimentId) {
    toast('请先在实验列表中选择一个实验（点击"📝 编辑"）', 'warn');
    return;
  }
  try {
    const data = await api(`/api/experiments/${currentExperimentId}/flow/load`);
    if (data && data.nodes && Object.keys(data.nodes).length > 0) {
      loadFlowData(data);
      toast('流程已从当前实验加载', 'success');
    } else {
      toast('当前实验暂无已保存的流程数据', 'info');
    }
  } catch (e) {
    toast('加载失败: ' + e.message, 'error');
  }
}

async function validateFlow() {
  const data = getFlowData();
  try {
    const result = await api('/api/flows/validate', {
      method: 'POST', body: JSON.stringify(data),
    });
    if (result.valid) {
      toast('✅ 流程校验通过', 'success');
    } else {
      toast('❌ ' + result.errors.join('; '), 'error');
    }
  } catch (e) {
    toast('校验出错: ' + e.message, 'error');
  }
}

// ============================================================================
// Signal source loading
// ============================================================================

async function loadSignalSources() {
  if (_sourcesLoading) return;
  _sourcesLoading = true;
  try {
    const resp = await fetch('/api/sources');
    const data = await resp.json();
    _cachedSources = data.sources || [];
  } catch (e) {
    _cachedSources = null;
  }
  _sourcesLoading = false;
  if (selectedNodeId && flowNodes[selectedNodeId]) {
    const t = flowNodes[selectedNodeId].type;
    if (t === 'trigger' || t === 'not') showConfigPanel(selectedNodeId);
  }
}

// D-30: 加载执行器列表（供 EXECUTE 节点 actuator_id 下拉）
async function loadActuatorSources() {
  if (typeof _actuatorsLoading !== 'undefined' && _actuatorsLoading) return;
  _actuatorsLoading = true;
  try {
    const resp = await fetch('/api/registry/actuators');
    const data = await resp.json();
    _cachedActuators = data.entries || [];
  } catch (e) {
    _cachedActuators = null;
  }
  _actuatorsLoading = false;
  if (selectedNodeId && flowNodes[selectedNodeId] && flowNodes[selectedNodeId].type === 'execute') {
    showConfigPanel(selectedNodeId);
  }
}

// ============================================================================
// Palette item tooltips
// ============================================================================

function initPaletteTooltips() {
  const tooltipMap = {
    trigger: '⚡ 触发信号 — 点击放置，选择信号源事件',
    delay: '⏱ 延时等待 — 点击放置，设置等待时长',
    condition: '🔀 条件判断 — 点击放置，设置判断条件',
    execute: '🛠 执行动作 — 点击放置，配置执行器',
    loop: '🔄 循环 — 点击放置，设置循环参数',
    and: '📦 逻辑与 — 点击放置，所有输入到齐才输出',
    not: '❌ 逻辑非 — 点击放置，信号反转',
    fork: '🔀 逻辑分叉 — 点击放置，1入2出无条件复制信号',
    record: '📝 记录事件 — 点击放置，记录实验数据',
    sniffer: '👁 旁路探针 — 点击放置，0入0出独立监听信号源',
    record_end: '⏹ 记录终止 — 点击放置，1进0出，记录后终止',
  };

  document.querySelectorAll('.palette-item').forEach(el => {
    const type = el.dataset.type;
    const tooltip = tooltipMap[type];
    if (tooltip) el.title = tooltip;
    el.addEventListener('mouseenter', () => el.style.background = '#e0e0e0');
    el.addEventListener('mouseleave', () => el.style.background = '#f0f0f0');
  });
}

// ============================================================================
// Init
// ============================================================================

loadSignalSources();
loadActuatorSources();          // D-30: 预加载执行器列表
initPaletteTooltips();
updateFlowEditorAccess();
