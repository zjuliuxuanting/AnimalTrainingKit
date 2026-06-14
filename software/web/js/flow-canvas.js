/**
 * Flow Canvas — Rendering layer for the flow editor.
 *
 * Contains: createNodeEl, initFixedNodes, updateSvg, updateConnectingLine,
 * makeDraggable, wouldCreateCycle, and port HTML generation.
 * Depends on: flow-model.js (NODE_SCHEMAS, flowNodes, flowEdges, etc.)
 */

// ============================================================================
// Color helper
// ============================================================================

function _headerTextColor(bgColor) {
  const hex = bgColor.replace('#', '');
  let r = 0, g = 0, b = 0;
  if (hex.length === 3) {
    r = parseInt(hex[0] + hex[0], 16);
    g = parseInt(hex[1] + hex[1], 16);
    b = parseInt(hex[2] + hex[2], 16);
  } else if (hex.length === 6) {
    r = parseInt(hex.substring(0, 2), 16);
    g = parseInt(hex.substring(2, 4), 16);
    b = parseInt(hex.substring(4, 6), 16);
  }
  const lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return lum > 0.55 ? '#1a1a2e' : 'white';
}

// ============================================================================
// Port position helper
// ============================================================================

function _getPortY(nodeEl, portId, isOutput) {
  const nodeTop = parseInt(nodeEl.style.top) || 0;
  const nodeHeight = nodeEl.offsetHeight || 60;

  if (isOutput) {
    // Find specific port row by data-port (Blockly-style dual-output nodes)
    const portRow = nodeEl.querySelector(`.node-port-row[data-port="${portId}"]`);
    if (portRow && portRow.offsetHeight > 0) {
      return nodeTop + portRow.offsetTop + portRow.offsetHeight / 2;
    }
    // Single output port at 50%
    return nodeTop + nodeHeight / 2;
  }
  // Input port at 50%
  return nodeTop + nodeHeight / 2;
}

// ============================================================================
// Node Element Creation — Schema-driven ports
// ============================================================================

// Port label mapping: port_id → Chinese display label
const PORT_LABELS = {
  'body': '循环体',
  'exit': '退出',
  'true': '真',
  'false': '假',
  'continue': '继续',
  'stop': '记录终止',
};

// Port color mapping: port_id → edge color (matches updateSvg)
const PORT_COLORS = {
  'true': '#4CAF50',
  'false': '#F44336',
  'body': '#7C4DFF',
  'exit': '#FF9800',
  'continue': '#2196F3',
  'stop': '#FF5722',
};

function createNodeEl(type, label, params) {
  const schema = NODE_SCHEMAS[type];
  if (!schema) {
    const div = document.createElement('div');
    div.className = 'flow-node';
    div.innerHTML = `<div class="node-header"><span>?</span> ${label || type}</div><div class="node-body">${type}</div>`;
    div.style.position = 'absolute';
    div.style.width = '140px';
    div.style.cursor = 'move';
    div.style.background = 'white';
    div.style.borderRadius = '8px';
    div.style.boxShadow = '0 2px 8px rgba(0,0,0,0.12)';
    div.style.overflow = 'visible';
    div.style.border = '2px solid transparent';
    div.style.zIndex = '10';
    return div;
  }

  const color = schema.color;
  const textColor = _headerTextColor(color);
  const icons = {
    start: '🔴', end: '⏹', trigger: '⚡', delay: '⏱',
    condition: '🔀', execute: '🛠', loop: '🔄',
    and: '📦', not: '❑', fork: '🔁',
    record: '📝', record_end: '⏹', sniffer: '👁',
  };

  // Build port HTML based on schema port spec
  let portsHtml = '';

  // Input ports
  const inputCount = schema.ports.inputs;
  if (inputCount > 0) {
    portsHtml += `<div class="node-port node-port-in" data-node="${type}_in"></div>`;
  } else if (inputCount === -1) {
    for (let i = 0; i < 3; i++) {
      const topOffset = (i - 1) * 30;
      portsHtml += `<div class="node-port node-port-in" data-node="${type}_in" style="top:${50 + topOffset}%"></div>`;
    }
  }

  // Output ports
  const outputCount = schema.ports.outputs;
  const outputLabels = schema.ports.outputLabels || [];
  const outputPorts = schema.ports.outputPorts || [];

  if (outputCount === 2 && outputPorts.length === 2) {
    // Blockly-style: each output port gets its own row
    for (let i = 0; i < 2; i++) {
      const portId = outputPorts[i];
      const portLabel = PORT_LABELS[portId] || outputLabels[i] || portId;
      portsHtml += `<div class="node-port-row node-port-out" data-port="${portId}" title="${portLabel}">
        <span class="port-row-label">${portLabel}</span>
        <span class="port-row-dot"></span>
      </div>`;
    }
  } else if (outputCount > 0) {
    // Single output
    portsHtml += `<div class="node-port node-port-out single" data-port="out"></div>`;
  }

  const iconChar = icons[type] || '●';
  const safeLabel = escapeHtml(label || schema.label);
  const div = document.createElement('div');
  div.className = 'flow-node';
  div.innerHTML = `<div class="node-header" style="background:${color}"><span>${iconChar}</span> ${safeLabel}</div>
    <div class="node-body">${type}</div>${portsHtml}`;

  // Apply styles
  div.style.position = 'absolute';
  div.style.width = '140px';
  div.style.cursor = 'move';
  div.style.background = 'white';
  div.style.borderRadius = '8px';
  div.style.boxShadow = '0 2px 8px rgba(0,0,0,0.12)';
  div.style.overflow = 'visible';
  div.style.border = '2px solid transparent';
  div.style.zIndex = '10';

  // Header text color
  div.querySelector('.node-header').style.cssText = `padding:6px 10px;background:${color};color:${textColor};font-size:12px;font-weight:600`;
  div.querySelector('.node-body').style.cssText = `padding:8px 10px;font-size:11px;color:#666`;

  // Style input port
  const inPort = div.querySelector('.node-port-in');
  if (inPort) {
    inPort.style.cssText = `position:absolute;left:-6px;top:50%;width:16px;height:16px;background:${color};border:2px solid white;border-radius:50%;cursor:crosshair;transform:translateY(-8px)`;
    inPort.title = '点击此处拖出连线';
  }

  // Style output ports — Blockly-style rows for dual-output nodes
  const outPortRows = div.querySelectorAll('.node-port-row');
  outPortRows.forEach(pt => {
    pt.style.cssText = `display:flex;align-items:center;justify-content:space-between;padding:4px 8px;margin:2px 4px;background:${color}18;border:1px solid ${color}40;border-radius:6px;cursor:crosshair;font-size:11px;transition:background 0.15s`;
    pt.addEventListener('mouseenter', () => { pt.style.background = color + '30'; });
    pt.addEventListener('mouseleave', () => { if (!connectingFrom) pt.style.background = color + '18'; });
    const dot = pt.querySelector('.port-row-dot');
    if (dot) {
      const dotColor = PORT_COLORS[pt.dataset.port] || color;
      dot.style.cssText = `display:inline-block;width:16px;height:16px;background:${dotColor};border:2px solid white;border-radius:50%;flex-shrink:0`;
    }
  });

  // Style single output port
  const singleOut = div.querySelector('.node-port-out.single');
  if (singleOut) {
    singleOut.style.cssText = `position:absolute;top:50%;right:-8px;width:16px;height:16px;background:${color};border:2px solid white;border-radius:50%;cursor:crosshair;transform:translateY(-8px)`;
    singleOut.title = '点击此处拖出连线';
  }

  // Hover: highlight connection points
  const allOutPorts = div.querySelectorAll('.node-port-out');
  div.addEventListener('mouseenter', () => {
    allOutPorts.forEach(p => {
      if (p.classList.contains('single')) {
        p.style.transform = 'translateY(-8px) scale(1.3)';
      } else {
        p.style.background = color + '30';
      }
    });
    if (inPort) inPort.style.transform = 'translateY(-8px) scale(1.3)';
  });
  div.addEventListener('mouseleave', () => {
    if (connectingFrom) return;
    allOutPorts.forEach(p => {
      if (p.classList.contains('single')) {
        p.style.transform = 'translateY(-8px) scale(1)';
      }
    });
    if (inPort) inPort.style.transform = 'translateY(-8px) scale(1)';
  });

  div.addEventListener('dblclick', () => selectNode(getNodeId(div)));
  return div;
}

// ============================================================================
// Draggable nodes
// ============================================================================

const FLOW_NODE_WIDTH = 140;
const FLOW_NODE_MIN_HEIGHT = 60;
const FLOW_NODE_MARGIN = 8;
const FLOW_NODE_GAP = 16;
const FLOW_WORKSPACE_MIN_WIDTH = 2200;
const FLOW_WORKSPACE_MIN_HEIGHT = 760;
const FLOW_VIEWPORT_MIN_SCALE = 0.35;
const FLOW_VIEWPORT_MAX_SCALE = 1;
const FLOW_VIEWPORT_PADDING = 32;

let flowViewportScale = 1;
let flowViewportMode = '100';
let currentRuntimeNodeId = null;

function _finiteNumber(value, fallback) {
  const num = Number.parseFloat(value);
  return Number.isFinite(num) ? num : fallback;
}

function getVisibleCanvasSize() {
  const canvas = document.getElementById('flowCanvas');
  const rect = canvas?.getBoundingClientRect();
  return {
    width: rect?.width || 800,
    height: rect?.height || 500,
  };
}

function getFlowWorkspace() {
  return document.getElementById('flowWorkspace') || document.getElementById('flowCanvas');
}

function getFlowWorkspaceBaseSize() {
  const canvas = document.getElementById('flowCanvas');
  const workspace = getFlowWorkspace();
  const inlineWidth = _finiteNumber(workspace?.style?.width, FLOW_WORKSPACE_MIN_WIDTH);
  const inlineHeight = _finiteNumber(workspace?.style?.height, FLOW_WORKSPACE_MIN_HEIGHT);
  const baseWidth = _finiteNumber(workspace?.dataset?.baseWidth, inlineWidth);
  const baseHeight = _finiteNumber(workspace?.dataset?.baseHeight, inlineHeight);
  return {
    width: Math.max(FLOW_WORKSPACE_MIN_WIDTH, baseWidth, (canvas?.clientWidth || 0) / flowViewportScale),
    height: Math.max(FLOW_WORKSPACE_MIN_HEIGHT, baseHeight, (canvas?.clientHeight || 0) / flowViewportScale),
  };
}

function _clampScrollValue(value, max) {
  return Math.max(0, Math.min(Math.max(0, max), Number.isFinite(value) ? value : 0));
}

function applyFlowViewportTransform() {
  const workspace = getFlowWorkspace();
  if (!workspace) return;
  const base = getFlowWorkspaceBaseSize();
  workspace.dataset.baseWidth = String(Math.round(base.width));
  workspace.dataset.baseHeight = String(Math.round(base.height));
  workspace.style.width = Math.round(base.width * flowViewportScale) + 'px';
  workspace.style.height = Math.round(base.height * flowViewportScale) + 'px';

  ['flowSvg', 'flowNodes'].forEach((id) => {
    const layer = document.getElementById(id);
    if (!layer) return;
    layer.style.width = Math.round(base.width) + 'px';
    layer.style.height = Math.round(base.height) + 'px';
    layer.style.transformOrigin = '0 0';
    layer.style.transform = `scale(${flowViewportScale})`;
  });
  window.__flowViewportScale = flowViewportScale;
}

function updateFlowViewportBadge() {
  const badge = document.getElementById('flowZoomBadge');
  if (!badge) return;
  const pct = Math.round(flowViewportScale * 100);
  badge.textContent = flowViewportMode === 'fit' ? `Fit ${pct}%` : `${pct}%`;
}

function initializeFlowViewport() {
  const workspace = getFlowWorkspace();
  if (!workspace) return;
  if (!workspace.dataset.baseWidth) {
    workspace.dataset.baseWidth = String(_finiteNumber(workspace.style.width, FLOW_WORKSPACE_MIN_WIDTH));
  }
  if (!workspace.dataset.baseHeight) {
    workspace.dataset.baseHeight = String(_finiteNumber(workspace.style.height, FLOW_WORKSPACE_MIN_HEIGHT));
  }
  applyFlowViewportTransform();
  updateFlowViewportBadge();
}

function refreshFlowViewport() {
  initializeFlowViewport();
  if (flowViewportMode === 'fit') {
    fitFlowToView();
    return;
  }
  applyFlowViewportTransform();
  updateFlowViewportBadge();
  updateSvg();
}

function setFlowWorkspaceBaseSize(width, height, options = {}) {
  const workspace = getFlowWorkspace();
  if (!workspace) return;
  const canvas = document.getElementById('flowCanvas');
  const oldScale = flowViewportScale || 1;
  const center = canvas && options.preserveCenter ? {
    x: (canvas.scrollLeft + canvas.clientWidth / 2) / oldScale,
    y: (canvas.scrollTop + canvas.clientHeight / 2) / oldScale,
  } : null;

  workspace.dataset.baseWidth = String(Math.max(FLOW_WORKSPACE_MIN_WIDTH, Math.ceil(width)));
  workspace.dataset.baseHeight = String(Math.max(FLOW_WORKSPACE_MIN_HEIGHT, Math.ceil(height)));
  applyFlowViewportTransform();

  if (canvas && center) {
    canvas.scrollLeft = _clampScrollValue(center.x * flowViewportScale - canvas.clientWidth / 2, canvas.scrollWidth - canvas.clientWidth);
    canvas.scrollTop = _clampScrollValue(center.y * flowViewportScale - canvas.clientHeight / 2, canvas.scrollHeight - canvas.clientHeight);
  }
}

function getCanvasSize() {
  const canvas = document.getElementById('flowCanvas');
  const base = getFlowWorkspaceBaseSize();
  return {
    width: Math.max(FLOW_WORKSPACE_MIN_WIDTH, base.width, (canvas?.clientWidth || 0) / flowViewportScale, 800),
    height: Math.max(FLOW_WORKSPACE_MIN_HEIGHT, base.height, (canvas?.clientHeight || 0) / flowViewportScale, 500),
  };
}

function clampNodePosition(x, y, el = null) {
  const size = getCanvasSize();
  const nodeWidth = Math.max(FLOW_NODE_WIDTH, el?.offsetWidth || 0);
  const nodeHeight = Math.max(FLOW_NODE_MIN_HEIGHT, el?.offsetHeight || 0);
  const maxX = Math.max(FLOW_NODE_MARGIN, size.width - nodeWidth - FLOW_NODE_MARGIN);
  const maxY = Math.max(FLOW_NODE_MARGIN, size.height - nodeHeight - FLOW_NODE_MARGIN);
  return {
    x: Math.max(FLOW_NODE_MARGIN, Math.min(maxX, Number.isFinite(x) ? x : FLOW_NODE_MARGIN)),
    y: Math.max(FLOW_NODE_MARGIN, Math.min(maxY, Number.isFinite(y) ? y : FLOW_NODE_MARGIN)),
  };
}

function placeNodeWithinCanvas(el, x, y) {
  const pos = clampNodePosition(Number(x), Number(y), el);
  el.style.left = pos.x + 'px';
  el.style.top = pos.y + 'px';
  return pos;
}

function getNodeRectAt(el, x, y) {
  return {
    left: x,
    top: y,
    right: x + Math.max(FLOW_NODE_WIDTH, el?.offsetWidth || 0),
    bottom: y + Math.max(FLOW_NODE_MIN_HEIGHT, el?.offsetHeight || 0),
  };
}

function rectsOverlap(a, b, gap = FLOW_NODE_GAP) {
  return !(
    a.right + gap <= b.left ||
    a.left >= b.right + gap ||
    a.bottom + gap <= b.top ||
    a.top >= b.bottom + gap
  );
}

function isNodePositionFree(el, pos) {
  const candidate = getNodeRectAt(el, pos.x, pos.y);
  return Array.from(document.querySelectorAll('#flowNodes .flow-node')).every(other => {
    if (other === el) return true;
    const otherX = Number.parseFloat(other.style.left || '0');
    const otherY = Number.parseFloat(other.style.top || '0');
    return !rectsOverlap(candidate, getNodeRectAt(other, otherX, otherY));
  });
}

function findAvailableNodePosition(el, x, y) {
  const preferred = clampNodePosition(Number(x), Number(y), el);
  if (isNodePositionFree(el, preferred)) return preferred;

  const size = getCanvasSize();
  const stepX = FLOW_NODE_WIDTH + FLOW_NODE_GAP;
  const stepY = FLOW_NODE_MIN_HEIGHT + 24;
  const nodeWidth = Math.max(FLOW_NODE_WIDTH, el?.offsetWidth || 0);
  const nodeHeight = Math.max(FLOW_NODE_MIN_HEIGHT, el?.offsetHeight || 0);
  const maxX = Math.max(FLOW_NODE_MARGIN, size.width - nodeWidth - FLOW_NODE_MARGIN);
  const maxY = Math.max(FLOW_NODE_MARGIN, size.height - nodeHeight - FLOW_NODE_MARGIN);

  for (let yy = FLOW_NODE_MARGIN; yy <= maxY; yy += stepY) {
    for (let xx = FLOW_NODE_MARGIN; xx <= maxX; xx += stepX) {
      const pos = clampNodePosition(xx, yy, el);
      if (isNodePositionFree(el, pos)) return pos;
    }
  }

  setFlowWorkspaceBaseSize(size.width, size.height + stepY * 8, { preserveCenter: true });
  const expanded = getCanvasSize();
  const expandedMaxY = Math.max(FLOW_NODE_MARGIN, expanded.height - nodeHeight - FLOW_NODE_MARGIN);
  for (let yy = maxY + stepY; yy <= expandedMaxY; yy += stepY) {
    for (let xx = FLOW_NODE_MARGIN; xx <= maxX; xx += stepX) {
      const pos = clampNodePosition(xx, yy, el);
      if (isNodePositionFree(el, pos)) return pos;
    }
  }
  return preferred;
}

function placeNodeAtAvailablePosition(el, x, y) {
  const pos = findAvailableNodePosition(el, x, y);
  el.style.left = pos.x + 'px';
  el.style.top = pos.y + 'px';
  return pos;
}

function clampAllFlowNodes() {
  expandFlowWorkspaceToFitNodes();
  for (const node of Object.values(flowNodes)) {
    if (!node?.el) continue;
    placeNodeWithinCanvas(
      node.el,
      Number.parseFloat(node.el.style.left || '0'),
      Number.parseFloat(node.el.style.top || '0')
    );
  }
  updateSvg();
}

function getFlowViewportScale() {
  return flowViewportScale || 1;
}

function getFlowViewportState() {
  return {
    scale: Number((flowViewportScale || 1).toFixed(3)),
    mode: flowViewportMode,
  };
}

function setFlowViewportScale(scale, mode = 'manual', options = {}) {
  const canvas = document.getElementById('flowCanvas');
  initializeFlowViewport();
  const oldScale = flowViewportScale || 1;
  const center = canvas && options.preserveCenter !== false ? {
    x: (canvas.scrollLeft + canvas.clientWidth / 2) / oldScale,
    y: (canvas.scrollTop + canvas.clientHeight / 2) / oldScale,
  } : null;

  flowViewportScale = Math.max(FLOW_VIEWPORT_MIN_SCALE, Math.min(FLOW_VIEWPORT_MAX_SCALE, scale));
  flowViewportMode = mode;
  applyFlowViewportTransform();

  if (canvas && center) {
    canvas.scrollLeft = _clampScrollValue(center.x * flowViewportScale - canvas.clientWidth / 2, canvas.scrollWidth - canvas.clientWidth);
    canvas.scrollTop = _clampScrollValue(center.y * flowViewportScale - canvas.clientHeight / 2, canvas.scrollHeight - canvas.clientHeight);
  }
  updateFlowViewportBadge();
  updateSvg();
}

function getFlowNodeBounds() {
  const nodes = Object.values(flowNodes).filter(n => n?.el);
  if (nodes.length === 0) {
    const base = getFlowWorkspaceBaseSize();
    return { left: 0, top: 0, right: base.width, bottom: base.height, width: base.width, height: base.height };
  }
  let left = Infinity;
  let top = Infinity;
  let right = -Infinity;
  let bottom = -Infinity;
  for (const n of nodes) {
    const x = _finiteNumber(n.el.style.left, 0);
    const y = _finiteNumber(n.el.style.top, 0);
    left = Math.min(left, x);
    top = Math.min(top, y);
    right = Math.max(right, x + Math.max(FLOW_NODE_WIDTH, n.el.offsetWidth || 0));
    bottom = Math.max(bottom, y + Math.max(FLOW_NODE_MIN_HEIGHT, n.el.offsetHeight || 0));
  }
  return { left, top, right, bottom, width: right - left, height: bottom - top };
}

function expandFlowWorkspaceToFitNodes(padding = 180) {
  const bounds = getFlowNodeBounds();
  const base = getFlowWorkspaceBaseSize();
  const width = Math.max(base.width, bounds.right + padding, FLOW_WORKSPACE_MIN_WIDTH);
  const height = Math.max(base.height, bounds.bottom + padding, FLOW_WORKSPACE_MIN_HEIGHT);
  setFlowWorkspaceBaseSize(width, height, { preserveCenter: true });
}

function syncFlowWorkspaceToFlowData(data) {
  const nodes = Object.values(data?.nodes || {});
  if (nodes.length === 0) {
    setFlowWorkspaceBaseSize(FLOW_WORKSPACE_MIN_WIDTH, FLOW_WORKSPACE_MIN_HEIGHT);
    return;
  }
  let right = FLOW_WORKSPACE_MIN_WIDTH;
  let bottom = FLOW_WORKSPACE_MIN_HEIGHT;
  nodes.forEach((n) => {
    right = Math.max(right, _finiteNumber(n.x, 0) + FLOW_NODE_WIDTH + 220);
    bottom = Math.max(bottom, _finiteNumber(n.y, 0) + FLOW_NODE_MIN_HEIGHT + 180);
  });
  setFlowWorkspaceBaseSize(right, bottom);
}

function fitFlowToView() {
  const canvas = document.getElementById('flowCanvas');
  if (!canvas) return;
  expandFlowWorkspaceToFitNodes();
  const bounds = getFlowNodeBounds();
  const availableW = Math.max(1, canvas.clientWidth - FLOW_VIEWPORT_PADDING * 2);
  const availableH = Math.max(1, canvas.clientHeight - FLOW_VIEWPORT_PADDING * 2);
  const scale = Math.min(
    FLOW_VIEWPORT_MAX_SCALE,
    Math.max(
      FLOW_VIEWPORT_MIN_SCALE,
      Math.min(availableW / Math.max(1, bounds.width), availableH / Math.max(1, bounds.height))
    )
  );
  setFlowViewportScale(scale, 'fit', { preserveCenter: false });
  canvas.scrollLeft = _clampScrollValue(bounds.left * scale - FLOW_VIEWPORT_PADDING, canvas.scrollWidth - canvas.clientWidth);
  canvas.scrollTop = _clampScrollValue(bounds.top * scale - FLOW_VIEWPORT_PADDING, canvas.scrollHeight - canvas.clientHeight);
}

function resetFlowZoom() {
  const targetId = selectedNodeId || currentRuntimeNodeId;
  const wasFit = flowViewportMode === 'fit';
  setFlowViewportScale(1, '100', { preserveCenter: !wasFit });
  if (targetId && flowNodes[targetId]) {
    ensureFlowNodeVisible(targetId, { center: wasFit });
  }
}

function setFlowZoom75() {
  setFlowViewportScale(0.75, '75');
}

function ensureFlowNodeVisible(id, options = {}) {
  const node = flowNodes[id];
  const canvas = document.getElementById('flowCanvas');
  if (!node?.el || !canvas) return false;
  initializeFlowViewport();

  const scale = getFlowViewportScale();
  const margin = options.margin ?? 18;
  const nodeLeft = _finiteNumber(node.el.style.left, 0) * scale;
  const nodeTop = _finiteNumber(node.el.style.top, 0) * scale;
  const nodeWidth = Math.max(FLOW_NODE_WIDTH, node.el.offsetWidth || 0) * scale;
  const nodeHeight = Math.max(FLOW_NODE_MIN_HEIGHT, node.el.offsetHeight || 0) * scale;
  const nodeRight = nodeLeft + nodeWidth;
  const nodeBottom = nodeTop + nodeHeight;
  let targetLeft = canvas.scrollLeft;
  let targetTop = canvas.scrollTop;

  if (options.center) {
    targetLeft = nodeLeft - (canvas.clientWidth - nodeWidth) / 2;
    targetTop = nodeTop - (canvas.clientHeight - nodeHeight) / 2;
  } else {
    if (nodeLeft < canvas.scrollLeft + margin) {
      targetLeft = nodeLeft - margin;
    } else if (nodeRight > canvas.scrollLeft + canvas.clientWidth - margin) {
      targetLeft = nodeRight - canvas.clientWidth + margin;
    }
    if (nodeTop < canvas.scrollTop + margin) {
      targetTop = nodeTop - margin;
    } else if (nodeBottom > canvas.scrollTop + canvas.clientHeight - margin) {
      targetTop = nodeBottom - canvas.clientHeight + margin;
    }
  }

  canvas.scrollTo({
    left: _clampScrollValue(targetLeft, canvas.scrollWidth - canvas.clientWidth),
    top: _clampScrollValue(targetTop, canvas.scrollHeight - canvas.clientHeight),
    behavior: options.behavior || 'auto',
  });
  return true;
}

function locateSelectedFlowNode() {
  const id = selectedNodeId || currentRuntimeNodeId;
  if (!id || !flowNodes[id]) {
    toast('请先选中一个节点', 'warn');
    return;
  }
  ensureFlowNodeVisible(id, { center: true });
}

function getSelectedFlowNodeId() {
  return selectedNodeId || null;
}

function markRuntimeNode(id, options = {}) {
  if (!id || !flowNodes[id]) return;
  document.querySelectorAll('#flowNodes .flow-node.flow-node-runtime').forEach(el => {
    el.classList.remove('flow-node-runtime');
  });
  currentRuntimeNodeId = id;
  flowNodes[id].el.classList.add('flow-node-runtime');
  if (options.scroll) ensureFlowNodeVisible(id, { center: true });
}

function canvasEventToLogicalPoint(e) {
  const canvas = document.getElementById('flowCanvas');
  const rect = canvas.getBoundingClientRect();
  const scale = getFlowViewportScale();
  return {
    x: (e.clientX - rect.left + canvas.scrollLeft) / scale,
    y: (e.clientY - rect.top + canvas.scrollTop) / scale,
  };
}

function autoLayoutFlow() {
  const ids = Object.keys(flowNodes);
  if (ids.length === 0) return;
  initializeFlowViewport();

  const startIds = ids.filter(id => flowNodes[id].type === 'start');
  const endIds = ids.filter(id => flowNodes[id].type === 'end');
  const adjacency = {};
  const incoming = {};
  ids.forEach((id) => {
    adjacency[id] = [];
    incoming[id] = 0;
  });
  flowEdges.forEach((edge) => {
    if (!flowNodes[edge.source] || !flowNodes[edge.target]) return;
    adjacency[edge.source].push(edge);
    incoming[edge.target] = (incoming[edge.target] || 0) + 1;
  });

  const layer = {};
  const roots = startIds.length > 0 ? startIds : ids.filter(id => (incoming[id] || 0) === 0);
  roots.forEach(id => { layer[id] = 0; });
  const queue = [...roots];
  let guard = 0;
  while (queue.length > 0 && guard < ids.length * ids.length * 2) {
    guard += 1;
    const source = queue.shift();
    const sourceLayer = layer[source] ?? 0;
    for (const edge of adjacency[source] || []) {
      // Skip body edge if target already at same or lower layer (loop convergence)
      if (edge.sourcePort === 'body' && layer[edge.target] !== undefined && layer[edge.target] <= sourceLayer) continue;
      // Skip back edges to already-layered loop nodes (prevent loop node from being pushed right)
      if (flowNodes[edge.target]?.type === 'loop' && layer[edge.target] !== undefined) continue;
      const nextLayer = Math.min(sourceLayer + 1, ids.length + 1);
      if (layer[edge.target] === undefined || nextLayer > layer[edge.target]) {
        layer[edge.target] = nextLayer;
        queue.push(edge.target);
      }
    }
  }

  let maxLayer = Math.max(0, ...Object.values(layer));
  ids.forEach((id) => {
    if (layer[id] === undefined) {
      maxLayer += 1;
      layer[id] = maxLayer;
    }
  });
  const lastNonEndLayer = Math.max(0, ...ids.filter(id => !endIds.includes(id)).map(id => layer[id]));
  endIds.forEach(id => { layer[id] = lastNonEndLayer + 1; });
  startIds.forEach(id => { layer[id] = 0; });
  maxLayer = Math.max(...ids.map(id => layer[id]));

  const groups = {};
  ids.forEach((id) => {
    const l = layer[id] || 0;
    if (!groups[l]) groups[l] = [];
    groups[l].push(id);
  });
  Object.values(groups).forEach(group => group.sort((a, b) => {
    const ay = _finiteNumber(flowNodes[a].el.style.top, 0);
    const by = _finiteNumber(flowNodes[b].el.style.top, 0);
    if (flowNodes[a].type === 'start') return -1;
    if (flowNodes[b].type === 'start') return 1;
    if (flowNodes[a].type === 'end') return 1;
    if (flowNodes[b].type === 'end') return -1;
    return ay - by || (flowNodes[a].label || a).localeCompare(flowNodes[b].label || b, 'zh-Hans-CN');
  }));

  const xStart = 32;
  const yStart = 56;
  const xGap = 190;
  const yGap = 118;
  let requiredHeight = FLOW_WORKSPACE_MIN_HEIGHT;
  Object.entries(groups).forEach(([level, group]) => {
    requiredHeight = Math.max(requiredHeight, yStart + group.length * yGap + 180);
  });
  const requiredWidth = xStart + (maxLayer + 1) * xGap + FLOW_NODE_WIDTH + 220;
  setFlowWorkspaceBaseSize(requiredWidth, requiredHeight);

  Object.entries(groups).forEach(([levelText, group]) => {
    const level = Number(levelText);
    group.forEach((id, index) => {
      const node = flowNodes[id];
      let x = xStart + level * xGap;
      let y = yStart + index * yGap;
      if (node.type === 'start') {
        x = xStart;
        y = yStart;
      } else if (node.type === 'end') {
        x = xStart + maxLayer * xGap;
        y = yStart;
      }
      placeNodeWithinCanvas(node.el, x, y);
    });
  });

  saveHistory();
  updateSvg();
  fitFlowToView();
  toast('流程已整理', 'success');
}

function makeDraggable(el, id) {
  let offsetX, offsetY;
  el.addEventListener('click', (e) => {
    if (e.target.closest('.node-port-out, .node-port-in, .node-port-row')) return;
    selectNode(id);
    e.stopPropagation();
  });
  el.addEventListener('mousedown', (e) => {
    if (e.target.closest('.node-port-out, .node-port-in, .node-port-row')) return;
    if (flowNodes[id] && flowNodes[id].fixed) return;
    const point = canvasEventToLogicalPoint(e);
    offsetX = point.x - _finiteNumber(el.style.left, 0);
    offsetY = point.y - _finiteNumber(el.style.top, 0);
    dragState = { el, id, offsetX, offsetY, wasOutOfBounds: false };
    el.style.zIndex = '20';
    el.style.boxShadow = '0 4px 16px rgba(0,0,0,0.2)';
    e.preventDefault();
  });
}

// ============================================================================
// Cycle detection
// ============================================================================

function wouldCreateCycle(sourceId, targetId) {
  const adjacency = {};
  for (const edge of flowEdges) {
    if (!adjacency[edge.source]) adjacency[edge.source] = [];
    adjacency[edge.source].push(edge.target);
  }

  const visited = new Set();
  const stack = [targetId];
  while (stack.length > 0) {
    const current = stack.pop();
    if (current === sourceId) return true;
    if (visited.has(current)) continue;
    visited.add(current);
    const neighbors = adjacency[current] || [];
    for (const next of neighbors) {
      if (!visited.has(next)) stack.push(next);
    }
  }
  return false;
}

// ============================================================================
// SVG rendering
// ============================================================================

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
    const sy = _getPortY(srcNode.el, edge.sourcePort, true);
    const tx = parseInt(tgtNode.el.style.left);
    const ty = _getPortY(tgtNode.el, edge.sourcePort, false);

    const midX = (sx + tx) / 2;
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', `M${sx},${sy} C${midX},${sy} ${midX},${ty} ${tx},${ty}`);
    const edgeColor = PORT_COLORS[edge.sourcePort] || '#90A4AE';
    const edgeWidth = PORT_COLORS[edge.sourcePort] ? '2.5' : '2';
    path.setAttribute('stroke', edgeColor);
    path.setAttribute('stroke-width', edgeWidth);
    path.setAttribute('fill', 'none');
    path.setAttribute('marker-end', 'url(#arrowhead)');
    path.setAttribute('pointer-events', 'stroke');
    path.style.cursor = 'pointer';
    if (edge.id === selectedEdgeId) {
      path.setAttribute('stroke', '#1976D2');
      path.setAttribute('stroke-width', '3');
    }
    path.setAttribute('data-edge-id', edge.id);
    // Bug-1: 直接在 path 上绑定右键删除，不依赖 document 冒泡（SVG target 可能不是 path 本身）
    path.addEventListener('contextmenu', (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      flowEdges = flowEdges.filter(ed => ed.id !== edge.id);
      if (selectedEdgeId === edge.id) selectedEdgeId = null;
      saveHistory();
      updateSvg();
    });
    svg.appendChild(path);
  }
}

// ============================================================================
// Connecting line (while dragging a connection)
// ============================================================================

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
  const canvas = document.getElementById('flowCanvas');
  const scale = getFlowViewportScale();
  const tx = (connectingMousePos.x - rect.left + (canvas?.scrollLeft || 0)) / scale;
  const ty = (connectingMousePos.y - rect.top + (canvas?.scrollTop || 0)) / scale;
  const midX = (sx + tx) / 2;
  line.setAttribute('d', `M${sx},${sy} C${midX},${sy} ${midX},${ty} ${tx},${ty}`);
}

// ============================================================================
// Fixed nodes (START/END)
// ============================================================================

function initFixedNodes() {
  const canvas = document.getElementById('flowCanvas');

  // Remove old fixed nodes from DOM first
  canvas.querySelectorAll('.flow-node[data-fixed="true"]').forEach(el => el.remove());

  // getBoundingClientRect returns 0 when flow tab is hidden (display:none)
  // Use canvas inline-style dimensions as fallback
  const rect = canvas.getBoundingClientRect();
  const canvasW = rect.width || 800;
  const canvasH = rect.height || 500;

  // Check if START/END already exist in flowNodes
  const hasStart = Object.values(flowNodes).some(n => n.type === 'start');
  const hasEnd = Object.values(flowNodes).some(n => n.type === 'end');

  // START node — top-left (0 inputs, 1 output). Bug-3: 不再标记 fixed，可拖可删
  if (!hasStart && !flowNodes['start_0']) {
    const startEl = createNodeEl('start', '开始', {});
    startEl.id = 'node_start_0';
    flowNodes['start_0'] = { el: startEl, type: 'start', label: '开始', params: {}, fixed: false };
    document.getElementById('flowNodes').appendChild(startEl);
    makeDraggable(startEl, 'start_0');
    placeNodeWithinCanvas(startEl, 16, 16);
  }

  // END node — bottom-right (>=1 inputs, 0 outputs). Bug-3: 不再标记 fixed，可拖可删
  if (!hasEnd && !flowNodes['end_0']) {
    const endEl = createNodeEl('end', '结束', {});
    endEl.id = 'node_end_0';
    flowNodes['end_0'] = { el: endEl, type: 'end', label: '结束', params: {}, fixed: false };
    document.getElementById('flowNodes').appendChild(endEl);
    makeDraggable(endEl, 'end_0');
    const visible = getVisibleCanvasSize();
    placeNodeWithinCanvas(endEl, visible.width - 156, visible.height - 76);
  }
}
