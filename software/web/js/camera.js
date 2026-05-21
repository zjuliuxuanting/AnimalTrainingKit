let cameraStream = null;
let cameraStep = 0;
let bgImageData = null;
let contrast = 'dark';
let zones = [];
let zoneDrawMode = false;
let zoneDragStart = null;
let zoneDragCurrent = null;
let detectInterval = null;
let bgMethod = 'auto';
let bgFrames = [];
let bgFillBox = null;
let fillDragStart = null;
let currentExperimentId = null;
let currentExperimentName = '';

const ZONE_COLORS = ['#FF9800', '#4CAF50', '#2196F3', '#E91E63', '#9C27B0'];

let rulerPoints = [];
let rulerPixelsPerCm = null;

function toggleAdvancedParams() {
  const panel = document.getElementById('advancedParams');
  const btn = document.getElementById('btnToggleAdvanced');
  if (!panel || !btn) return;
  if (panel.style.display === 'none') {
    panel.style.display = 'block';
    btn.innerHTML = '⚙ 高级参数 ▾';
  } else {
    panel.style.display = 'none';
    btn.innerHTML = '⚙ 高级参数 ▸';
  }
}

function applyRuler() {
  if (rulerPoints.length < 2) { toast('请在画面上点击两个点', 'warn'); return; }
  const length = parseFloat(document.getElementById('camRulerLength').value);
  const unit = document.getElementById('camRulerUnit').value;
  if (!length || length <= 0) { toast('请输入有效的线段长度', 'warn'); return; }
  const dx = rulerPoints[1].x - rulerPoints[0].x;
  const dy = rulerPoints[1].y - rulerPoints[0].y;
  const pixelDist = Math.sqrt(dx * dx + dy * dy);
  const lengthCm = unit === 'm' ? length * 100 : length;
  rulerPixelsPerCm = pixelDist / lengthCm;
  document.getElementById('camRulerStatus').textContent =
    `✅ 已校准: ${pixelDist.toFixed(0)} 像素 = ${length} ${unit === 'm' ? '米' : '厘米'} (${rulerPixelsPerCm.toFixed(1)} px/cm)`;
  document.getElementById('camRulerStatus').style.color = '#4CAF50';
  saveCameraConfig();
  toast('标尺校准已保存', 'success');
}

function resetRuler() {
  rulerPoints = [];
  rulerPixelsPerCm = null;
  drawRulerCanvas();
  document.getElementById('camRulerStatus').textContent = '点击画面上两点，画一条已知长度的线段';
  document.getElementById('camRulerStatus').style.color = 'var(--text-secondary)';
  saveCameraConfig();
}

function drawRulerCanvas() {
  const canvas = document.getElementById('camRulerCanvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  if (!bgImageData) {
    ctx.fillStyle = '#333';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = '#999';
    ctx.font = '14px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('请先完成背景建模', canvas.width / 2, canvas.height / 2);
    return;
  }
  canvas.width = bgImageData.width;
  canvas.height = bgImageData.height;
  ctx.putImageData(bgImageData, 0, 0);
  if (rulerPoints.length > 0) {
    ctx.fillStyle = '#FF9800';
    rulerPoints.forEach((p, i) => {
      ctx.beginPath(); ctx.arc(p.x, p.y, 5, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = 'white';
      ctx.font = '12px sans-serif';
      ctx.fillText(i + 1, p.x + 8, p.y - 8);
      ctx.fillStyle = '#FF9800';
    });
    if (rulerPoints.length === 2) {
      ctx.strokeStyle = '#FF9800'; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(rulerPoints[0].x, rulerPoints[0].y);
      ctx.lineTo(rulerPoints[1].x, rulerPoints[1].y); ctx.stroke();
      if (rulerPixelsPerCm) {
        const dx = rulerPoints[1].x - rulerPoints[0].x;
        const dy = rulerPoints[1].y - rulerPoints[0].y;
        const midX = (rulerPoints[0].x + rulerPoints[1].x) / 2;
        const midY = (rulerPoints[0].y + rulerPoints[1].y) / 2;
        ctx.fillStyle = '#FF9800';
        ctx.font = 'bold 12px sans-serif';
        ctx.fillText(`${(Math.sqrt(dx*dx+dy*dy)/rulerPixelsPerCm).toFixed(1)} cm`, midX, midY - 8);
      }
    }
  }
}

function logCam(msg, type = 'info') {
  const el = document.getElementById('camEventLog');
  if (!el) return;
  const ts = new Date().toLocaleTimeString();
  el.innerHTML += `<span class="${type}">[${ts}] ${msg}</span>\n`;
  el.scrollTop = el.scrollHeight;
}

function goToStep(step) {
  document.querySelectorAll('.camera-step').forEach(el => el.classList.remove('active'));
  document.getElementById('camStep' + step).classList.add('active');
  document.querySelectorAll('.camera-step-dot').forEach(d => {
    d.classList.remove('active');
    const s = parseInt(d.dataset.step);
    if (s === step) d.classList.add('active');
    else if (s < step) d.classList.add('done');
  });
  const titles = ['第 1 步：选择摄像头', '第 2 步：追踪参数', '第 3 步：背景建模', '第 4 步：标尺校准', '第 5 步：绘制检测区域', '第 6 步：区域事件定义', '第 7 步：开始检测'];
  document.getElementById('cameraStepTitle').textContent = titles[step] || '';
  document.getElementById('camPrev').disabled = step === 0;
  cameraStep = step;
}

function cameraPrevStep() { if (cameraStep > 0) goToStep(cameraStep - 1); }

function cameraNextStep() {
  if (cameraStep === 0 && !document.getElementById('camSelect').value) { toast('请先选择一个摄像头', 'warn'); return; }
  if (cameraStep === 2 && !bgImageData) { toast('请先完成背景建模', 'warn'); return; }
  if (cameraStep === 3 && !bgImageData) { toast('请先完成背景建模', 'warn'); return; }
  if (cameraStep === 4 && zones.length === 0) { toast('请先绘制至少一个检测区域', 'warn'); return; }
  if (cameraStep < 6) goToStep(cameraStep + 1);
}

async function refreshCameraList() {
  const sel = document.getElementById('camSelect');
  sel.innerHTML = '<option value="">检测中...</option>';
  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    const cams = devices.filter(d => d.kind === 'videoinput');
    if (cams.length === 0) {
      sel.innerHTML = '<option value="">未检测到摄像头</option>';
      document.getElementById('camSelectStatus').textContent = '❌ 未检测到摄像头';
    } else {
      let html = '';
      cams.forEach((cam, i) => {
        html += `<option value="${cam.deviceId}">摄像头 ${i + 1}: ${cam.label || '未命名'}</option>`;
      });
      sel.innerHTML = html;
      document.getElementById('camSelectStatus').textContent = `✅ 检测到 ${cams.length} 个摄像头`;
    }
  } catch (e) {
    sel.innerHTML = '<option value="">无法检测摄像头</option>';
    document.getElementById('camSelectStatus').textContent = '⚠️ 请允许摄像头权限后重试';
  }
}

function setContrast(val) {
  contrast = val;
  document.getElementById('contrastDark').style.borderColor = val === 'dark' ? '#FF9800' : 'var(--border)';
  document.getElementById('contrastLight').style.borderColor = val === 'light' ? '#FF9800' : 'var(--border)';
}

function setBgMethod(method) {
  bgMethod = method;
  document.getElementById('bgMethodAuto').className = 'btn btn-sm' + (method === 'auto' ? ' btn-primary' : '');
  document.getElementById('bgMethodFill').className = 'btn btn-sm' + (method === 'fill' ? ' btn-primary' : '');
  document.getElementById('bgAutoArea').style.display = method === 'auto' ? 'block' : 'none';
  document.getElementById('bgFillArea').style.display = method === 'fill' ? 'block' : 'none';
}

async function startAutoBackground() {
  const deviceId = document.getElementById('camSelect').value;
  if (!deviceId) { toast('请先选择摄像头', 'warn'); return; }
  document.getElementById('btnCaptureBg').disabled = true;
  document.getElementById('camBgProgress').textContent = '正在采集帧... 0/30';
  try {
    if (cameraStream) cameraStream.getTracks().forEach(t => t.stop());
    cameraStream = await navigator.mediaDevices.getUserMedia({
      video: { deviceId: { exact: deviceId }, width: { ideal: 640 }, height: { ideal: 480 } },
      audio: false,
    });
    const video = document.getElementById('camPreviewBg');
    video.srcObject = cameraStream;
    await video.play();
    const canvas = document.getElementById('camCanvas');
    canvas.width = video.videoWidth || 640;
    canvas.height = video.videoHeight || 480;
    const ctx = canvas.getContext('2d');
    bgFrames = [];
    for (let i = 0; i < 30; i++) {
      await new Promise(r => setTimeout(r, 100));
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
      bgFrames.push(ctx.getImageData(0, 0, canvas.width, canvas.height).data.slice());
      document.getElementById('camBgProgress').textContent = `正在采集帧... ${i + 1}/30`;
    }
    const w = canvas.width, h = canvas.height;
    const result = new Uint8ClampedArray(w * h * 4);
    for (let p = 0; p < w * h * 4; p += 4) {
      const r = [], g = [], b = [];
      for (let f = 0; f < 30; f++) {
        r.push(bgFrames[f][p]); g.push(bgFrames[f][p + 1]); b.push(bgFrames[f][p + 2]);
      }
      r.sort(); g.sort(); b.sort();
      result[p] = r[15]; result[p + 1] = g[15]; result[p + 2] = b[15]; result[p + 3] = 255;
    }
    bgImageData = new ImageData(result, w, h);
    ctx.putImageData(bgImageData, 0, 0);
    drawZones();
    document.getElementById('camBgProgress').textContent = '✅ 背景已生成（30帧中值）';
    document.getElementById('camBgProgress').style.color = '#4CAF50';
    toast('背景已生成', 'success');
    document.getElementById('btnCaptureBg').disabled = false;
    if (cameraStream) { cameraStream.getTracks().forEach(t => t.stop()); cameraStream = null; }
    cameraNextStep();
  } catch (e) {
    toast('背景采集失败: ' + e.message, 'error');
    document.getElementById('camBgProgress').textContent = '❌ 采集失败';
    document.getElementById('btnCaptureBg').disabled = false;
  }
}

function startFillBox() {
  if (!cameraStream || !cameraStream.active) {
    const deviceId = document.getElementById('camSelect').value;
    if (!deviceId) { toast('请先选择摄像头', 'warn'); return; }
    navigator.mediaDevices.getUserMedia({
      video: { deviceId: { exact: deviceId }, width: { ideal: 640 }, height: { ideal: 480 } },
      audio: false,
    }).then(stream => {
      cameraStream = stream;
      const video = document.createElement('video');
      video.srcObject = stream;
      video.onloadedmetadata = () => {
        const canvas = document.getElementById('camFillCanvas');
        canvas.width = video.videoWidth || 640; canvas.height = video.videoHeight || 480;
        video.play(); drawFillFrame();
      };
    });
    return;
  }
  fillDragStart = null; bgFillBox = null;
  toast('在画面上拖拽框出动物位置', 'info');
}

function drawFillFrame() {
  const canvas = document.getElementById('camFillCanvas');
  const ctx = canvas.getContext('2d');
  if (cameraStream && cameraStream.active) {
    const video = document.querySelector('video[srcObject]');
    if (video) ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
  }
  if (bgFillBox) {
    ctx.strokeStyle = '#FF9800'; ctx.lineWidth = 2; ctx.setLineDash([6,4]);
    ctx.strokeRect(bgFillBox.x, bgFillBox.y, bgFillBox.w, bgFillBox.h);
    ctx.setLineDash([]);
  }
  if (cameraStream && cameraStream.active) requestAnimationFrame(drawFillFrame);
}

document.getElementById('camFillCanvas').addEventListener('mousedown', (e) => {
  if (bgMethod !== 'fill') return;
  const rect = e.target.getBoundingClientRect();
  fillDragStart = { x: e.clientX - rect.left, y: e.clientY - rect.top };
});
document.getElementById('camFillCanvas').addEventListener('mousemove', (e) => {
  if (!fillDragStart || bgMethod !== 'fill') return;
  const rect = e.target.getBoundingClientRect();
  const cx = e.clientX - rect.left, cy = e.clientY - rect.top;
  bgFillBox = { x: Math.min(fillDragStart.x, cx), y: Math.min(fillDragStart.y, cy), w: Math.abs(cx - fillDragStart.x), h: Math.abs(cy - fillDragStart.y) };
  const canvas = document.getElementById('camFillCanvas');
  const ctx = canvas.getContext('2d');
  if (cameraStream && cameraStream.active) {
    const video = document.querySelector('video[srcObject]');
    if (video) ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
  }
  ctx.strokeStyle = '#FF9800'; ctx.lineWidth = 2; ctx.setLineDash([6,4]);
  ctx.strokeRect(bgFillBox.x, bgFillBox.y, bgFillBox.w, bgFillBox.h);
  ctx.setLineDash([]);
});
document.getElementById('camFillCanvas').addEventListener('mouseup', () => {
  fillDragStart = null;
  if (bgFillBox && bgFillBox.w > 10 && bgFillBox.h > 10) {
    document.getElementById('camFillStatus').textContent = '✅ 已框选，点击"生成背景"完成';
  }
});

function applyFillBg() {
  if (!bgFillBox || bgFillBox.w < 10) { toast('请先框选动物位置', 'warn'); return; }
  const canvas = document.getElementById('camFillCanvas');
  const ctx = canvas.getContext('2d');
  const box = bgFillBox;
  const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
  const data = imageData.data;
  const w = canvas.width;
  for (let y = box.y; y < box.y + box.h && y < canvas.height; y++) {
    for (let x = box.x; x < box.x + box.w && x < canvas.width; x++) {
      const i = (y * w + x) * 4;
      const left = Math.max(0, x - 1), right = Math.min(w - 1, x + 1);
      const top = Math.max(0, y - 1), bottom = Math.min(canvas.height - 1, y + 1);
      let cr = 0, cg = 0, cb = 0, cn = 0;
      for (const ny of [top, y, bottom]) {
        for (const nx of [left, x, right]) {
          if (nx === x && ny === y) continue;
          const ni = (ny * w + nx) * 4;
          cr += data[ni]; cg += data[ni + 1]; cb += data[ni + 2]; cn++;
        }
      }
      if (cn > 0) { data[i] = cr / cn; data[i + 1] = cg / cn; data[i + 2] = cb / cn; }
    }
  }
  bgImageData = new ImageData(new Uint8ClampedArray(data), canvas.width, canvas.height);
  const mainCanvas = document.getElementById('camCanvas');
  mainCanvas.width = canvas.width; mainCanvas.height = canvas.height;
  const mainCtx = mainCanvas.getContext('2d');
  mainCtx.putImageData(bgImageData, 0, 0);
  drawZones();
  document.getElementById('camFillStatus').textContent = '✅ 背景已生成（填充法）';
  document.getElementById('camFillStatus').style.color = '#4CAF50';
  toast('背景已生成', 'success');
  if (cameraStream) { cameraStream.getTracks().forEach(t => t.stop()); cameraStream = null; }
  cameraNextStep();
}

let zonePoints = [];
let dragZoneIdx = -1;
let dragPtIdx = -1;

function polygonArea(points) {
  let area = 0;
  for (let i = 0; i < points.length; i++) {
    const j = (i + 1) % points.length;
    area += points[i].x * points[j].y;
    area -= points[j].x * points[i].y;
  }
  return Math.abs(area) / 2;
}

function pointInPolygon(px, py, points) {
  let inside = false;
  for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
    const xi = points[i].x, yi = points[i].y;
    const xj = points[j].x, yj = points[j].y;
    if ((yi > py) !== (yj > py) && px < (xj - xi) * (py - yi) / (yj - yi) + xi) {
      inside = !inside;
    }
  }
  return inside;
}

function areaDisplay(pxArea) {
  if (rulerPixelsPerCm && rulerPixelsPerCm > 0) {
    const cm2 = pxArea / (rulerPixelsPerCm * rulerPixelsPerCm);
    if (cm2 >= 10000) return (cm2 / 10000).toFixed(2) + ' m²';
    return cm2.toFixed(1) + ' cm²';
  }
  return pxArea.toFixed(0) + ' px²';
}

function addZone() {
  if (!bgImageData) { toast('请先完成背景建模', 'warn'); return; }
  zoneDrawMode = true;
  zonePoints = [];
  dragZoneIdx = -1;
  dragPtIdx = -1;
  document.getElementById('camCanvas').style.cursor = 'crosshair';
  toast('点击画面放置顶点，双击最后一个顶点闭合多边形', 'info');
}

function removeLastZone() {
  if (zones.length === 0) return;
  zones.pop(); zoneDrawMode = false; zonePoints = [];
  drawZones(); updateZoneList();
}

function drawZones() {
  const canvas = document.getElementById('camCanvas');
  const ctx = canvas.getContext('2d');
  if (bgImageData) ctx.putImageData(bgImageData, 0, 0);
  ctx.font = '14px sans-serif'; ctx.textBaseline = 'top';

  zones.forEach((z) => {
    if (!z.points || z.points.length < 3) return;
    ctx.strokeStyle = z.color; ctx.lineWidth = 3;
    ctx.fillStyle = z.color + '30';
    ctx.beginPath();
    ctx.moveTo(z.points[0].x, z.points[0].y);
    for (let i = 1; i < z.points.length; i++) {
      ctx.lineTo(z.points[i].x, z.points[i].y);
    }
    ctx.closePath();
    ctx.fill();
    ctx.stroke();

    const p0 = z.points[0];
    ctx.fillStyle = z.color;
    const labelW = ctx.measureText(z.name).width + 12;
    ctx.fillRect(p0.x, p0.y - 22, labelW, 22);
    ctx.fillStyle = 'white';
    ctx.fillText(z.name, p0.x + 6, p0.y - 18);

    const pxArea = polygonArea(z.points);
    const areaStr = areaDisplay(pxArea);
    ctx.fillStyle = z.color;
    ctx.font = '11px sans-serif';
    ctx.fillText(areaStr, p0.x + 6, p0.y - 5);

    if (dragZoneIdx >= 0 && zones[dragZoneIdx] === z) {
      z.points.forEach((p, i) => {
        ctx.fillStyle = (i === dragPtIdx) ? '#FFD700' : z.color;
        ctx.beginPath(); ctx.arc(p.x, p.y, 5, 0, Math.PI * 2); ctx.fill();
        ctx.strokeStyle = '#fff'; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.arc(p.x, p.y, 5, 0, Math.PI * 2); ctx.stroke();
      });
    }
  });

  if (zonePoints.length > 0) {
    ctx.strokeStyle = '#FF9800'; ctx.lineWidth = 2; ctx.setLineDash([6, 4]);
    ctx.fillStyle = '#FF9800';
    zonePoints.forEach((p, i) => {
      ctx.beginPath(); ctx.arc(p.x, p.y, 4, 0, Math.PI * 2); ctx.fill();
    });
    ctx.beginPath();
    ctx.moveTo(zonePoints[0].x, zonePoints[0].y);
    for (let i = 1; i < zonePoints.length; i++) {
      ctx.lineTo(zonePoints[i].x, zonePoints[i].y);
    }
    ctx.stroke(); ctx.setLineDash([]);
  }
}

function closePolygon() {
  if (zonePoints.length < 3) { toast('至少需要3个顶点', 'warn'); return; }
  const idx = zones.length;
  zones.push({
    id: 'zone_' + idx,
    name: '区域 ' + String.fromCharCode(65 + idx),
    points: [...zonePoints],
    color: ZONE_COLORS[idx % ZONE_COLORS.length],
  });
  zoneDrawMode = false;
  zonePoints = [];
  document.getElementById('camCanvas').style.cursor = 'default';
  drawZones(); updateZoneList();
  toast('已添加 ' + zones[zones.length - 1].name, 'success');
}

function updateZoneList() {
  const el = document.getElementById('zoneList');
  if (zones.length === 0) {
    el.innerHTML = '<p style="color:var(--text-secondary);font-size:12px">还没有定义检测区域，点击"添加区域"开始绘制多边形</p>';
    return;
  }
  let html = '';
  zones.forEach((z, i) => {
    const pxArea = polygonArea(z.points);
    const areaStr = areaDisplay(pxArea);
    html += `<div class="flex" style="align-items:center;margin:4px 0">
      <span style="display:inline-block;width:12px;height:12px;border-radius:3px;background:${z.color};margin-right:8px"></span>
      ${z.name} — ${z.points.length} 顶点 — ${areaStr}
    </div>`;
  });
  el.innerHTML = html;
  const configEl = document.getElementById('zoneConfigList');
  let cfgHtml = '';
  zones.forEach((z, i) => {
    cfgHtml += `<div class="card" style="padding:8px;margin:4px 0">
      <div class="flex" style="align-items:center">
        <span style="display:inline-block;width:12px;height:12px;border-radius:3px;background:${z.color};margin-right:8px"></span>
        <input value="${z.name}" style="flex:1;padding:4px 8px;border:1px solid var(--border);border-radius:4px"
          onchange="zones[${i}].name=this.value;drawZones();updateZoneList()">
      </div>
      <p style="color:var(--text-secondary);font-size:11px;margin-top:4px">
        动物进入「${z.name}」→ 触发信号「<strong>camera:${z.name}:enter</strong>」<br>
        动物离开「${z.name}」→ 触发信号「<strong>camera:${z.name}:leave</strong>」
      </p>
    </div>`;
  });
  configEl.innerHTML = cfgHtml;
  saveCameraConfig();
}

async function saveCameraConfig() {
  const config = {
    zones: zones.map(z => ({ name: z.name, points: z.points })),
    contrast: contrast,
    algorithm: document.getElementById('camAlgo') ? document.getElementById('camAlgo').value : 'bgsub',
    sensitivity: document.getElementById('camSensitivity') ? parseInt(document.getElementById('camSensitivity').value) : 30,
    min_area: document.getElementById('camMinArea') ? parseInt(document.getElementById('camMinArea').value) : 500,
    ruler_points: rulerPoints,
    pixels_per_cm: rulerPixelsPerCm,
  };
  try {
    await fetch('/api/camera/config', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ config, experiment_id: currentExperimentId }),
    });
  } catch (e) { /* best effort */ }
}

async function loadCameraConfig() {
  try {
    let url = '/api/camera/config';
    if (currentExperimentId) url += '?experiment_id=' + encodeURIComponent(currentExperimentId);
    const resp = await fetch(url);
    const data = await resp.json();
    const cfg = data.config || {};
    if (cfg.zones && cfg.zones.length > 0) {
      zones = cfg.zones.map((z, i) => ({
        id: 'zone_' + i, name: z.name,
        points: z.points || [{x: z.x, y: z.y}, {x: z.x + z.w, y: z.y}, {x: z.x + z.w, y: z.y + z.h}, {x: z.x, y: z.y + z.h}],
        color: ZONE_COLORS[i % ZONE_COLORS.length],
      }));
      if (cfg.contrast) { contrast = cfg.contrast; setContrast(cfg.contrast); }
      if (cfg.sensitivity) document.getElementById('camSensitivity').value = cfg.sensitivity;
      if (cfg.min_area) document.getElementById('camMinArea').value = cfg.min_area;
      drawZones(); updateZoneList();
    }
    if (cfg.ruler_points && cfg.ruler_points.length > 0) {
      rulerPoints = cfg.ruler_points;
      rulerPixelsPerCm = cfg.pixels_per_cm || null;
      drawRulerCanvas();
      if (rulerPixelsPerCm) {
        document.getElementById('camRulerStatus').textContent =
          `✅ 已加载校准: ${rulerPixelsPerCm.toFixed(1)} px/cm`;
        document.getElementById('camRulerStatus').style.color = '#4CAF50';
      }
    }
  } catch (e) { /* first time */ }
}

function setCameraExperiment(expId, expName) {
  currentExperimentId = expId;
  currentExperimentName = expName || '';
  const el = document.getElementById('cameraExpBadge');
  if (el) {
    if (expId) {
      el.textContent = '📋 当前实验: ' + currentExperimentName;
      el.style.display = 'block';
    } else {
      el.style.display = 'none';
    }
  }
  zones = [];
  bgImageData = null;
  drawZones();
  updateZoneList();
  loadCameraConfig();
}

// --- Centroid / contour helper ---
function findCentroid(data, w, h, threshold) {
  let sumX = 0, sumY = 0, count = 0, minX = w, maxX = 0, minY = h, maxY = 0;
  for (let y = 0; y < h; y += 2) {
    for (let x = 0; x < w; x += 2) {
      const i = (y * w + x) * 4;
      if (data[i] === 255) {
        sumX += x; sumY += y; count++;
        if (x < minX) minX = x; if (x > maxX) maxX = x;
        if (y < minY) minY = y; if (y > maxY) maxY = y;
      }
    }
  }
  if (count < 5) return null;
  return { cx: sumX / count, cy: sumY / count, minX, maxX, minY, maxY, count };
}

// --- Detection ---
async function startCameraDetection() {
  if (zones.length === 0) { toast('请先添加至少一个检测区域', 'warn'); return; }
  if (!bgImageData) { toast('请先完成背景建模', 'warn'); return; }

  saveCameraConfig();

  document.getElementById('btnStartDetection').disabled = true;
  document.getElementById('btnStopDetection').disabled = false;
  document.getElementById('camDetectionLog').style.display = 'block';
  document.getElementById('camEventLog').innerHTML = '检测开始...\n';
  toast('摄像头检测已启动', 'success');

  const deviceId = document.getElementById('camSelect').value;
  const sensitivity = parseInt(document.getElementById('camSensitivity').value);
  const minArea = parseInt(document.getElementById('camMinArea').value);
  const algo = document.getElementById('camAlgo').value;
  const bgData = bgImageData.data;

  try {
    if (!cameraStream || !cameraStream.active) {
      cameraStream = await navigator.mediaDevices.getUserMedia({
        video: { deviceId: { exact: deviceId }, width: { ideal: 640 }, height: { ideal: 480 } },
        audio: false,
      });
    }
    const video = document.createElement('video');
    video.srcObject = cameraStream; video.width = 640; video.height = 480;
    await video.play();
    const canvas = document.getElementById('camCanvas');
    const ctx = canvas.getContext('2d');
    const threshold = 40 - sensitivity * 0.35;
    let prevFrame = null;
    let inZone = {};

    detectInterval = setInterval(() => {
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
      const frame = ctx.getImageData(0, 0, canvas.width, canvas.height);
      const data = frame.data;

      // Detect motion pixels based on chosen algorithm
      for (let i = 0; i < data.length; i += 4) {
        let isMotion = false;

        if (algo === 'bgsub' || algo === 'graythresh') {
          const diff = Math.abs(data[i] - bgData[i]) + Math.abs(data[i + 1] - bgData[i + 1]) + Math.abs(data[i + 2] - bgData[i + 2]);
          if (algo === 'bgsub') {
            const isDarker = data[i] < bgData[i] - threshold / 3;
            const isLighter = data[i] > bgData[i] + threshold / 3;
            const matches = contrast === 'dark' ? isDarker : isLighter;
            isMotion = diff > threshold && matches;
          } else {
            // Gray threshold: compare luminance
            const lum = 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
            const bgLum = 0.299 * bgData[i] + 0.587 * bgData[i + 1] + 0.114 * bgData[i + 2];
            const lumDiff = contrast === 'dark' ? (bgLum - lum) : (lum - bgLum);
            isMotion = lumDiff > threshold * 0.5;
          }
        } else if (algo === 'silhouette' && prevFrame) {
          // Frame differencing
          const diff = Math.abs(data[i] - prevFrame.data[i]) +
                       Math.abs(data[i + 1] - prevFrame.data[i + 1]) +
                       Math.abs(data[i + 2] - prevFrame.data[i + 2]);
          isMotion = diff > threshold * 1.5;
        }

        if (isMotion) {
          data[i] = 255; data[i + 1] = 0; data[i + 2] = 0; data[i + 3] = 128;
        }
      }

      // Draw centroid + bounding box for each detected blob
      const centroid = findCentroid(data, canvas.width, canvas.height, threshold);
      if (centroid && centroid.count > 10) {
        ctx.strokeStyle = '#FFD700'; ctx.lineWidth = 2;
        ctx.strokeRect(centroid.minX, centroid.minY, centroid.maxX - centroid.minX, centroid.maxY - centroid.minY);
        ctx.fillStyle = '#FFD700';
        ctx.beginPath(); ctx.arc(centroid.cx, centroid.cy, 4, 0, Math.PI * 2); ctx.fill();
      }

      ctx.putImageData(frame, 0, 0);
      drawZones();

      // Check each zone
      zones.forEach(z => {
        if (!z.points || z.points.length < 3) return;
        let zoneMotion = 0;
        const minX = Math.min(...z.points.map(p => p.x));
        const maxX = Math.max(...z.points.map(p => p.x));
        const minY = Math.min(...z.points.map(p => p.y));
        const maxY = Math.max(...z.points.map(p => p.y));
        for (let y = Math.max(0, minY); y < Math.min(canvas.height, maxY); y += 3) {
          for (let x = Math.max(0, minX); x < Math.min(canvas.width, maxX); x += 3) {
            if (data[(y * canvas.width + x) * 4] === 255 && pointInPolygon(x, y, z.points)) {
              zoneMotion++;
            }
          }
        }
        const had = inZone[z.id];
        const has = zoneMotion > minArea / 30;
        if (has && !had) {
          inZone[z.id] = true;
          logCam(`🧪 ${z.name}: 动物进入`, 'success');
          toast(`${z.name}: 检测到动物进入`, 'info');
          fetch('/api/experiment/camera-event', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ zone: z.name, event: 'enter', ts: Date.now(), experiment_id: currentExperimentId }),
          }).catch(() => {});
        } else if (!has && had) {
          inZone[z.id] = false;
          logCam(`🧪 ${z.name}: 动物离开`, 'warn');
          fetch('/api/experiment/camera-event', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ zone: z.name, event: 'leave', ts: Date.now(), experiment_id: currentExperimentId }),
          }).catch(() => {});
        }
      });

      prevFrame = frame;
    }, 200);

    const algoLabel = algo === 'bgsub' ? '背景差分' : algo === 'graythresh' ? '灰度阈值' : algo === 'colordetect' ? '颜色检测' : '动态剪影';
    document.getElementById('cameraDetectStatus').textContent =
      `✅ 检测运行中 | ${algoLabel} | ${contrast === 'dark' ? '暗色' : '亮色'} | 灵敏度 ${sensitivity}`;
  } catch (e) {
    toast('检测启动失败: ' + e.message, 'error');
    document.getElementById('btnStartDetection').disabled = false;
    document.getElementById('btnStopDetection').disabled = true;
  }
}

function stopCameraDetection() {
  if (detectInterval) { clearInterval(detectInterval); detectInterval = null; }
  if (cameraStream) { cameraStream.getTracks().forEach(t => t.stop()); cameraStream = null; }
  document.getElementById('btnStartDetection').disabled = false;
  document.getElementById('btnStopDetection').disabled = true;
  document.getElementById('cameraDetectStatus').textContent = '⏹ 检测已停止';
  toast('摄像头检测已停止', 'warn');
  logCam('⏹ 检测已停止', 'warn');
}

document.addEventListener('visibilitychange', () => {});

// Ruler canvas click handler
const rulerCanvas = document.getElementById('camRulerCanvas');
if (rulerCanvas) {
  rulerCanvas.addEventListener('click', (e) => {
    if (cameraStep !== 3) return;
    if (rulerPoints.length >= 2) rulerPoints = [];
    const rect = e.target.getBoundingClientRect();
    rulerPoints.push({ x: e.clientX - rect.left, y: e.clientY - rect.top });
    drawRulerCanvas();
    if (rulerPoints.length === 2) {
      const dx = rulerPoints[1].x - rulerPoints[0].x;
      const dy = rulerPoints[1].y - rulerPoints[0].y;
      const pixelDist = Math.sqrt(dx * dx + dy * dy);
      document.getElementById('camRulerStatus').textContent =
        `已选择两点，线段长度: ${pixelDist.toFixed(0)} 像素。请输入实际长度并点击确认校准`;
    }
  });
}

refreshCameraList();
loadCameraConfig();

// Find nearest vertex within threshold
function findNearestVertex(canvasX, canvasY, threshold) {
  threshold = threshold || 12;
  let bestIdx = -1, bestZone = -1, bestDist = Infinity;
  zones.forEach((z, zi) => {
    if (!z.points) return;
    z.points.forEach((p, pi) => {
      const dist = Math.hypot(p.x - canvasX, p.y - canvasY);
      if (dist < threshold && dist < bestDist) {
        bestDist = dist; bestIdx = pi; bestZone = zi;
      }
    });
  });
  return { zone: bestZone, point: bestIdx };
}

// Canvas mouse handlers
const zoneCanvas = document.getElementById('camCanvas');
let mouseCanvasPos = null;

zoneCanvas.addEventListener('mousedown', (e) => {
  if (e.button !== 0) return;
  const rect = zoneCanvas.getBoundingClientRect();
  const cx = e.clientX - rect.left;
  const cy = e.clientY - rect.top;

  if (zoneDrawMode) {
    zonePoints.push({ x: cx, y: cy });
    drawZones();
    return;
  }

  const near = findNearestVertex(cx, cy);
  if (near.zone >= 0 && near.point >= 0) {
    dragZoneIdx = near.zone;
    dragPtIdx = near.point;
    zoneCanvas.style.cursor = 'grabbing';
    drawZones();
  } else {
    dragZoneIdx = -1;
    dragPtIdx = -1;
  }
});

zoneCanvas.addEventListener('mousemove', (e) => {
  const rect = zoneCanvas.getBoundingClientRect();
  const cx = e.clientX - rect.left;
  const cy = e.clientY - rect.top;
  mouseCanvasPos = { x: cx, y: cy };

  if (dragZoneIdx >= 0 && dragPtIdx >= 0) {
    zones[dragZoneIdx].points[dragPtIdx].x = cx;
    zones[dragZoneIdx].points[dragPtIdx].y = cy;
    drawZones();
    return;
  }

  if (zoneDrawMode && zonePoints.length > 0) {
    drawZones();
    const ctx = zoneCanvas.getContext('2d');
    const last = zonePoints[zonePoints.length - 1];
    ctx.strokeStyle = '#FFD700'; ctx.lineWidth = 1; ctx.setLineDash([4, 4]);
    ctx.beginPath(); ctx.moveTo(last.x, last.y);
    ctx.lineTo(cx, cy); ctx.stroke(); ctx.setLineDash([]);
    return;
  }

  if (!zoneDrawMode) {
    const near = findNearestVertex(cx, cy);
    zoneCanvas.style.cursor = (near.zone >= 0) ? 'grab' : 'default';
  }
});

zoneCanvas.addEventListener('mouseup', () => {
  if (dragZoneIdx >= 0) {
    updateZoneList();
    saveCameraConfig();
  }
  dragZoneIdx = -1;
  dragPtIdx = -1;
  zoneCanvas.style.cursor = zoneDrawMode ? 'crosshair' : 'default';
});

zoneCanvas.addEventListener('dblclick', (e) => {
  if (zoneDrawMode && zonePoints.length >= 3) {
    closePolygon();
  }
});

zoneCanvas.addEventListener('contextmenu', (e) => {
  e.preventDefault();
  const rect = zoneCanvas.getBoundingClientRect();
  const cx = e.clientX - rect.left;
  const cy = e.clientY - rect.top;
  const near = findNearestVertex(cx, cy);
  if (near.zone >= 0 && near.point >= 0) {
    if (zones[near.zone].points.length <= 3) {
      toast('至少需要3个顶点，请删除整个区域', 'warn');
      return;
    }
    zones[near.zone].points.splice(near.point, 1);
    drawZones(); updateZoneList();
    toast('已删除顶点', 'info');
  } else {
    const zoneIdx = zones.findIndex(z => {
      if (!z.points || z.points.length < 3) return false;
      return pointInPolygon(cx, cy, z.points);
    });
    if (zoneIdx >= 0) {
      if (confirm(`确定删除区域「${zones[zoneIdx].name}」吗？`)) {
        zones.splice(zoneIdx, 1);
        drawZones(); updateZoneList();
        toast('已删除区域', 'warn');
      }
    }
  }
});

zoneCanvas.addEventListener('mouseleave', () => {
  dragZoneIdx = -1;
  dragPtIdx = -1;
  zoneCanvas.style.cursor = zoneDrawMode ? 'crosshair' : 'default';
});
