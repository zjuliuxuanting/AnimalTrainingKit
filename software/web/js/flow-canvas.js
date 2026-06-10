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
      dot.style.cssText = `display:inline-block;width:16px;height:16px;background:${color};border:2px solid white;border-radius:50%;flex-shrink:0`;
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

function getCanvasSize() {
  const canvas = document.getElementById('flowCanvas');
  const rect = canvas?.getBoundingClientRect();
  return {
    width: rect?.width || 800,
    height: rect?.height || 500,
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

function clampAllFlowNodes() {
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

function makeDraggable(el, id) {
  let offsetX, offsetY;
  el.addEventListener('mousedown', (e) => {
    if (e.target.closest('.node-port-out, .node-port-in, .node-port-row')) return;
    if (flowNodes[id] && flowNodes[id].fixed) return;
    offsetX = e.offsetX;
    offsetY = e.offsetY;
    dragState = { el, id, offsetX, offsetY };
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
    const sy = parseInt(srcNode.el.style.top) + 30;
    const tx = parseInt(tgtNode.el.style.left);
    const ty = parseInt(tgtNode.el.style.top) + 30;

    const midX = (sx + tx) / 2;
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', `M${sx},${sy} C${midX},${sy} ${midX},${ty} ${tx},${ty}`);
    let edgeColor = '#90A4AE';
    let edgeWidth = '2';
    if (edge.sourcePort === 'true') { edgeColor = '#4CAF50'; edgeWidth = '2.5'; }
    else if (edge.sourcePort === 'false') { edgeColor = '#F44336'; edgeWidth = '2.5'; }
    else if (edge.sourcePort === 'body') { edgeColor = '#7C4DFF'; edgeWidth = '2.5'; }
    else if (edge.sourcePort === 'exit') { edgeColor = '#FF9800'; edgeWidth = '2.5'; }
    else if (edge.sourcePort === 'continue') { edgeColor = '#2196F3'; edgeWidth = '2.5'; }
    else if (edge.sourcePort === 'stop') { edgeColor = '#FF5722'; edgeWidth = '2.5'; }
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
  const tx = connectingMousePos.x - rect.left;
  const ty = connectingMousePos.y - rect.top;
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

  // START node — fixed top-left (0 inputs, 1 output)
  if (!hasStart && !flowNodes['start_0']) {
    const startEl = createNodeEl('start', '开始', {});
    startEl.id = 'node_start_0';
    startEl.setAttribute('data-fixed', 'true');
    startEl.style.opacity = '0.85';
    flowNodes['start_0'] = { el: startEl, type: 'start', label: '开始', params: {}, fixed: true };
    document.getElementById('flowNodes').appendChild(startEl);
    placeNodeWithinCanvas(startEl, 16, 16);
  }

  // END node — fixed bottom-right (>=1 inputs, 0 outputs)
  if (!hasEnd && !flowNodes['end_0']) {
    const endEl = createNodeEl('end', '结束', {});
    endEl.id = 'node_end_0';
    endEl.setAttribute('data-fixed', 'true');
    endEl.style.opacity = '0.85';
    flowNodes['end_0'] = { el: endEl, type: 'end', label: '结束', params: {}, fixed: true };
    document.getElementById('flowNodes').appendChild(endEl);
    placeNodeWithinCanvas(endEl, canvasW - 156, canvasH - 76);
  }

  // Defense: force-correct fixed status on any START/END that arrived with fixed=false
  for (const [id, n] of Object.entries(flowNodes)) {
    if ((n.type === 'start' || n.type === 'end') && !n.fixed) {
      n.fixed = true;
      n.el.setAttribute('data-fixed', 'true');
    }
  }
}
