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
        key: 'duration_s',
        label: '等待时间',
        type: 'number',
        min: 0.1,
        max: 3600,
        step: 0.1,
        default: 1,
        unit: '秒',
        required: true,
      },
    ],
    help: '流程执行到此节点时暂停指定时长。默认 1 秒，范围 0.1 秒 ~ 1 小时。',
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
          { value: 'counter', label: '指定计数器' },
          { value: 'feeds_today', label: '今日已投喂次数' },
          { value: 'daily_quota_count', label: '每日投喂上限' },
          { value: 'quota_locked', label: '额度冷却锁定中' },
          { value: 'quota_available', label: '今日额度仍可用' },
          { value: 'quota_reached', label: '今日额度已达上限' },
          { value: 'cooldown_remaining_s', label: '剩余冷却秒数' },
          { value: 'day_index', label: '压缩日序号' },
        ],
        default: 'trigger_count',
        required: true,
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
        min: 0,
        max: 999999,
        default: 0,
        required: true,
      },
      {
        key: 'daily_quota_count',
        label: '每日投喂上限',
        type: 'number',
        min: 1,
        max: 10000,
        step: 1,
        default: 3,
        unit: '次/颗',
        required: false,
      },
    ],
    help: '根据上游数据做条件判断。source 可读取 TRIGGER 累计数、计数器或第5链路持久额度状态。',
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
        key: 'counter_name',
        label: '计数器名称',
        type: 'text',
        maxLength: 64,
        required: false,
      },
      {
        key: 'counter_op',
        label: '计数器操作',
        type: 'select',
        options: [
          { value: '+1', label: '+1（递增）' },
          { value: '=0', label: '=0（重置为零）' },
          { value: '=1', label: '=1（重置为一）' },
          { value: '-1', label: '-1（递减）' },
        ],
        default: '+1',
        required: false,
      },
      {
        key: 'state_op',
        label: '持久额度写入',
        type: 'select',
        options: [
          { value: '', label: '不写持久状态' },
          { value: 'feed_success', label: '投喂成功：feeds_today +1' },
          { value: 'start_cooldown', label: '开始冷却：锁定额度' },
          { value: 'new_day_reset', label: '新日重置：清零并解锁' },
        ],
        default: '',
        required: false,
      },
      {
        key: 'daily_quota_count',
        label: '每日投喂上限',
        type: 'number',
        min: 1,
        max: 10000,
        step: 1,
        default: 3,
        unit: '次/颗',
        required: false,
      },
      {
        key: 'cooldown_s',
        label: '冷却时长',
        type: 'number',
        min: 0.1,
        max: 86400,
        step: 0.1,
        default: 72000,
        unit: '秒',
        required: false,
      },
    ],
    help: '记录实验事件。可选做运行时计数器操作；第5链路可写入最小持久额度状态。',
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
const PALETTE_ORDER = ['trigger', 'delay', 'condition', 'execute', 'loop', 'and', 'not', 'fork', 'record', 'record_end', 'sniffer'];

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

  for (const [id, nd] of Object.entries(snapshot.nodes)) {
    const el = createNodeEl(nd.type, nd.label, nd.params);
    el.id = 'node_' + id;
    el.style.left = nd.left + 'px';
    el.style.top = nd.top + 'px';
    flowNodes[id] = { el, type: nd.type, label: nd.label, params: nd.params || {}, fixed: nd.fixed || false };
    if (!nd.fixed) makeDraggable(el, id);
    flowNodesDiv.appendChild(el);
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
  // Clear canvas first to prevent accumulation
  flowNodes = {};
  flowEdges = [];
  document.getElementById('flowNodes').innerHTML = '';
  document.getElementById('flowSvg')?.querySelectorAll('path:not(#connectingLine)').forEach(p => p.remove());
  nodeIdCounter = 0;
  connectingFrom = null;
  connectingMousePos = null;

  if (data && data.nodes) {
    for (const [id, nd] of Object.entries(data.nodes)) {
      const n = createNodeEl(nd.node_type, nd.label || id, nd.params);
      n.id = 'node_' + id;
      const isFixed = nd.node_type === 'start' || nd.node_type === 'end';
      if (nd.node_type === 'start') {
        n.style.left = '16px';
        n.style.top = '16px';
      } else if (nd.node_type === 'end') {
        const rect = document.getElementById('flowCanvas')?.getBoundingClientRect();
        const cw = rect?.width || 800;
        const ch = rect?.height || 500;
        n.style.left = (cw - 156) + 'px';
        n.style.top = (ch - 76) + 'px';
      } else {
        n.style.left = (nd.x || 100) + 'px';
        n.style.top = (nd.y || 100) + 'px';
      }
      flowNodes[id] = { el: n, type: nd.node_type, label: nd.label || id, params: nd.params || {}, fixed: isFixed };
      if (isFixed) n.setAttribute('data-fixed', 'true');
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
  // initFixedNodes() 不在此调用 — loadFlowData() 已正确设置 START/END 的 fixed 属性和 DOM
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
