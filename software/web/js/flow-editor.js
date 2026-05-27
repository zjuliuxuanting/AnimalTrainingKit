let flowNodes = {};
let flowEdges = [];
let selectedNodeId = null;
let nodeIdCounter = 0;
let dragState = null;
let connectingFrom = null;
let connectingFromPort = 'out';
let connectingMousePos = null;
let historyStack = [];
let historyIndex = -1;
const MAX_HISTORY = 50;
let undoBlocked = false;

function saveHistory() {
  if (undoBlocked) return;
  const snapshot = {
    nodes: JSON.parse(JSON.stringify(Object.fromEntries(
      Object.entries(flowNodes).map(([id, n]) => [id, { type: n.type, label: n.label, params: n.params, fixed: n.fixed, left: parseInt(n.el.style.left), top: parseInt(n.el.style.top) }])
    ))),
    edges: JSON.parse(JSON.stringify(flowEdges)),
    counter: nodeIdCounter,
  };
  if (historyIndex < historyStack.length - 1) {
    historyStack = historyStack.slice(0, historyIndex + 1);
  }
  historyStack.push(snapshot);
  if (historyStack.length > MAX_HISTORY) historyStack.shift();
  historyIndex = historyStack.length - 1;
}

function undoFlow() {
  if (historyIndex <= 0) return;
  historyIndex--;
  undoBlocked = true;
  restoreHistory(historyStack[historyIndex]);
  setTimeout(() => { undoBlocked = false; }, 50);
}

function redoFlow() {
  if (historyIndex >= historyStack.length - 1) return;
  historyIndex++;
  undoBlocked = true;
  restoreHistory(historyStack[historyIndex]);
  setTimeout(() => { undoBlocked = false; }, 50);
}

function restoreHistory(snapshot) {
  document.getElementById('flowNodes').innerHTML = '';
  flowNodes = {};
  flowEdges = [];
  nodeIdCounter = snapshot.counter || 0;

  const canvas = document.getElementById('flowCanvas');
  for (const [id, nd] of Object.entries(snapshot.nodes)) {
    const el = createNodeEl(nd.type, nd.label, nd.params);
    el.id = 'node_' + id;
    el.style.left = nd.left + 'px';
    el.style.top = nd.top + 'px';
    flowNodes[id] = { el, type: nd.type, label: nd.label, params: nd.params || {}, fixed: nd.fixed || false };
    if (!nd.fixed) makeDraggable(el, id);
    canvas.appendChild(el);
  }
  flowEdges = JSON.parse(JSON.stringify(snapshot.edges || []));
  updateSvg();
  selectedNodeId = null;
  document.getElementById('flowConfigPanel').style.display = 'none';
}

const NODE_COLORS = {
  start: '#4CAF50', end: '#F44336', trigger: '#FF9800',
  delay: '#9C27B0', condition: '#2196F3', execute: '#1976D2',
  loop: '#E91E63', variable: '#607D8B', record: '#795548',
};

const NODE_DEFAULTS = {
  start: {},
  end: {},
  trigger: { signal_id: 'mock:0:mock:trigger', trigger: 'click', debounce_ms: 0 },
  delay: { duration_ms: 1000 },
  condition: { variable: '计数', operator: 'gt', value: 5 },
  execute: { actuator_id: '出粮器', action: 'pulse', duration_ms: 1000 },
  loop: { max_iterations: 10, timeout_ms: 60000 },
  variable: { name: '计数', operation: 'inc', value: 1 },
  record: { event_name: '记录事件' },
};

function initFixedNodes() {
  const canvas = document.getElementById('flowCanvas');
  const rect = canvas.getBoundingClientRect();

  // Check if START/END already exist in flow (after loading)
  const hasStart = Object.values(flowNodes).some(n => n.type === 'start');
  const hasEnd = Object.values(flowNodes).some(n => n.type === 'end');

  // START node - fixed top-left
  if (!hasStart && !flowNodes['start_0']) {
    const startEl = createNodeEl('start', '开始', {});
    startEl.id = 'node_start_0';
    startEl.style.left = '16px';
    startEl.style.top = '16px';
    startEl.style.cursor = 'default';
    startEl.style.opacity = '0.85';
    flowNodes['start_0'] = { el: startEl, type: 'start', label: '开始', params: {}, fixed: true };
    canvas.appendChild(startEl);
  }

  // END node - fixed bottom-right
  if (!hasEnd && !flowNodes['end_0']) {
    const endEl = createNodeEl('end', '结束', {});
    endEl.id = 'node_end_0';
    endEl.style.left = (rect.width - 156) + 'px';
    endEl.style.top = (rect.height - 76) + 'px';
    endEl.style.cursor = 'default';
    endEl.style.opacity = '0.85';
    flowNodes['end_0'] = { el: endEl, type: 'end', label: '结束', params: {}, fixed: true };
    canvas.appendChild(endEl);
  }
}

function getFlowData() {
  const nodes = {};
  for (const [id, n] of Object.entries(flowNodes)) {
    nodes[id] = {
      id, node_type: n.type, label: n.label,
      params: n.params || {},
      x: parseInt(n.el.style.left), y: parseInt(n.el.style.top),
    };
  }
  const edges = flowEdges.map(e => ({
    id: e.id, source_node: e.source, source_port: e.sourcePort || 'out',
    target_node: e.target, target_port: e.targetPort || 'in',
  }));
  return { id: 'flow_web', name: '实验流程', nodes, edges };
}

function loadFlowData(data) {
  flowNodes = {};
  flowEdges = [];
  document.getElementById('flowNodes').innerHTML = '';
  nodeIdCounter = 0;
  connectingFrom = null;
  connectingMousePos = null;

  if (data && data.nodes) {
    for (const [id, nd] of Object.entries(data.nodes)) {
      const n = createNodeEl(nd.node_type, nd.label || id, nd.params);
      n.id = 'node_' + id;
      n.style.left = (nd.x || 100) + 'px';
      n.style.top = (nd.y || 100) + 'px';
      flowNodes[id] = { el: n, type: nd.node_type, label: nd.label || id, params: nd.params || {}, fixed: false };
      document.getElementById('flowNodes').appendChild(n);
      makeDraggable(n, id);
      const idx = parseInt(id.split('_')[1]) || 0;
      if (idx > nodeIdCounter) nodeIdCounter = idx;
    }
    if (data.edges) {
      for (const e of data.edges) {
        const edgeId = 'edge_' + Math.random().toString(36).slice(2, 8);
        flowEdges.push({ id: edgeId, source: e.source_node, sourcePort: e.source_port || 'out', target: e.target_node, targetPort: e.target_port || 'in' });
      }
    }
  }
  initFixedNodes();
  saveHistory();
  updateSvg();
}

function createNodeEl(type, label, params) {
  const div = document.createElement('div');
  div.className = 'flow-node';
  const color = NODE_COLORS[type] || '#999';
  const icons = { start: '🏁', end: '⏹', trigger: '⚡', delay: '⏱', condition: '🔀', execute: '🛠', loop: '🔄', variable: '📦', record: '📝' };
  let portsHtml = `<div class="node-port node-port-in" data-node="${type}_in"></div>`;
  if (type === 'loop') {
    portsHtml += `<div class="node-port node-port-out" data-port="body" style="right:30px" title="循环体">循环体</div>`;
    portsHtml += `<div class="node-port node-port-out" data-port="exit" style="right:-6px" title="退出">退出</div>`;
  } else if (type === 'condition') {
    portsHtml += `<div class="node-port node-port-out" data-port="true" style="right:30px" title="True">真</div>`;
    portsHtml += `<div class="node-port node-port-out" data-port="false" style="right:-6px" title="False">假</div>`;
  } else {
    portsHtml += `<div class="node-port node-port-out" data-node="${type}_out" style="right:-6px"></div>`;
  }
  div.innerHTML = `<div class="node-header" style="background:${color}"><span>${icons[type] || '●'}</span> ${label || type}</div>
    <div class="node-body">${type}</div>${portsHtml}`;
  div.style.position = 'absolute';
  div.style.width = '140px';
  div.style.cursor = 'move';
  div.style.background = 'white';
  div.style.borderRadius = '8px';
  div.style.boxShadow = '0 2px 8px rgba(0,0,0,0.12)';
  div.style.overflow = 'visible';
  div.style.border = '2px solid transparent';
  div.style.zIndex = '10';
  div.querySelector('.node-header').style.cssText = `padding:6px 10px;color:white;font-size:12px;font-weight:600`;
  div.querySelector('.node-body').style.cssText = `padding:8px 10px;font-size:11px;color:#666`;
  const inPort = div.querySelector('.node-port-in');
  if (inPort) {
    inPort.style.cssText = `position:absolute;left:-6px;top:50%;width:12px;height:12px;background:${color};border:2px solid white;border-radius:50%;cursor:crosshair;transform:translateY(-6px)`;
    inPort.title = '点击此处拖出连线';
  }
  const outPorts = div.querySelectorAll('.node-port-out');
  outPorts.forEach(pt => {
    const pStyle = pt.getAttribute('style') || '';
    pt.style.cssText = pStyle + `;position:absolute;top:50%;width:12px;height:12px;background:${color};border:2px solid white;border-radius:50%;cursor:crosshair;transform:translateY(-6px);font-size:9px;display:flex;align-items:center;justify-content:center;color:white;font-weight:bold`;
    pt.title = '点击此处拖出连线';
  });

  // Hover: highlight connection points
  div.addEventListener('mouseenter', () => {
    outPorts.forEach(p => p.style.transform = 'translateY(-6px) scale(1.3)');
    if (inPort) inPort.style.transform = 'translateY(-6px) scale(1.3)';
  });
  div.addEventListener('mouseleave', () => {
    if (connectingFrom) return;
    outPorts.forEach(p => p.style.transform = 'translateY(-6px) scale(1)');
    if (inPort) inPort.style.transform = 'translateY(-6px) scale(1)';
  });

  div.addEventListener('dblclick', () => selectNode(getNodeId(div)));
  return div;
}

function getNodeId(el) {
  for (const [id, n] of Object.entries(flowNodes)) {
    if (n.el === el) return id;
  }
  return null;
}

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
  if (n.fixed) { document.getElementById('flowConfigPanel').style.display = 'none'; return; }
  document.getElementById('flowConfigPanel').style.display = 'block';
  document.getElementById('cfgLabel').value = n.label || n.type;
  const params = n.params || {};
  let extra = '';

  if (n.type === 'trigger') {
    extra = `<label>信号源</label><select id="signalSourceSelect" onchange="updateParam('${id}','signal_id',this.value)">
      <option value="生成信号" ${params.signal_id==='生成信号'?'selected':''}>模拟信号（测试用）</option>
      <option value="硬件传感器" ${params.signal_id==='硬件传感器'?'selected':''}>硬件传感器（控制盒）</option>
      ${getSignalSourceOptions(params.signal_id)}
    </select>
    <label>触发方式</label><select onchange="updateParam('${id}','trigger',this.value)">
      <option value="click" ${params.trigger==='click'?'selected':''}>单击（动物触碰/进入区域）</option>
      <option value="double_click" ${params.trigger==='double_click'?'selected':''}>双击（快速进出）</option>
      <option value="hold" ${params.trigger==='hold'?'selected':''}>按住（持续在区域内）</option>
      <option value="release" ${params.trigger==='release'?'selected':''}>释放（动物离开区域）</option>
    </select>`;
  } else if (n.type === 'delay') {
    extra = `<label>等待时间（毫秒）</label><input type="number" value="${params.duration_ms || 1000}" onchange="updateParam('${id}','duration_ms',parseInt(this.value))">
      <p style="color:var(--text-secondary);font-size:11px;margin-top:4px">💡 1000 毫秒 = 1 秒</p>`;
  } else if (n.type === 'execute') {
    extra = `<label>执行器名称</label><input value="${escapeHtml(params.actuator_id || '')}" onchange="updateParam('${id}','actuator_id',this.value)">
      <label>动作类型</label><select onchange="updateParam('${id}','action',this.value)">
        <option value="high" ${params.action==='high'?'selected':''}>开启</option>
        <option value="low" ${params.action==='low'?'selected':''}>关闭</option>
        <option value="toggle" ${params.action==='toggle'?'selected':''}>切换</option>
        <option value="pulse" ${params.action==='pulse'?'selected':''}>脉冲（持续一段时间后关闭）</option>
      </select>
      <div id="pulseParam" style="${params.action==='pulse'?'':'display:none'}">
        <label>脉冲时长（毫秒）</label><input type="number" value="${params.duration_ms || 1000}" onchange="updateParam('${id}','duration_ms',parseInt(this.value))">
      </div>`;
  } else if (n.type === 'condition') {
    extra = `<label>变量名</label><input value="${escapeHtml(params.variable || '计数')}" onchange="updateParam('${id}','variable',this.value)">
      <label>比较方式</label><select onchange="updateParam('${id}','operator',this.value)">
        <option value="eq" ${params.operator==='eq'?'selected':''}>等于</option>
        <option value="gt" ${params.operator==='gt'?'selected':''}>大于</option>
        <option value="lt" ${params.operator==='lt'?'selected':''}>小于</option>
        <option value="gte" ${params.operator==='gte'?'selected':''}>大于等于</option>
        <option value="lte" ${params.operator==='lte'?'selected':''}>小于等于</option>
      </select>
      <label>比较值</label><input type="number" value="${params.value || 0}" onchange="updateParam('${id}','value',parseInt(this.value))">`;
  } else if (n.type === 'loop') {
    extra = `<label>最大循环次数</label><input type="number" value="${params.max_iterations || 10}" onchange="updateParam('${id}','max_iterations',parseInt(this.value))">
      <label>超时时间（秒）</label><input type="number" value="${(params.timeout_ms || 60000)/1000}" onchange="updateParam('${id}','timeout_ms',parseInt(this.value)*1000)">`;
  } else if (n.type === 'variable') {
    extra = `<label>变量名</label><input value="${escapeHtml(params.name || '计数')}" onchange="updateParam('${id}','name',this.value)">
      <label>操作</label><select onchange="updateParam('${id}','operation',this.value)">
        <option value="set" ${params.operation==='set'?'selected':''}>赋值为</option>
        <option value="inc" ${params.operation==='inc'?'selected':''}>加 1</option>
        <option value="dec" ${params.operation==='dec'?'selected':''}>减 1</option>
      </select>
      <div id="setValueParam" style="${params.operation==='set'?'':'display:none'}">
        <label>值</label><input type="number" value="${params.value || 0}" onchange="updateParam('${id}','value',parseInt(this.value))">
      </div>`;
  } else if (n.type === 'record') {
    extra = `<label>事件名称</label><input value="${escapeHtml(params.event_name || '记录事件')}" onchange="updateParam('${id}','event_name',this.value)">
      <p style="color:var(--text-secondary);font-size:11px;margin-top:4px">该事件会被记录到实验数据中</p>`;
  }
  document.getElementById('cfgExtra').innerHTML = extra;
}

let _cachedSources = null;
let _cachedOptionsHtml = '';
let _sourcesLoading = false;

async function loadSignalSources() {
  if (_sourcesLoading) return;
  _sourcesLoading = true;
  try {
    const resp = await fetch('/api/sources');
    const data = await resp.json();
    _cachedSources = data.sources || [];
    _cachedOptionsHtml = _cachedSources.map(s =>
      `<option value="${s.id}">${s.label}</option>`
    ).join('');
  } catch (e) {
    _cachedOptionsHtml = `<option value="camera:区域A:enter">摄像头 - 区域 A - 进入</option>
      <option value="camera:区域A:leave">摄像头 - 区域 A - 离开</option>`;
  }
  _sourcesLoading = false;
  if (selectedNodeId && flowNodes[selectedNodeId] && flowNodes[selectedNodeId].type === 'trigger') {
    showConfigPanel(selectedNodeId);
  }
}

function getSignalSourceOptions(selected) {
  if (_cachedSources) {
    return _cachedSources.map(s => {
      const sel = selected === s.id ? 'selected' : '';
      return `<option value="${s.id}" ${sel}>${s.label}</option>`;
    }).join('');
  }
  return `<option value="生成信号" ${selected==='生成信号'?'selected':''}>模拟信号（测试用）</option>
    <option value="硬件传感器" ${selected==='硬件传感器'?'selected':''}>硬件传感器（控制盒）</option>
    <option value="camera:区域A:enter" ${selected==='camera:区域A:enter'?'selected':''}>摄像头 - 区域 A - 进入</option>
    <option value="camera:区域A:leave" ${selected==='camera:区域A:leave'?'selected':''}>摄像头 - 区域 A - 离开</option>`;
}

loadSignalSources();

function updateParam(id, key, value) {
  if (flowNodes[id]) {
    if (!flowNodes[id].params) flowNodes[id].params = {};
    flowNodes[id].params[key] = value;
  }
  showConfigPanel(id);
}

function updateNodeConfig() {
  const id = selectedNodeId;
  const label = document.getElementById('cfgLabel').value;
  if (id && flowNodes[id] && !flowNodes[id].fixed) {
    flowNodes[id].label = label;
    const hdr = flowNodes[id].el.querySelector('.node-header');
    if (hdr) {
      const span = hdr.querySelector('span');
      if (span) hdr.innerHTML = span.outerHTML + ' ' + label;
      else hdr.textContent = label;
    }
  }
}

function makeDraggable(el, id) {
  let offsetX, offsetY;
  el.addEventListener('mousedown', (e) => {
    if (e.target.classList.contains('node-port')) return;
    if (flowNodes[id] && flowNodes[id].fixed) return;
    offsetX = e.offsetX;
    offsetY = e.offsetY;
    dragState = { el, id, offsetX, offsetY };
    el.style.zIndex = '20';
    el.style.boxShadow = '0 4px 16px rgba(0,0,0,0.2)';
    e.preventDefault();
  });
}

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
  // Update connecting line while dragging
  if (connectingFrom) {
    connectingMousePos = { x: e.clientX, y: e.clientY };
    const canvas = document.getElementById('flowCanvas');
    const rect = canvas.getBoundingClientRect();
    updateConnectingLine(rect);
  }
});

document.addEventListener('mouseup', (e) => {
  if (dragState) {
    dragState.el.style.zIndex = '10';
    dragState.el.style.boxShadow = '0 2px 8px rgba(0,0,0,0.12)';
    dragState = null;
  }

  // Finish connection
  if (connectingFrom) {
    const port = e.target.closest('.node-port-in, .node-port-out');
    if (port && port.classList.contains('node-port-in')) {
      const nodeEl = port.closest('.flow-node');
      const toId = getNodeId(nodeEl);
      if (toId && toId !== connectingFrom) {
        const exists = flowEdges.some(ed => ed.source === connectingFrom && ed.target === toId);
        if (!exists) {
          const edgeId = 'edge_' + Math.random().toString(36).slice(2, 8);
          flowEdges.push({ id: edgeId, source: connectingFrom, sourcePort: connectingFromPort, target: toId });
        }
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

function updateConnectingLine(rect) {
  let line = document.getElementById('connectingLine');
  if (!line) {
    const svg = document.getElementById('flowSvg');
    line = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    line.id = 'connectingLine';
    line.classList.add('flow-connecting-line');
    svg.appendChild(line);
  }
  const srcNode = flowNodes[connectingFrom];
  if (!srcNode || !connectingMousePos) return;
  const sx = parseInt(srcNode.el.style.left) + 140;
  const sy = parseInt(srcNode.el.style.top) + 30;
  const tx = connectingMousePos.x - rect.left;
  const ty = connectingMousePos.y - rect.top;
  const midX = (sx + tx) / 2;
  line.setAttribute('d', `M${sx},${sy} C${midX},${sy} ${midX},${ty} ${tx},${ty}`);
}

// Start connection from output port
document.addEventListener('mousedown', (e) => {
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

document.getElementById('nodePalette').addEventListener('mousedown', (e) => {
  const item = e.target.closest('.palette-item');
  if (!item) return;
  e.preventDefault();
  const type = item.dataset.type;
  nodeIdCounter++;
  const id = type + '_' + nodeIdCounter;
  const label = item.textContent.trim();
  const el = createNodeEl(type, label, { ...NODE_DEFAULTS[type] });
  el.id = 'node_' + id;
  el.style.left = '200px';
  el.style.top = '100px';
  document.getElementById('flowNodes').appendChild(el);
  flowNodes[id] = { el, type, label, params: { ...NODE_DEFAULTS[type] }, fixed: false };
  makeDraggable(el, id);
  selectNode(id);
  saveHistory();
  updateSvg();
});

document.addEventListener('contextmenu', (e) => {
  const nodeEl = e.target.closest('.flow-node');
  if (nodeEl) {
    e.preventDefault();
    const id = getNodeId(nodeEl);
    if (!id) return;
    if (flowNodes[id] && flowNodes[id].fixed) {
      toast('开始和结束节点不可删除', 'warn');
      return;
    }
    if (confirm('删除节点「' + (flowNodes[id]?.label || id) + '」？')) {
      flowEdges = flowEdges.filter(ed => ed.source !== id && ed.target !== id);
      delete flowNodes[id];
      nodeEl.remove();
      saveHistory();
      updateSvg();
      if (selectedNodeId === id) { selectedNodeId = null; document.getElementById('flowConfigPanel').style.display = 'none'; }
    }
    return;
  }
});

function updateSvg() {
  const svg = document.getElementById('flowSvg');
  svg.innerHTML = '';

  // Arrow marker
  const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
  defs.innerHTML = '<marker id="arrowhead" markerWidth="10" markerHeight="7" refX="10" refY="3.5" orient="auto"><polygon points="0 0, 10 3.5, 0 7" fill="#90A4AE"/></marker>';
  svg.appendChild(defs);

  for (const edge of flowEdges) {
    const srcNode = flowNodes[edge.source];
    const tgtNode = flowNodes[edge.target];
    if (!srcNode || !tgtNode) continue;

    const sx = parseInt(srcNode.el.style.left) + 140;
    const sy = parseInt(srcNode.el.style.top) + 30;
    const tx = parseInt(tgtNode.el.style.left);
    const ty = parseInt(tgtNode.el.style.top) + 30;

    const midX = (sx + tx) / 2;
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', `M${sx},${sy} C${midX},${sy} ${midX},${ty} ${tx},${ty}`);
    path.setAttribute('stroke', '#90A4AE');
    path.setAttribute('stroke-width', '2');
    path.setAttribute('fill', 'none');
    path.setAttribute('marker-end', 'url(#arrowhead)');
    svg.appendChild(path);
  }
}

async function saveFlow() {
  const data = getFlowData();
  if (!data.nodes || Object.keys(data.nodes).length === 0) {
    toast('请先从左侧面板拖拽节点到画布', 'warn');
    return;
  }
  const name = prompt('流程名称:', data.name || '我的实验流程');
  if (!name) return;
  try {
    const result = await api('/api/flows/save', {
      method: 'POST',
      body: JSON.stringify({ name, flow: data }),
    });
    toast('流程已保存: ' + result.filename, 'success');
    loadFlows();
  } catch (e) {
    toast('保存失败: ' + e.message, 'error');
  }
}

async function loadFlow() {
  const data = await api('/api/flows');
  if (data.flows.length === 0) {
    toast('暂无已保存的流程', 'info');
    return;
  }
  const fname = prompt('请粘贴要加载的流程文件名:\n' + data.flows.map(f => '  ' + f.id).join('\n'));
  if (!fname) return;
  loadFlowFile(fname);
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

document.querySelectorAll('.palette-item').forEach(el => {
  el.style.cssText = 'padding:6px 10px;margin:2px 0;border-radius:4px;cursor:grab;font-size:12px;background:#f0f0f0;transition:all 0.2s';
  el.addEventListener('mouseenter', () => el.style.background = '#e0e0e0');
  el.addEventListener('mouseleave', () => el.style.background = '#f0f0f0');
});
  
// Don't call initFixedNodes here - called when flow tab is activated
// initFixedNodes();

// Load signal sources from backend for TRIGGER dropdown
loadSignalSources();
