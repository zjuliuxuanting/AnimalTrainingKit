/**
 * Flow Model — Data layer for the flow editor.
 *
 * Contains: NODE_SCHEMAS, state variables, history (undo/redo),
 * serialization (getFlowData/loadFlowData), and debugState().
 */

// ============================================================================
// Schema Definition — 13 node types (G3)
// ============================================================================
// Color groups:
//   TRIGGER  = orange   (#FF9800)
//   CONTROL  = purple/blue  (#7C4DFF / #5C6BC0)
//   EXECUTE  = green    (#43A047)
//   LOGIC    = grey     (#78909C)
// ============================================================================

const NODE_SCHEMAS = {
  start: {
    label: '开始',
    color: '#4C9B50',
    icon: '🔴',
    fields: [],
    help: '',
    ports: { inputs: 0, outputs: 1 },
  },
  end: {
    label: '结束',
    color: '#D32F2F',
    icon: '⏹',
    fields: [],
    help: '',
    ports: { inputs: -1, outputs: 0 }, // -1 means >=1
  },
  // --- TRIGGER group (orange) ---
  trigger: {
    label: '触发信号',
    color: '#FF9800',
    icon: '⚡',
    fields: [
      {
        key: 'signal_id',
        label: '信号源',
        type: 'select',
        options: 'dynamic', // loaded from GET /api/sources
        default: '',        // overridden in createNodeEl() with first available source
        required: true,
      },
    ],
    help: '从注册中心选择信号源。摄像头区域事件在配置 zone 后自动注册，硬件设备连接后自动注册。',
    ports: { inputs: -1, outputs: 1 },
  },
  // --- CONTROL group (purple/blue) ---
  delay: {
    label: '延时等待',
    color: '#7C4DFF',
    icon: '⏱',
    fields: [
      {
        key: 'duration_value',
        label: '等待数值',
        type: 'number',
        min: 0,
        max: 1000,
        step: 1,
        default: 1,
        integer: true,
        required: true,
      },
      {
        key: 'duration_unit',
        label: '时间单位',
        type: 'select',
        options: [
          { value: 'seconds', label: '秒' },
          { value: 'minutes', label: '分钟' },
          { value: 'hours', label: '小时' },
        ],
        default: 'seconds',
        required: true,
      },
    ],
    help: '流程执行到此节点时暂停指定时长。按整数数值 + 秒/分钟/小时配置。',
    ports: { inputs: -1, outputs: 1 },
  },
  condition: {
    label: '条件判断',
    color: '#5C6BC0',
    icon: '🔀',
    fields: [
      {
        key: 'source',
        label: '数据来源',
        type: 'select',
        options: [
          { value: 'trigger_count', label: 'TRIGGER 累计计数' },
          { value: 'variable', label: '变量' },
        ],
        default: 'trigger_count',
        required: true,
      },
      {
        key: 'variable_name',
        label: '变量名称',
        type: 'text',
        maxLength: 64,
        required: false,
        condition: (params) => params.source === 'variable',
      },
      {
        key: 'operator',
        label: '判断条件',
        type: 'select',
        options: [
          { value: 'eq', label: '等于' },
          { value: 'neq', label: '不等于' },
          { value: 'gt', label: '大于' },
          { value: 'lt', label: '小于' },
          { value: 'gte', label: '大于等于' },
          { value: 'lte', label: '小于等于' },
        ],
        default: 'gt',
        required: true,
      },
      {
        key: 'value',
        label: '判断值',
        type: 'number',
        min: -999999,
        max: 999999,
        default: 0,
        integer: true,
        required: true,
        condition: (params) => params.compare_source !== 'variable',
      },
      {
        key: 'compare_source',
        label: '比较对象',
        type: 'select',
        options: [
          { value: 'value', label: '固定数值' },
          { value: 'variable', label: '变量' },
        ],
        default: 'value',
        required: false,
      },
      {
        key: 'compare_variable_name',
        label: '比较变量名称',
        type: 'text',
        maxLength: 64,
        required: false,
        condition: (params) => params.compare_source === 'variable',
      },
    ],
    help: '根据上游数据做条件判断。可读取运行时变量和持久变量。',
    ports: { inputs: 1, outputs: 2, outputLabels: ['真', '假'], outputPorts: ['true', 'false'] },
  },
  // --- EXECUTE group (green) ---
  execute: {
    label: '执行动作',
    color: '#43A047',
    icon: '🛠',
    fields: [
      {
        key: 'actuator_id',
        label: '执行器名称',
        type: 'select',
        options: 'dynamic',  // loaded from GET /api/registry/actuators
        required: true,
      },
      {
        key: 'action',
        label: '动作类型',
        type: 'select',
        options: [
          { value: 'high', label: '开启' },
          { value: 'low', label: '关闭' },
        ],
        default: 'high',
        required: true,
      },
    ],
    help: '调用指定执行器执行动作。开启/关闭模式，具体参数由硬件模块自管。',
    ports: { inputs: -1, outputs: 1 },
  },
  loop: {
    label: '循环',
    color: '#7C4DFF',
    icon: '🔄',
    fields: [
      {
        key: 'max_iterations',
        label: '最大循环次数',
        type: 'number',
        min: 1,
        max: 10000,
        default: 10,
        required: true,
      },
      {
        key: 'timeout_s',
        label: '超时时间',
        type: 'number',
        min: 1,
        max: 3600,
        step: 1,
        default: 60,
        unit: '秒',
        required: true,
      },
    ],
    help: '循环执行，最多循环 max_iterations 次或超时 timeout_s 秒（哪个先到就退出）。循环结束后流程继续向下执行。',
    ports: { inputs: 1, outputs: 2, outputLabels: ['循环体', '退出'], outputPorts: ['body', 'exit'] },
  },
  // --- LOGIC group (grey) ---
  and: {
    label: '逻辑与',
    color: '#78909C',
    icon: '📦',
    fields: [],
    help: '所有输入端口都收到信号后才触发输出。用于多路径汇聚。',
    ports: { inputs: -1, outputs: 1 },
  },
  not: {
    label: '逻辑非',
    color: '#B0BEC5',
    icon: '❑',
    fields: [
      {
        key: 'signal_id',
        label: '检测信号源',
        type: 'select',
        options: 'dynamic',
        required: true,
      },
      {
        key: 'timeout_s',
        label: '消失等待',
        type: 'number',
        min: 0.1,
        max: 3600,
        step: 0.1,
        default: 5,
        unit: '秒',
        required: true,
      },
    ],
    help: '等待信号消失后放行：在超时上限内持续检测指定信号源，若无事件则放行。常用于检测动物离开区域等场景。',
    ports: { inputs: 1, outputs: 1 },
  },
  fork: {
    label: '逻辑分叉',
    color: '#90A4AE',
    icon: '🔁',
    fields: [],
    help: '同时触发下游两条路径。无配置参数。两路完全独立，各自走各自的流程。',
    ports: { inputs: 1, outputs: 2, outputLabels: ['继续', '记录终止'], outputPorts: ['continue', 'stop'] },
  },
  record: {
    label: '记录事件',
    color: '#43A047',
    icon: '📝',
    fields: [
      {
        key: 'event_name',
        label: '事件名称',
        type: 'text',
        maxLength: 100,
        required: true,
      },
      {
        key: 'variable_name',
        label: '变量名称',
        type: 'text',
        maxLength: 64,
        required: false,
      },
      {
        key: 'variable_op',
        label: '变量操作',
        type: 'select',
        options: [
          { value: 'add', label: '加' },
          { value: 'subtract', label: '减' },
          { value: 'set', label: '设为' },
        ],
        default: 'add',
        required: false,
      },
      {
        key: 'variable_value',
        label: '变量数值',
        type: 'number',
        min: -999999,
        max: 999999,
        step: 1,
        default: 1,
        integer: true,
        required: false,
      },
      {
        key: 'variable_persistent',
        label: '是否持久状态',
        type: 'checkbox',
        default: false,
        required: false,
      },
    ],
    help: '记录实验事件，并可选写入变量。勾选持久状态后变量跨服务重启保留。',
    ports: { inputs: -1, outputs: 1 },
  },
  sniffer: {
    label: '旁路探针',
    color: '#FFB74D',
    icon: '👁',
    fields: [
      {
        key: 'signal_id',
        label: '监听信号源',
        type: 'select',
        options: 'dynamic',
        required: true,
      },
      {
        key: 'event_name',
        label: '事件别名',
        type: 'text',
        maxLength: 100,
        default: '旁路记录',
        required: true,
      },
    ],
    help: '旁路观测节点。0入0出，不参与流程拓扑。运行时独立监听指定信号源，全程记录事件。',
    ports: { inputs: 0, outputs: 0 },
  },
  record_end: {
    label: '记录终止',
    color: '#E53935',
    icon: '⏹',
    fields: [
      { key: 'event_name', label: '事件名称', type: 'text', maxLength: 100, required: true },
    ],
    help: '记录后终止流程分支。用于分支路径的终点记录，记录完成即停止，不再往下执行。',
    ports: { inputs: -1, outputs: 0 },
  },
};

// Palette display order
const PALETTE_ORDER = ['trigger', 'delay', 'condition', 'execute', 'loop', 'and', 'not', 'fork', 'record', 'sniffer'];

// ============================================================================
// State
// ============================================================================

let flowNodes = {};
let flowEdges = [];
let selectedNodeId = null;
let selectedEdgeId = null;
let nodeIdCounter = 0;
let dragState = null;
let connectingFrom = null;
let connectingFromPort = 'out';
let connectingMousePos = null;
let historyStack = [];
let historyIndex = -1;
const MAX_HISTORY = 50;
let undoBlocked = false;

// CR-3: offset counter for new node creation position
let nodeCreationOffset = 0;

// Signal source cache (for TRIGGER dynamic dropdown)
let _cachedSources = null;
let _sourcesLoading = false;

// Actuator cache (D-30: for EXECUTE dynamic dropdown)
let _cachedActuators = null;
let _actuatorsLoading = false;

// G3-FIN-1: current experiment ID (set by app.js enterExperiment)
let currentExperimentId = null;

// ============================================================================
// History (undo/redo)
// ============================================================================

function saveHistory() {
  if (undoBlocked) return;
  const snapshot = {
    nodes: JSON.parse(JSON.stringify(Object.fromEntries(
      Object.entries(flowNodes).map(([id, n]) => [id, {
        type: n.type,
        label: n.label,
        params: n.params,
        fixed: n.fixed,
        left: parseInt(n.el.style.left),
        top: parseInt(n.el.style.top),
      }])
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
  debugState(false);
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
  // Clear all non-fixed nodes from flowNodes div
  const flowNodesDiv = document.getElementById('flowNodes');
  flowNodesDiv.innerHTML = '';
  flowNodes = {};
  flowEdges = [];
  nodeIdCounter = snapshot.counter || 0;
  if (typeof setFlowWorkspaceBaseSize === 'function') {
    let right = FLOW_WORKSPACE_MIN_WIDTH;
    let bottom = FLOW_WORKSPACE_MIN_HEIGHT;
    Object.values(snapshot.nodes || {}).forEach((nd) => {
      right = Math.max(right, Number(nd.left || 0) + FLOW_NODE_WIDTH + 220);
      bottom = Math.max(bottom, Number(nd.top || 0) + FLOW_NODE_MIN_HEIGHT + 180);
    });
    setFlowWorkspaceBaseSize(right, bottom);
  }

  for (const [id, nd] of Object.entries(snapshot.nodes)) {
    const params = normalizeNodeParams(nd.type, nd.params || {});
    const displayLabel = getNodeDisplayName(nd.type, nd.label, params, true);
    const el = createNodeEl(nd.type, displayLabel, params);
    el.id = 'node_' + id;
    flowNodesDiv.appendChild(el);
    placeNodeWithinCanvas(el, Number(nd.left), Number(nd.top));
    flowNodes[id] = { el, type: nd.type, label: getCanonicalNodeLabel(nd.type), params, fixed: nd.fixed || false };
    if (!nd.fixed) makeDraggable(el, id);
  }
  flowEdges = JSON.parse(JSON.stringify(snapshot.edges || []));
  updateSvg();
  selectedNodeId = null;
  document.getElementById('flowConfigPanel').style.display = 'none';
  debugState(false);
}

// ============================================================================
// Node ID helpers
// ============================================================================

function getNodeId(el) {
  for (const [id, n] of Object.entries(flowNodes)) {
    if (n.el === el) return id;
  }
  return null;
}

// ============================================================================
// Flow data save/load
// ============================================================================

function getCanonicalNodeLabel(type) {
  return NODE_SCHEMAS[type]?.label || type;
}

function getNodeDisplayName(type, savedLabel = '', params = {}, includeCanonical = true) {
  const canonical = getCanonicalNodeLabel(type);
  const explicit = (params?.display_name || '').trim();
  if (explicit) return explicit;
  const legacyLabel = String(savedLabel || '').trim();
  if (legacyLabel && legacyLabel !== canonical && legacyLabel !== type) return legacyLabel;
  return includeCanonical ? canonical : '';
}

function normalizeNodeParams(type, params = {}) {
  const next = { ...(params || {}) };

  if (type === 'delay') {
    if (next.duration_value === undefined && next.duration_s !== undefined) {
      const seconds = Number(next.duration_s);
      next.duration_value = Number.isFinite(seconds) ? Math.max(0, Math.min(1000, Math.round(seconds))) : 1;
      next.duration_unit = 'seconds';
    }
    delete next.duration_s;
    if (next.duration_value === undefined || next.duration_value === null || next.duration_value === '') {
      next.duration_value = 1;
    } else {
      const value = Number(next.duration_value);
      next.duration_value = Number.isFinite(value) ? Math.max(0, Math.min(1000, Math.round(value))) : 1;
    }
    if (!['seconds', 'minutes', 'hours'].includes(next.duration_unit)) {
      next.duration_unit = 'seconds';
    }
  }

  if (type === 'record') {
    if (next.counter_name && next.counter_op && !next.variable_name) {
      const opMap = {
        '+1': ['add', 1],
        '-1': ['subtract', 1],
        '=0': ['set', 0],
        '=1': ['set', 1],
      };
      if (opMap[next.counter_op]) {
        next.variable_name = next.counter_name;
        next.variable_op = opMap[next.counter_op][0];
        next.variable_value = opMap[next.counter_op][1];
        next.variable_persistent = false;
        delete next.counter_name;
        delete next.counter_op;
      }
    }
    if (next.variable_op && !['add', 'subtract', 'set'].includes(next.variable_op)) {
      next.variable_op = 'add';
    }
    if (next.variable_value !== undefined && next.variable_value !== null && next.variable_value !== '') {
      const value = Number(next.variable_value);
      next.variable_value = Number.isFinite(value) ? Math.round(value) : 0;
    }
    if (next.variable_persistent !== undefined) {
      next.variable_persistent = Boolean(next.variable_persistent);
    }
  }

  if (type === 'condition') {
    if (next.source === 'counter' && next.counter_name && !next.variable_name) {
      next.source = 'variable';
      next.variable_name = next.counter_name;
      delete next.counter_name;
    }
    if (!['trigger_count', 'variable'].includes(next.source)) {
      next.source = 'trigger_count';
    }
    if (!['value', 'variable'].includes(next.compare_source)) {
      next.compare_source = 'value';
    }
    if (next.compare_source !== 'variable') {
      const value = Number(next.value ?? 0);
      next.value = Number.isFinite(value) ? Math.round(value) : 0;
    }
  }

  return next;
}

function getFlowData() {
  const nodes = {};
  for (const [id, n] of Object.entries(flowNodes)) {
    const params = normalizeNodeParams(n.type, n.params || {});
    n.params = params;
    nodes[id] = {
      id, node_type: n.type, label: getCanonicalNodeLabel(n.type),
      params,
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
  // Clear canvas first to prevent accumulation
  flowNodes = {};
  flowEdges = [];
  document.getElementById('flowNodes').innerHTML = '';
  document.getElementById('flowSvg')?.querySelectorAll('path:not(#connectingLine)').forEach(p => p.remove());
  nodeIdCounter = 0;
  connectingFrom = null;
  connectingMousePos = null;
  if (typeof syncFlowWorkspaceToFlowData === 'function') {
    syncFlowWorkspaceToFlowData(data);
  }
  if (typeof resetFlowZoom === 'function') {
    resetFlowZoom();
  }

  if (data && data.nodes) {
    for (const [id, nd] of Object.entries(data.nodes)) {
      const params = normalizeNodeParams(nd.node_type, nd.params || {});
      const displayLabel = getNodeDisplayName(nd.node_type, nd.label || id, params, true);
      if (!params.display_name && displayLabel !== getCanonicalNodeLabel(nd.node_type)) {
        params.display_name = displayLabel;
      }
      const n = createNodeEl(nd.node_type, displayLabel, params);
      n.id = 'node_' + id;
      const isFixed = nd.node_type === 'start' || nd.node_type === 'end';
      if (nd.node_type === 'start') {
        document.getElementById('flowNodes').appendChild(n);
        placeNodeAtAvailablePosition(n, Number(nd.x ?? 16), Number(nd.y ?? 16));
      } else if (nd.node_type === 'end') {
        const visible = getVisibleCanvasSize();
        document.getElementById('flowNodes').appendChild(n);
        placeNodeAtAvailablePosition(n, Number(nd.x ?? (visible.width - 156)), Number(nd.y ?? (visible.height - 76)));
      } else {
        document.getElementById('flowNodes').appendChild(n);
        placeNodeAtAvailablePosition(n, Number(nd.x ?? 100), Number(nd.y ?? 100));
      }
      flowNodes[id] = { el: n, type: nd.node_type, label: getCanonicalNodeLabel(nd.node_type), params, fixed: isFixed };
      if (isFixed) n.setAttribute('data-fixed', 'true');
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
  // initFixedNodes() 不在此调用 — loadFlowData() 已正确设置 START/END 的 fixed 属性和 DOM
  clampAllFlowNodes();
  requestAnimationFrame(() => clampAllFlowNodes());
  saveHistory();
  updateSvg();
  debugState(false);
}

// ============================================================================
// debugState — runtime self-check
// ============================================================================

function debugState(verbose = false) {
  const issues = [];
  // 1. DOM node count vs flowNodes object entries
  const domNodes = document.querySelectorAll('#flowNodes .flow-node').length;
  const objNodes = Object.keys(flowNodes).length;
  if (domNodes !== objNodes) issues.push(`节点数不一致: DOM=${domNodes} obj=${objNodes}`);
  // 2. No duplicate IDs
  const ids = new Set();
  for (const el of document.querySelectorAll('#flowNodes .flow-node')) {
    if (ids.has(el.id)) issues.push(`重复DOM ID: ${el.id}`);
    ids.add(el.id);
  }
  // 3. START/END always fixed:true
  for (const [id, n] of Object.entries(flowNodes)) {
    if ((n.type === 'start' || n.type === 'end') && !n.fixed) {
      issues.push(`START/END 节点 ${id} fixed=false`);
    }
  }
  // 4. All edge source/target point to valid nodes
  for (const edge of flowEdges) {
    if (!flowNodes[edge.source]) issues.push(`边 ${edge.id} source=${edge.source} 不存在`);
    if (!flowNodes[edge.target]) issues.push(`边 ${edge.id} target=${edge.target} 不存在`);
  }
  if (issues.length > 0) {
    console.error('🔴 debugState 发现异常:', issues);
    if (verbose && typeof toast === 'function') toast('状态异常: ' + issues.join('; '), 'warn');
  }
  return issues;
}
