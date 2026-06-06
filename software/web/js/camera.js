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
let bgFillPoints = [];
let bgFillMode = false;
let bgFillCloseBtn = null;
// currentExperimentId declared in flow-editor.js (G3-FIN-1)
let currentExperimentName = '';
let cameraExperimentEnabled = false;
let eventRules = [];

const ZONE_COLORS = ['#FF9800', '#4CAF50', '#2196F3', '#E91E63', '#9C27B0'];

let rulerPoints = [];
let rulerPixelsPerCm = null;

let trackPreviewInterval = null;
let _detectionPaused = false;
let _smoothPrev = { cx: null, cy: null, minX: null, minY: null, maxX: null, maxY: null };

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
  toast('标尺校准已保存', 'success');
  if (zones.length > 0) { drawZones(); updateZoneList(); }
}

function resetRuler() {
  rulerPoints = [];
  rulerPixelsPerCm = null;
  drawRulerCanvas();
  document.getElementById('camRulerStatus').textContent = '点击画面上两点，画一条已知长度的线段';
  document.getElementById('camRulerStatus').style.color = 'var(--text-secondary)';
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
      const dx = rulerPoints[1].x - rulerPoints[0].x;
      const dy = rulerPoints[1].y - rulerPoints[0].y;
      const pixelDist = Math.sqrt(dx * dx + dy * dy);
      const midX = (rulerPoints[0].x + rulerPoints[1].x) / 2;
      const midY = (rulerPoints[0].y + rulerPoints[1].y) / 2;
      ctx.fillStyle = '#FF9800';
      ctx.font = 'bold 12px sans-serif';
      ctx.fillText(`${pixelDist.toFixed(0)} px`, midX, midY - 8);
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
  const oldStep = cameraStep;
  document.querySelectorAll('.camera-step').forEach(el => el.classList.remove('active'));
  document.getElementById('camStep' + step).classList.add('active');
  document.querySelectorAll('.camera-step-dot').forEach(d => {
    d.classList.remove('active');
    const s = parseInt(d.dataset.step);
    if (s === step) d.classList.add('active');
    else if (s < step) d.classList.add('done');
  });
  const titles = [
    '第 1 步：选择摄像头',
    '第 2 步：背景建模',
    '第 3 步：标尺校准',
    '第 4 步：绘制检测区域',
    '第 5 步：区域事件定义',
    '第 6 步：追踪参数',
    '第 7 步：开始检测'
  ];
  document.getElementById('cameraStepTitle').textContent = titles[step] || '';
  document.getElementById('camPrev').disabled = step === 0;
  cameraStep = step;

  if (oldStep === 1 && step !== 1) releaseBgCamera();
  if (step === 1 && oldStep !== 1) {
    updateBgConfiguredBadge();
    if (bgMethod === 'auto') {
      startBgPreview();
    } else if (bgMethod === 'fill') {
      startFillBox();
    }
  }
  if (step === 2) drawRulerCanvas();
  if (step === 3) drawZones();
  if (step === 4) renderEventRules();
  if (step === 5 && oldStep !== 5) startTrackStepCamera();
  if (oldStep === 5 && step !== 5 && step !== 6) releaseTrackCamera();
  if (oldStep === 5 && step === 6) { /* keep stream for detection */ }
  if (step === 6) updateViewConfigButton();

  if (oldStep === 6 && step !== 6 && detectInterval) {
    _detectionPaused = true;
    clearInterval(detectInterval);
    detectInterval = null;
    const previewCanvas = document.getElementById('camDetectPreview');
    if (previewCanvas) {
      previewCanvas.style.display = 'none';
    }
    document.getElementById('cameraDetectStatus').textContent = '⏸ 检测已暂停';
    document.getElementById('btnStartDetection').disabled = false;
  }
  if (step === 6 && oldStep !== 6 && _detectionPaused) {
    _detectionPaused = false;
    startCameraDetection();
  }
}

function cameraPrevStep() {
  if (cameraStep > 0) goToStep(cameraStep - 1);
}

function cameraNextStep() {
  if (cameraStep === 0 && !document.getElementById('camSelect').value) { toast('请先选择一个摄像头', 'warn'); return; }
  if (cameraStep === 1 && !bgImageData) { toast('请先完成背景建模', 'warn'); return; }
  if (cameraStep === 2 && !bgImageData) { toast('请先完成背景建模', 'warn'); return; }
  if (cameraStep === 3 && zones.length === 0) { toast('请先绘制至少一个检测区域', 'warn'); return; }
  if (cameraStep === 4 && (!Array.isArray(eventRules) || eventRules.length === 0)) { toast('建议先定义至少一条事件规则', 'warn'); return; }
  if (cameraStep === 5 && !bgImageData) { toast('请先完成背景建模', 'warn'); return; }
  if (cameraStep < 6) goToStep(cameraStep + 1);
}

async function refreshCameraList() {
  const sel = document.getElementById('camSelect');
  sel.innerHTML = '<option value="">检测中...</option>';
  try {
    let tempStream = null;
    try {
      tempStream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
    } catch (permErr) {
    }
    const devices = await navigator.mediaDevices.enumerateDevices();
    if (tempStream) {
      tempStream.getTracks().forEach(t => t.stop());
    }
    const cams = devices.filter(d => d.kind === 'videoinput');
    if (cams.length === 0) {
      sel.innerHTML = '<option value="">暂未检测到可用摄像头</option>';
      document.getElementById('camSelectStatus').textContent = '💡 暂未检测到可用摄像头';
    } else {
      let html = '';
      cams.forEach((cam, i) => {
        html += `<option value="${cam.deviceId}">摄像头 ${i + 1}: ${cam.label || '未命名'}</option>`;
      });
      sel.innerHTML = html;
      document.getElementById('camSelectStatus').textContent = `✅ 检测到 ${cams.length} 个摄像头`;
    }
  } catch (e) {
    sel.innerHTML = '<option value="">未能检测摄像头，请检查连接</option>';
    document.getElementById('camSelectStatus').textContent = '💡 请授予摄像头权限后重试';
  }
}

function setContrast(val) {
  contrast = val;
  document.getElementById('contrastDark').style.borderColor = val === 'dark' ? '#FF9800' : 'var(--border)';
  document.getElementById('contrastLight').style.borderColor = val === 'light' ? '#FF9800' : 'var(--border)';
}

function updateBgConfiguredBadge() {
  const badge = document.getElementById('bgConfiguredBadge');
  if (!badge) return;
  if (bgImageData) {
    badge.style.display = 'block';
  } else {
    badge.style.display = 'none';
  }
}

function setBgMethod(method) {
  const oldMethod = bgMethod;
  bgMethod = method;
  document.getElementById('bgMethodAuto').className = 'btn btn-sm' + (method === 'auto' ? ' btn-primary' : '');
  document.getElementById('bgMethodFill').className = 'btn btn-sm' + (method === 'fill' ? ' btn-primary' : '');
  document.getElementById('bgAutoArea').style.display = method === 'auto' ? 'block' : 'none';
  document.getElementById('bgFillArea').style.display = method === 'fill' ? 'block' : 'none';
  if (method === 'auto' && (!cameraStream || !cameraStream.active)) {
    startBgPreview();
  }
  if (method === 'fill' && oldMethod !== 'fill') {
    if (cameraStream && cameraStream.active) {
      _setupFillFromStream(cameraStream);
    } else {
      startFillBox();
    }
  }
}

function startBgPreview() {
  const deviceId = document.getElementById('camSelect').value;
  if (!deviceId) { toast('请先选择摄像头', 'warn'); return; }
  if (cameraStream) {
    cameraStream.getTracks().forEach(t => t.stop());
    cameraStream = null;
  }
  navigator.mediaDevices.getUserMedia({
    video: { deviceId: { exact: deviceId }, width: { ideal: 640 }, height: { ideal: 480 } },
    audio: false,
  }).then(stream => {
    cameraStream = stream;
    const autoVideo = document.getElementById('camPreviewBg');
    autoVideo.srcObject = stream;
    autoVideo.play().catch(() => {});
    const fillVideo = document.getElementById('camFillVideo');
    fillVideo.srcObject = stream;
    fillVideo.onloadedmetadata = () => {
      const fillCanvas = document.getElementById('camFillCanvas');
      fillCanvas.width = fillVideo.videoWidth || 640;
      fillCanvas.height = fillVideo.videoHeight || 480;
      fillVideo.play().catch(() => {});
      if (bgMethod === 'fill') drawFillFrame();
    };
    if (fillVideo.readyState >= 2) {
      const fillCanvas = document.getElementById('camFillCanvas');
      fillCanvas.width = fillVideo.videoWidth || 640;
      fillCanvas.height = fillVideo.videoHeight || 480;
    }
    document.getElementById('camBgProgress').textContent = '摄像头已开启，点击"开始采集背景"采集30帧';
    document.getElementById('camBgProgress').style.color = 'var(--text-secondary)';
  }).catch(e => {
    toast('摄像头暂未就绪，可以重试', 'error');
    document.getElementById('camBgProgress').textContent = '💡 摄像头暂未就绪，请重试';
  });
}

function releaseBgCamera() {
  if (cameraStream) {
    cameraStream.getTracks().forEach(t => t.stop());
    cameraStream = null;
  }
  const autoVideo = document.getElementById('camPreviewBg');
  if (autoVideo) autoVideo.srcObject = null;
  const fillVideo = document.getElementById('camFillVideo');
  if (fillVideo) fillVideo.srcObject = null;
}

async function startAutoBackground() {
  const deviceId = document.getElementById('camSelect').value;
  if (!deviceId) { toast('请先选择摄像头', 'warn'); return; }
  document.getElementById('btnCaptureBg').disabled = true;
  document.getElementById('camBgProgress').textContent = '正在采集帧... 0/30';
  try {
    if (!cameraStream || !cameraStream.active) {
      if (cameraStream) cameraStream.getTracks().forEach(t => t.stop());
      cameraStream = await navigator.mediaDevices.getUserMedia({
        video: { deviceId: { exact: deviceId }, width: { ideal: 640 }, height: { ideal: 480 } },
        audio: false,
      });
    }
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
    saveBackgroundImage();
     document.getElementById('camBgProgress').textContent = '✅ 背景已生成（30帧中值）';
     document.getElementById('camBgProgress').style.color = '#4CAF50';
     toast('背景已生成', 'success');
     document.getElementById('btnCaptureBg').disabled = false;
     releaseBgCamera();
     updateBgConfiguredBadge();
  } catch (e) {
    toast('背景采集未成功，请重试', 'error');
    document.getElementById('camBgProgress').textContent = '💡 采集未成功，可以重试';
    document.getElementById('btnCaptureBg').disabled = false;
  }
}

function startFillBox() {
  const btn = document.getElementById('btnToggleFillPreview');
  const fillCanvas = document.getElementById('camFillCanvas');
  const fillStatus = document.getElementById('camFillStatus');

  if (cameraStream && cameraStream.active) {
    releaseBgCamera();
    btn.textContent = '📷 打开预览';
    fillStatus.textContent = '';
    const ctx = fillCanvas.getContext('2d');
    ctx.fillStyle = '#000';
    ctx.fillRect(0, 0, fillCanvas.width, fillCanvas.height);
    bgFillPoints = [];
    bgFillMode = false;
    return;
  }

  const deviceId = document.getElementById('camSelect').value;
  if (!deviceId) { toast('请先选择摄像头', 'warn'); return; }

  bgFillPoints = [];
  bgFillMode = false;
  const fillVideo = document.getElementById('camFillVideo');

  function setupFillVideo(stream) {
    fillVideo.srcObject = stream;
    fillVideo.onloadedmetadata = () => {
      fillCanvas.width = fillVideo.videoWidth || 640;
      fillCanvas.height = fillVideo.videoHeight || 480;
      fillVideo.play();
      drawFillFrame();
      fillStatus.textContent = '点击画面放置顶点，用多边形圈出动物位置。双击最后一个顶点闭合多边形';
    };
    if (fillVideo.readyState >= 2) {
      fillCanvas.width = fillVideo.videoWidth || 640;
      fillCanvas.height = fillVideo.videoHeight || 480;
      fillVideo.play();
      drawFillFrame();
      fillStatus.textContent = '点击画面放置顶点，用多边形圈出动物位置。双击最后一个顶点闭合多边形';
    }
  }

  if (cameraStream && cameraStream.active) {
    setupFillVideo(cameraStream);
  } else {
    navigator.mediaDevices.getUserMedia({
      video: { deviceId: { exact: deviceId }, width: { ideal: 640 }, height: { ideal: 480 } },
      audio: false,
    }).then(stream => {
      cameraStream = stream;
      setupFillVideo(stream);
    }).catch(e => {
      toast('摄像头暂未就绪，可以重试', 'error');
      return;
    });
  }
  btn.textContent = '📷 关闭预览';
}

function _setupFillFromStream(stream) {
  const fillCanvas = document.getElementById('camFillCanvas');
  const fillVideo = document.getElementById('camFillVideo');
  const fillStatus = document.getElementById('camFillStatus');
  const btn = document.getElementById('btnToggleFillPreview');

  fillVideo.srcObject = stream;
  fillVideo.onloadedmetadata = () => {
    fillCanvas.width = fillVideo.videoWidth || 640;
    fillCanvas.height = fillVideo.videoHeight || 480;
    fillVideo.play().catch(() => {});
    drawFillFrame();
    if (fillStatus) fillStatus.textContent = '点击画面放置顶点，用多边形圈出动物位置。双击最后一个顶点闭合多边形';
  };
  if (fillVideo.readyState >= 2) {
    fillCanvas.width = fillVideo.videoWidth || 640;
    fillCanvas.height = fillVideo.videoHeight || 480;
    fillVideo.play().catch(() => {});
    drawFillFrame();
    if (fillStatus) fillStatus.textContent = '点击画面放置顶点，用多边形圈出动物位置。双击最后一个顶点闭合多边形';
  }
  if (btn) btn.textContent = '📷 关闭预览';
  bgFillPoints = [];
  bgFillMode = false;
}

function drawFillFrame() {
  const canvas = document.getElementById('camFillCanvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const fillVideo = document.getElementById('camFillVideo');

  if (fillVideo && fillVideo.readyState >= 2) {
    ctx.drawImage(fillVideo, 0, 0, canvas.width, canvas.height);
  }

  if (bgFillPoints.length > 0) {
    ctx.strokeStyle = '#FF9800'; ctx.lineWidth = 2;
    ctx.fillStyle = 'rgba(255,152,0,0.08)';
    ctx.beginPath();
    ctx.moveTo(bgFillPoints[0].x, bgFillPoints[0].y);
    for (let i = 1; i < bgFillPoints.length; i++) {
      ctx.lineTo(bgFillPoints[i].x, bgFillPoints[i].y);
    }
    if (bgFillMode) {
      ctx.closePath();
      ctx.fill();
    }
    ctx.stroke();

    // Draw vertices
    bgFillPoints.forEach((p, i) => {
      ctx.beginPath();
      ctx.arc(p.x, p.y, 4, 0, Math.PI * 2);
      ctx.fillStyle = i === 0 ? '#4CAF50' : '#FF9800';
      ctx.fill();
      ctx.strokeStyle = '#fff'; ctx.lineWidth = 1;
      ctx.stroke();
    });

    // Draw index numbers
    if (!bgFillMode) {
      bgFillPoints.forEach((p, i) => {
        ctx.fillStyle = '#fff'; ctx.font = '11px sans-serif';
        ctx.fillText(i + 1, p.x + 6, p.y - 6);
      });
    }
  }

  if (cameraStream && cameraStream.active) {
    requestAnimationFrame(drawFillFrame);
  }
}

document.getElementById('camFillCanvas').addEventListener('mousedown', (e) => {
  if (bgMethod !== 'fill' || !cameraStream) return;
  if (bgFillMode) return;
  const pos = canvasPos(e, e.target);
  bgFillPoints.push({ x: pos.x, y: pos.y });
  document.getElementById('camFillStatus').textContent =
    `已添加顶点 ${bgFillPoints.length} 个，双击最后一个顶点闭合多边形`;
});
document.getElementById('camFillCanvas').addEventListener('mousemove', (e) => {
  if (bgMethod !== 'fill' || bgFillPoints.length === 0 || bgFillMode) return;
  const pos = canvasPos(e, e.target);
  const canvas = e.target;
  const ctx = canvas.getContext('2d');
  const fillVideo = document.getElementById('camFillVideo');
  if (fillVideo && fillVideo.readyState >= 2) {
    ctx.drawImage(fillVideo, 0, 0, canvas.width, canvas.height);
  }
  // Redraw polygon with preview line to cursor
  ctx.strokeStyle = '#FF9800'; ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(bgFillPoints[0].x, bgFillPoints[0].y);
  for (let i = 1; i < bgFillPoints.length; i++) {
    ctx.lineTo(bgFillPoints[i].x, bgFillPoints[i].y);
  }
  ctx.lineTo(pos.x, pos.y);
  ctx.stroke();
  bgFillPoints.forEach((p, i) => {
    ctx.beginPath();
    ctx.arc(p.x, p.y, 4, 0, Math.PI * 2);
    ctx.fillStyle = i === 0 ? '#4CAF50' : '#FF9800';
    ctx.fill();
    ctx.strokeStyle = '#fff'; ctx.lineWidth = 1;
    ctx.stroke();
    ctx.fillStyle = '#fff'; ctx.font = '11px sans-serif';
    ctx.fillText(i + 1, p.x + 6, p.y - 6);
  });
});
document.getElementById('camFillCanvas').addEventListener('dblclick', (e) => {
  if (bgMethod !== 'fill' || bgFillMode) return;
  e.preventDefault();
  closeFillPolygon();
});

function closeFillPolygon() {
  if (bgFillPoints.length < 3) {
    toast('需要至少3个顶点，继续添加吧', 'warn');
    return;
  }
  bgFillMode = true;
  document.getElementById('camFillStatus').textContent = '✅ 多边形已闭合，点击"生成背景"完成';
}

function applyFillBg() {
  if (bgFillPoints.length < 3) { toast('请用多边形圈出动物位置（需要至少3个顶点）', 'warn'); return; }

  const canvas = document.getElementById('camFillCanvas');
  const ctx = canvas.getContext('2d');

  // Draw raw video frame (clear overlay polygons/lines before reading pixels)
  const fillVideo = document.getElementById('camFillVideo');
  if (fillVideo && fillVideo.readyState >= 2) {
    ctx.drawImage(fillVideo, 0, 0, canvas.width, canvas.height);
  }

  const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
  const w = canvas.width;
  const h = canvas.height;
  const workData = new Uint8ClampedArray(imageData.data);

  // Step 1: Build mask — -1=outside polygon, 0=inside needs fill
  const mask = new Int32Array(w * h);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      mask[y * w + x] = pointInPolygon(x, y, bgFillPoints) ? 0 : -1;
    }
  }

  // Step 2: BFS to compute distance-to-boundary for each interior pixel
  const pixels = [];
  for (let y = 1; y < h - 1; y++) {
    for (let x = 1; x < w - 1; x++) {
      if (mask[y * w + x] !== 0) continue;
      let isBoundary = false;
      for (let dy = -1; dy <= 1 && !isBoundary; dy++) {
        for (let dx = -1; dx <= 1 && !isBoundary; dx++) {
          if (dx === 0 && dy === 0) continue;
          if (mask[(y + dy) * w + (x + dx)] === -1) {
            isBoundary = true;
          }
        }
      }
      if (isBoundary) {
        mask[y * w + x] = 1;
        pixels.push({ x, y, dist: 1 });
      }
    }
  }

  let head = 0;
  while (head < pixels.length) {
    const { x, y, dist } = pixels[head++];
    for (let dy = -1; dy <= 1; dy++) {
      for (let dx = -1; dx <= 1; dx++) {
        if (dx === 0 && dy === 0) continue;
        const nx = x + dx, ny = y + dy;
        if (nx < 0 || nx >= w || ny < 0 || ny >= h) continue;
        if (mask[ny * w + nx] !== 0) continue;
        mask[ny * w + nx] = dist + 1;
        pixels.push({ x: nx, y: ny, dist: dist + 1 });
      }
    }
  }

  // Step 3: Fill pixels from closest to farthest from boundary
  pixels.sort((a, b) => a.dist - b.dist);
  for (const { x, y, dist } of pixels) {
    const kernelSize = dist <= 2 ? 3 : dist <= 5 ? 5 : 7;
    const half = Math.floor(kernelSize / 2);
    let cr = 0, cg = 0, cb = 0, cw = 0;
    for (let dy = -half; dy <= half; dy++) {
      for (let dx = -half; dx <= half; dx++) {
        if (dx === 0 && dy === 0) continue;
        const nx = x + dx, ny = y + dy;
        if (nx < 0 || nx >= w || ny < 0 || ny >= h) continue;
        if (mask[ny * w + nx] === -1 || mask[ny * w + nx] < dist) {
          const weight = 1 / (Math.abs(dx) + Math.abs(dy) + 1);
          const ni = (ny * w + nx) * 4;
          cr += workData[ni] * weight;
          cg += workData[ni + 1] * weight;
          cb += workData[ni + 2] * weight;
          cw += weight;
        }
      }
    }
    if (cw > 0) {
      const di = (y * w + x) * 4;
      workData[di] = Math.round(cr / cw);
      workData[di + 1] = Math.round(cg / cw);
      workData[di + 2] = Math.round(cb / cw);
    }
  }

  bgImageData = new ImageData(workData, w, h);
  const mainCanvas = document.getElementById('camCanvas');
  mainCanvas.width = w; mainCanvas.height = h;
  const mainCtx = mainCanvas.getContext('2d');
  mainCtx.putImageData(bgImageData, 0, 0);
  drawZones();
  saveBackgroundImage();
  document.getElementById('camFillStatus').textContent = '✅ 背景已生成（分层扩张填充）';
  document.getElementById('camFillStatus').style.color = '#4CAF50';
  toast('背景已生成', 'success');
  releaseBgCamera();
  updateBgConfiguredBadge();
}

function canvasPos(e, canvas) {
  const rect = canvas.getBoundingClientRect();
  const scaleX = canvas.width / rect.width;
  const scaleY = canvas.height / rect.height;
  return { x: (e.clientX - rect.left) * scaleX, y: (e.clientY - rect.top) * scaleY };
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
    if (cm2 >= 1) return cm2.toFixed(1) + ' cm²';
    const mm2 = cm2 * 100;
    return mm2.toFixed(0) + ' mm²';
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

function deleteZoneByIndex(idx) {
  if (idx < 0 || idx >= zones.length) return;
  const name = zones[idx].name;
  if (!confirm(`确认移除区域「${name}」？`)) return;
  zones.splice(idx, 1);
  if (Array.isArray(eventRules)) {
    eventRules = eventRules.filter(r => r.zone !== name);
  }
  zoneDrawMode = false; zonePoints = [];
  drawZones(); updateZoneList();
  toast('已移除区域「' + name + '」', 'warn');
}

function renameZone(idx, newName) {
  if (idx < 0 || idx >= zones.length) return;
  const oldName = zones[idx].name;
  zones[idx].name = newName;
  if (Array.isArray(eventRules)) {
    eventRules.forEach(r => { if (r.zone === oldName) r.zone = newName; });
  }
  drawZones();
  updateZoneList();
}

function clearAllZones() {
  if (zones.length === 0) return;
  if (!confirm('确认清除全部 ' + zones.length + ' 个区域？')) return;
  zones = [];
  zoneDrawMode = false; zonePoints = [];
  drawZones(); updateZoneList();
  toast('已清除全部区域', 'warn');
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

    const pxArea = polygonArea(z.points);
    const areaStr = areaDisplay(pxArea);
    ctx.fillStyle = z.color;
    ctx.font = '11px sans-serif';
    ctx.fillText(areaStr, p0.x + 6, p0.y - 35);

    ctx.fillStyle = z.color;
    const labelW = ctx.measureText(z.name).width + 12;
    ctx.fillRect(p0.x, p0.y - 20, labelW, 20);
    ctx.fillStyle = 'white';
    ctx.fillText(z.name, p0.x + 6, p0.y - 16);

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
  if (zonePoints.length < 3) { toast('至少需要3个顶点，请继续添加', 'warn'); return; }
  const idx = zones.length;
  zones.push({
    id: 'zone_' + idx,
    name: '区域 ' + String.fromCharCode(65 + idx),
    points: [...zonePoints],
    color: ZONE_COLORS[idx % ZONE_COLORS.length],
    events: {
      enter: { enabled: true, role: 'trigger' },
      leave: { enabled: true, role: 'trigger' },
      accumulate: { enabled: false, n: 5, role: 'trigger' },
      dwell: { enabled: false, seconds: 3, role: 'trigger' },
    },
  });
  zoneDrawMode = false;
  zonePoints = [];
  document.getElementById('camCanvas').style.cursor = 'default';
  drawZones(); updateZoneList();
  toast('已添加 ' + zones[zones.length - 1].name, 'success');
}

function getZoneEvents(idx) {
  if (!zones[idx].events) {
    zones[idx].events = {
      enter: { enabled: true, role: 'trigger' },
      leave: { enabled: true, role: 'trigger' },
      accumulate: { enabled: false, n: 5, role: 'trigger' },
      dwell: { enabled: false, seconds: 3, role: 'trigger' },
    };
  }
  return zones[idx].events;
}

function updateZoneEvent(idx, eventType, field, value) {
  const events = getZoneEvents(idx);
  if (!events[eventType]) events[eventType] = {};
  events[eventType][field] = value;
  if (field === 'enabled' && value === false && eventType === 'accumulate') {
    events.accumulate.n = 5;
  }
  if (field === 'enabled' && value === false && eventType === 'dwell') {
    events.dwell.seconds = 3;
  }
}

function updateZoneList() {
  const el = document.getElementById('zoneList');
  if (zones.length === 0) {
    el.innerHTML = '<p style="color:var(--text-secondary);font-size:12px">还没有定义检测区域，点击"添加区域"开始绘制多边形</p>';
    return;
  }
  let html = '<p style="color:var(--text-secondary);font-size:11px;margin-bottom:4px">💡 提示：右键点击区域可删除，右键点击顶点可删除顶点，拖拽顶点可移动</p>';
  zones.forEach((z, i) => {
    const pxArea = polygonArea(z.points);
    const areaStr = areaDisplay(pxArea);
    html += `<div class="flex" style="align-items:center;margin:4px 0;gap:6px">
      <span style="display:inline-block;width:12px;height:12px;border-radius:3px;background:${z.color};flex-shrink:0"></span>
      <input value="${z.name}" style="flex:1;min-width:50px;padding:2px 6px;border:1px solid var(--border);border-radius:3px;font-size:12px"
        onchange="renameZone(${i}, this.value)">
      <span style="font-size:11px;color:var(--text-secondary);white-space:nowrap">${z.points.length} 顶点 — ${areaStr}</span>
      <button class="btn btn-sm" style="padding:1px 8px;font-size:11px;color:#e74c3c;border:1px solid #e74c3c;background:transparent;border-radius:4px;flex-shrink:0" onclick="deleteZoneByIndex(${i})" title="删除此区域">✕</button>
    </div>`;
  });
  el.innerHTML = html;
  renderEventRules();
}

function renderEventRules() {
  const el = document.getElementById('zoneConfigList');
  if (!el) return;
  if (!Array.isArray(eventRules)) eventRules = [];

  if (zones.length === 0) {
    el.innerHTML = '<p style="color:var(--text-secondary);font-size:12px">请先在步骤④中定义检测区域</p>';
    return;
  }

  const eventTypes = [
    { value: 'enter', label: '进入区域' },
    { value: 'leave', label: '离开区域' },
    { value: 'accumulate', label: '累计进入N次' },
    { value: 'dwell', label: '停留超过X秒' },
  ];

  const roleOpts = [
    { value: 'trigger', label: '作为触发信号' },
    { value: 'record', label: '仅记录不触发' },
  ];

  let html = '<div style="margin-bottom:8px;font-size:12px;color:var(--text-secondary)">定义事件规则，每条规则由一个名称 + 区域 + 事件类型 + 用途组成。名称默认可修改：</div>';

  eventRules.forEach((r, i) => {
    const conflicts = checkDuplicateName(r.name, i);
    const dupStyle = conflicts.length > 0
      ? 'border-color:#F44336;background:#FFF5F5'
      : 'border:1px solid var(--border)';
    const dupTitle = conflicts.length > 0
      ? `⚠ 重名冲突！已存在同名事件: ${conflicts.map(c => c.name).join(', ')}`
      : '事件名称';
    const dupIcon = conflicts.length > 0
      ? '<span style="color:#F44336;font-size:14px;flex-shrink:0" title="' + dupTitle + '">⚠️</span>'
      : '';

    html += `<div class="card" style="padding:10px;margin:6px 0;display:flex;align-items:center;gap:8px;flex-wrap:wrap">
      ${dupIcon}
      <input value="${(r.name || '').replace(/"/g, '&quot;')}" placeholder="事件名称" onchange="updateEventRule(${i},'name',this.value)"
        style="flex:1;min-width:100px;padding:4px 8px;border-radius:4px;font-size:12px;${dupStyle}" title="${dupTitle}">
      <span style="color:var(--text-secondary)">|</span>
      <select onchange="updateEventRule(${i},'zone',this.value)" style="flex:1;min-width:80px;padding:4px 8px;border:1px solid var(--border);border-radius:4px;font-size:12px">`;
    zones.forEach(z => {
      const sel = z.name === r.zone ? ' selected' : '';
      html += `<option value="${z.name.replace(/"/g, '&quot;')}"${sel}>${z.name}</option>`;
    });
    html += `</select>
      <span style="color:var(--text-secondary)">→</span>
      <select onchange="updateEventRule(${i},'event',this.value)" style="flex:1;min-width:90px;padding:4px 8px;border:1px solid var(--border);border-radius:4px;font-size:12px">`;
    eventTypes.forEach(et => {
      const sel = et.value === r.event ? ' selected' : '';
      html += `<option value="${et.value}"${sel}>${et.label}</option>`;
    });
    html += `</select>
      <span style="color:var(--text-secondary)">→</span>
      <select onchange="updateEventRule(${i},'role',this.value)" style="flex:1;min-width:110px;padding:4px 8px;border:1px solid var(--border);border-radius:4px;font-size:12px">`;
    roleOpts.forEach(ro => {
      const sel = ro.value === (r.role || 'trigger') ? ' selected' : '';
      html += `<option value="${ro.value}"${sel}>${ro.label}</option>`;
    });
    html += `</select>`;
    if (r.event === 'accumulate') {
      html += `<input type="number" value="${r.n || 5}" min="1" max="999" style="width:60px;padding:4px;border:1px solid var(--border);border-radius:4px;font-size:12px" onchange="updateEventRule(${i},'n',parseInt(this.value)||5)"><span style="font-size:11px;color:var(--text-secondary)">次</span>`;
    }
    if (r.event === 'dwell') {
      html += `<input type="number" value="${r.seconds || 3}" min="0.1" step="0.1" max="999" style="width:60px;padding:4px;border:1px solid var(--border);border-radius:4px;font-size:12px" onchange="updateEventRule(${i},'seconds',parseFloat(this.value)||3)"><span style="font-size:11px;color:var(--text-secondary)">秒</span>`;
    }
    html += `<button onclick="deleteEventRule(${i})" style="padding:2px 8px;font-size:11px;color:#e74c3c;border:1px solid #e74c3c;background:transparent;border-radius:4px;flex-shrink:0">✕</button>
    </div>`;
  });

  html += `<button onclick="addEventRule()" class="btn btn-sm btn-primary" style="margin-top:4px">＋ 新增事件条目</button>`;
  el.innerHTML = html;
}

function checkDuplicateName(name, excludeIndex) {
  const conflicts = [];
  if (!Array.isArray(eventRules)) return conflicts;
  eventRules.forEach((r, i) => {
    if (i !== excludeIndex && r.name === name) {
      conflicts.push({ index: i, name: r.name, zone: r.zone, event: r.event });
    }
  });
  return conflicts;
}

function defaultEventName(zone, event, n, seconds, excludeIndex) {
  let base;
  if (event === 'enter') base = `${zone}-进入`;
  else if (event === 'leave') base = `${zone}-离开`;
  else if (event === 'accumulate') base = `${zone}-累计${n || 5}次`;
  else if (event === 'dwell') base = `${zone}-停留${seconds || 3}秒`;
  else base = `${zone}-事件`;
  let name = base;
  let counter = 2;
  while (checkDuplicateName(name, excludeIndex).length > 0) {
    name = `${base}_${counter}`;
    counter++;
  }
  return name;
}

function resolveDupName(rawName, excludeIndex) {
  let name = rawName;
  let counter = 2;
  while (checkDuplicateName(name, excludeIndex).length > 0) {
    name = `${rawName}_${counter}`;
    counter++;
  }
  return name;
}

function findEventRuleName(zone, eventType) {
  if (!Array.isArray(eventRules)) return null;
  const rule = eventRules.find(r => r.zone === zone && r.event === eventType);
  return rule ? rule.name : null;
}

function addEventRule() {
  if (zones.length === 0) { toast('请先在步骤④中定义检测区域', 'warn'); return; }
  if (!Array.isArray(eventRules)) eventRules = [];
  const zone = zones[0].name;
  const event = 'enter';
  const idx = eventRules.length;
  eventRules.push({ zone, event, role: 'trigger', name: defaultEventName(zone, event, null, null, idx) });
  renderEventRules();
}

function deleteEventRule(idx) {
  if (idx < 0 || idx >= eventRules.length) return;
  eventRules.splice(idx, 1);
  renderEventRules();
}

function updateEventRule(idx, field, value) {
  if (!eventRules[idx]) return;
  eventRules[idx][field] = value;
  if (field === 'event') {
    if (value !== 'accumulate') delete eventRules[idx].n;
    if (value !== 'dwell') delete eventRules[idx].seconds;
  }
  if (field === 'zone' || field === 'event' || field === 'n' || field === 'seconds') {
    eventRules[idx].name = defaultEventName(
      eventRules[idx].zone,
      eventRules[idx].event,
      eventRules[idx].n,
      eventRules[idx].seconds,
      idx,
    );
  }
  if (field === 'name') {
    const resolved = resolveDupName(value, idx);
    if (resolved !== value) {
      eventRules[idx].name = resolved;
    }
  }
  renderEventRules();
}

async function saveBackgroundImage() {
  if (!bgImageData) return;
  try {
    const canvas = document.createElement('canvas');
    canvas.width = bgImageData.width;
    canvas.height = bgImageData.height;
    const ctx = canvas.getContext('2d');
    ctx.putImageData(bgImageData, 0, 0);
    const b64 = canvas.toDataURL('image/png');
    await fetch('/api/camera/background', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image: b64, experiment_id: currentExperimentId }),
    });
  } catch (e) { /* best effort */ }
}

async function loadBackgroundImage() {
  try {
    let url = '/api/camera/background';
    if (currentExperimentId) url += '?experiment_id=' + encodeURIComponent(currentExperimentId);
    const resp = await fetch(url);
    if (!resp.ok) return null;
    const blob = await resp.blob();
    const img = new Image();
    return new Promise((resolve) => {
      img.onload = () => {
        const canvas = document.createElement('canvas');
        canvas.width = img.width;
        canvas.height = img.height;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(img, 0, 0);
        resolve(ctx.getImageData(0, 0, img.width, img.height));
      };
      img.onerror = () => resolve(null);
      img.src = URL.createObjectURL(blob);
    });
  } catch (e) {
    return null;
  }
}

async function saveCameraConfig() {
  const config = {
    zones: zones.map(z => ({
      name: z.name,
      points: z.points,
      events: z.events || {
        enter: { enabled: true, role: 'trigger' },
        leave: { enabled: true, role: 'trigger' },
        accumulate: { enabled: false, n: 5, role: 'trigger' },
        dwell: { enabled: false, seconds: 3, role: 'trigger' }
      }
    })),
    contrast: contrast,
    algorithm: document.getElementById('camAlgo') ? document.getElementById('camAlgo').value : 'bgsub',
    sensitivity: document.getElementById('camSensitivity') ? parseInt(document.getElementById('camSensitivity').value) : 25,
    brightness_threshold: document.getElementById('camBrightnessThresh') ? parseInt(document.getElementById('camBrightnessThresh').value) : 30,
    obj_size_min: document.getElementById('camObjSizeMin') ? parseInt(document.getElementById('camObjSizeMin').value) : 100,
    obj_size_max: document.getElementById('camObjSizeMax') ? parseInt(document.getElementById('camObjSizeMax').value) : 5000,
    track_smooth_enabled: document.getElementById('camTrackSmooth') ? document.getElementById('camTrackSmooth').checked : false,
    track_smooth_strength: document.getElementById('camTrackSmoothStrength') ? parseInt(document.getElementById('camTrackSmoothStrength').value) : 3,
    box_smooth_enabled: document.getElementById('camBoxSmooth') ? document.getElementById('camBoxSmooth').checked : false,
    box_smooth_strength: document.getElementById('camBoxSmoothStrength') ? parseInt(document.getElementById('camBoxSmoothStrength').value) : 3,
    ruler_points: rulerPoints,
    pixels_per_cm: rulerPixelsPerCm,
    event_rules: eventRules || [],
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
        events: z.events || {
          enter: { enabled: true, role: 'trigger' },
          leave: { enabled: true, role: 'trigger' },
          accumulate: { enabled: false, n: 5, role: 'trigger' },
          dwell: { enabled: false, seconds: 3, role: 'trigger' }
        }
      }));
      if (cfg.contrast) { contrast = cfg.contrast; setContrast(cfg.contrast); }
      if (cfg.sensitivity) document.getElementById('camSensitivity').value = cfg.sensitivity;
      if (cfg.brightness_threshold) document.getElementById('camBrightnessThresh').value = cfg.brightness_threshold;
      if (cfg.obj_size_min || cfg.min_area) {
        document.getElementById('camObjSizeMin').value = cfg.obj_size_min || cfg.min_area || 100;
        document.getElementById('camObjSizeMinVal').textContent = document.getElementById('camObjSizeMin').value;
      }
      if (cfg.obj_size_max) {
        document.getElementById('camObjSizeMax').value = cfg.obj_size_max;
        document.getElementById('camObjSizeMaxVal').textContent = document.getElementById('camObjSizeMax').value;
      }
      if (cfg.track_smooth_enabled !== undefined) {
        document.getElementById('camTrackSmooth').checked = cfg.track_smooth_enabled;
        document.getElementById('camTrackSmoothStrength').disabled = !cfg.track_smooth_enabled;
      }
      if (cfg.track_smooth_strength) {
        document.getElementById('camTrackSmoothStrength').value = cfg.track_smooth_strength;
        document.getElementById('camTrackSmoothStrengthVal').textContent = cfg.track_smooth_strength;
      }
      if (cfg.box_smooth_enabled !== undefined) {
        document.getElementById('camBoxSmooth').checked = cfg.box_smooth_enabled;
        document.getElementById('camBoxSmoothStrength').disabled = !cfg.box_smooth_enabled;
      }
      if (cfg.box_smooth_strength) {
        document.getElementById('camBoxSmoothStrength').value = cfg.box_smooth_strength;
        document.getElementById('camBoxSmoothStrengthVal').textContent = cfg.box_smooth_strength;
      }
      drawZones(); updateZoneList();
    }
    if (cfg.event_rules && Array.isArray(cfg.event_rules)) {
      eventRules = cfg.event_rules;
    } else {
      eventRules = [];
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

async function saveCameraConfigManual() {
  await saveCameraConfig();
  toast('配置已保存', 'success');
  updateViewConfigButton();
}

async function updateViewConfigButton() {
   const btn = document.getElementById('btnViewConfig');
   if (!btn) return;
   try {
     let url = '/api/camera/config/exists';
     if (currentExperimentId) url += '?experiment_id=' + encodeURIComponent(currentExperimentId);
     const resp = await fetch(url);
     const data = await resp.json();
     btn.disabled = !data.exists;
     btn.title = data.exists ? '打开配置文件: ' + data.path : '请先保存配置后再查看';
   } catch (e) {
     btn.disabled = true;
   }
 }

function viewCameraConfig() {
  let url = '/api/camera/config/view';
  if (currentExperimentId) url += '?experiment_id=' + encodeURIComponent(currentExperimentId);
  window.open(url, '_blank');
}

function setCameraExperiment(expId, expName, cameraEnabled) {
  currentExperimentId = expId;
  currentExperimentName = expName || '';
  cameraExperimentEnabled = !!cameraEnabled;
  updateCameraTabAccess();
  // 同步更新流程编辑器的访问状态
  if (typeof updateFlowEditorAccess === 'function') {
    updateFlowEditorAccess();
  }

  // Full reset: clear all in-memory state before loading new experiment's config
  if (detectInterval) { clearInterval(detectInterval); detectInterval = null; _detectionPaused = false; }
  if (trackPreviewInterval) { clearInterval(trackPreviewInterval); trackPreviewInterval = null; }
  if (cameraStream) { cameraStream.getTracks().forEach(t => t.stop()); cameraStream = null; }
  document.getElementById('btnStopDetection').disabled = true;
  document.getElementById('btnStartDetection').disabled = false;
  document.getElementById('btnStopTrackPreview').disabled = true;
  document.getElementById('btnStartTrackPreview').disabled = false;
  const previewCanvas = document.getElementById('camDetectPreview');
  if (previewCanvas) { previewCanvas.style.display = 'none'; }

  cameraStep = 0;
  bgMethod = 'auto';
  zones = [];
  bgImageData = null;
  bgFillPoints = [];
  bgFillMode = false;
  rulerPoints = [];
  rulerPixelsPerCm = null;
  eventRules = [];
  _smoothPrev = { cx: null, cy: null, minX: null, minY: null, maxX: null, maxY: null };

  // Sync bgMethod UI
  document.getElementById('bgMethodAuto').className = 'btn btn-sm btn-primary';
  document.getElementById('bgMethodFill').className = 'btn btn-sm';
  document.getElementById('bgAutoArea').style.display = 'block';
  document.getElementById('bgFillArea').style.display = 'none';

  // Reset step navigation UI to step 0
  document.querySelectorAll('.camera-step').forEach(el => el.classList.remove('active'));
  document.getElementById('camStep0').classList.add('active');
  document.querySelectorAll('.camera-step-dot').forEach(d => {
    d.classList.remove('active', 'done');
    if (parseInt(d.dataset.step) === 0) d.classList.add('active');
  });
  document.getElementById('cameraStepTitle').textContent = '第 1 步：选择摄像头';
  document.getElementById('camPrev').disabled = true;

  // Clear fill canvas
  const fillCanvas = document.getElementById('camFillCanvas');
  if (fillCanvas) {
    const fctx = fillCanvas.getContext('2d');
    fctx.fillStyle = '#000';
    fctx.fillRect(0, 0, fillCanvas.width || 640, fillCanvas.height || 480);
  }
  const fillStatus = document.getElementById('camFillStatus');
  if (fillStatus) fillStatus.textContent = '';

  drawZones();
  updateZoneList();
  loadCameraConfig().then(() => {
    updateZoneList();
    renderEventRules();
  });
  loadBackgroundImage().then(data => {
    if (data) {
      bgImageData = data;
      const cvs = document.getElementById('camCanvas');
      if (cvs) { cvs.width = data.width; cvs.height = data.height; }
      drawZones();
      updateBgConfiguredBadge();
    }
  });
  // Initialize pixel area slider ranges with a default 640x480 resolution
  // Actual resolution will override when a camera stream starts
  updateObjSizeRange(640, 480);
}

function updateCameraTabAccess() {
  const hasExp = !!currentExperimentId;
  const cameraOk = hasExp && cameraExperimentEnabled;
  const badge = document.getElementById('cameraExpBadge');

  if (badge) {
    if (!hasExp) {
      badge.textContent = '📋 请先在实验管理中「编辑」或「启动」一个含摄像头的实验';
      badge.style.display = 'block';
      badge.style.background = '#FFF3CD';
      badge.style.color = '#856404';
    } else if (!cameraExperimentEnabled) {
      badge.textContent = '📋 当前实验未启用摄像头，摄像头标签页不可用。请创建含摄像头的实验。';
      badge.style.display = 'block';
      badge.style.background = '#FFF3CD';
      badge.style.color = '#856404';
    } else {
      badge.textContent = '📋 当前实验: ' + currentExperimentName;
      badge.style.display = 'block';
      badge.style.background = '#E3F2FD';
      badge.style.color = '#1565C0';
    }
  }

  const camTab = document.querySelector('[data-tab="camera"]');
  if (camTab) {
    if (!cameraOk) {
      camTab.classList.add('tab-disabled');
      camTab.style.opacity = '0.5';
      camTab.style.pointerEvents = 'none';
      camTab.title = '请先进入一个启用了摄像头的实验';
    } else {
      camTab.classList.remove('tab-disabled');
      camTab.style.opacity = '1';
      camTab.style.pointerEvents = 'auto';
      camTab.title = '';
    }
  }

  // 灰色覆盖层：无实验或无摄像头时遮挡全部内容
  const overlay = document.getElementById('cameraOverlay');
  const overlayText = document.getElementById('cameraOverlayText');
  if (overlay) {
    if (!cameraOk) {
      overlay.style.display = 'flex';
      if (overlayText) {
        if (!hasExp) {
          overlayText.textContent = '请先在实验管理中「编辑」或「启动」一个实验';
        } else if (!cameraExperimentEnabled) {
          overlayText.textContent = '当前实验未启用摄像头，请创建含摄像头的实验';
        }
      }
    } else {
      overlay.style.display = 'none';
    }
  }

  document.getElementById('camNext').disabled = !cameraOk;
  document.getElementById('camPrev').disabled = !cameraOk || cameraStep === 0;
  document.getElementById('camSelect').disabled = !cameraOk;
  document.getElementById('btnCaptureBg').disabled = !cameraOk;
  document.getElementById('btnStartDetection').disabled = !cameraOk;

  const bgMethodAuto = document.getElementById('bgMethodAuto');
  const bgMethodFill = document.getElementById('bgMethodFill');
  if (bgMethodAuto) bgMethodAuto.disabled = !cameraOk;
  if (bgMethodFill) bgMethodFill.disabled = !cameraOk;
}

// Called by app.js tab switch to release camera resources when leaving camera tab
function releaseCamera() {
  if (detectInterval) { clearInterval(detectInterval); detectInterval = null; _detectionPaused = false; }
  if (trackPreviewInterval) { clearInterval(trackPreviewInterval); trackPreviewInterval = null; }
  if (cameraStream) { cameraStream.getTracks().forEach(t => t.stop()); cameraStream = null; }
  document.getElementById('btnStopDetection').disabled = true;
  document.getElementById('btnStartDetection').disabled = false;
  document.getElementById('btnStopTrackPreview').disabled = true;
  document.getElementById('btnStartTrackPreview').disabled = false;
  const previewCanvas = document.getElementById('camDetectPreview');
  if (previewCanvas) { previewCanvas.style.display = 'none'; }
  const trackCanvas = document.getElementById('camTrackPreview');
  if (trackCanvas) { trackCanvas.style.display = 'none'; }
  document.getElementById('cameraDetectStatus').textContent = '';
  document.getElementById('camTrackStatus').textContent = '';
}

function clearExperimentContext() {
  currentExperimentId = null;
  currentExperimentName = '';
  cameraExperimentEnabled = false;
  zones = [];
  bgImageData = null;
  rulerPoints = [];
  rulerPixelsPerCm = null;
  zoneDrawMode = false;
  zonePoints = [];
  dragZoneIdx = -1;
  dragPtIdx = -1;
  eventRules = [];
  if (detectInterval) { clearInterval(detectInterval); detectInterval = null; }
  if (trackPreviewInterval) { clearInterval(trackPreviewInterval); trackPreviewInterval = null; }
  if (cameraStream) { cameraStream.getTracks().forEach(t => t.stop()); cameraStream = null; }
  document.getElementById('btnStopDetection').disabled = true;
  document.getElementById('cameraDetectStatus').textContent = '';
  const previewCanvas = document.getElementById('camDetectPreview');
  if (previewCanvas) {
    previewCanvas.style.display = 'none';
  }
  const trackCanvas = document.getElementById('camTrackPreview');
  if (trackCanvas) {
    trackCanvas.style.display = 'none';
  }
  drawZones();
  updateZoneList();
  drawRulerCanvas();
  updateCameraTabAccess();
  // 同步更新流程编辑器的访问状态
  if (typeof updateFlowEditorAccess === 'function') {
    updateFlowEditorAccess();
  }
}

// --- Blob / connected-component extraction ---
function extractBlob(data, width, height, threshold) {
  const h = height, w = width;
  const visited = new Uint8Array(w * h);
  const blobs = [];

  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const idx = y * w + x;
      if (visited[idx]) continue;
      const i = idx * 4;
      if (data[i] !== 255 && data[i + 1] !== 255) continue;

      let minX = x, maxX = x, minY = y, maxY = y;
      let sumX = 0, sumY = 0, count = 0;
      const stack = [[x, y]];
      visited[idx] = 1;

      while (stack.length > 0) {
        const [cx, cy] = stack.pop();
        sumX += cx; sumY += cy; count++;
        if (cx < minX) minX = cx; if (cx > maxX) maxX = cx;
        if (cy < minY) minY = cy; if (cy > maxY) maxY = cy;

        for (const [dx, dy] of [[-1,0],[1,0],[0,-1],[0,1],[ -1,-1],[-1,1],[1,-1],[1,1]]) {
          const nx = cx + dx, ny = cy + dy;
          if (nx < 0 || nx >= w || ny < 0 || ny >= h) continue;
          const nidx = ny * w + nx;
          if (visited[nidx]) continue;
          const ni = nidx * 4;
          if (data[ni] === 255 || data[ni + 1] === 255) {
            visited[nidx] = 1;
            stack.push([nx, ny]);
          }
        }
      }

      if (count >= 5) {
        blobs.push({
          cx: sumX / count, cy: sumY / count,
          minX, maxX, minY, maxY,
          area: count, width: maxX - minX, height: maxY - minY
        });
      }
    }
  }

  blobs.sort((a, b) => b.area - a.area);
  return blobs;
}

function findBestBlob(blobs, minArea, maxArea, contrastDir) {
  if (blobs.length === 0) return null;
  const filtered = blobs.filter(b => b.area >= minArea && b.area <= maxArea);
  if (filtered.length === 0) return null;
  const best = filtered[0];
  return { cx: best.cx, cy: best.cy, minX: best.minX, maxX: best.maxX, minY: best.minY, maxY: best.maxY, count: best.area };
}

function onSmoothChange() {
  const trackSmooth = document.getElementById('camTrackSmooth').checked;
  const boxSmooth = document.getElementById('camBoxSmooth').checked;
  document.getElementById('camTrackSmoothStrength').disabled = !trackSmooth;
  document.getElementById('camBoxSmoothStrength').disabled = !boxSmooth;
  if (!trackSmooth) { _smoothPrev.cx = null; _smoothPrev.cy = null; }
  if (!boxSmooth) { _smoothPrev.minX = null; _smoothPrev.minY = null; _smoothPrev.maxX = null; _smoothPrev.maxY = null; }
}

function applySmoothing(best, type) {
  if (!best) return best;
  const alpha = type === 'track'
    ? (1 / (parseInt(document.getElementById('camTrackSmoothStrength')?.value || 3) * 0.5 + 1))
    : (1 / (parseInt(document.getElementById('camBoxSmoothStrength')?.value || 3) * 0.5 + 1));
  if (type === 'track' && document.getElementById('camTrackSmooth').checked) {
    if (_smoothPrev.cx !== null) {
      best.cx = alpha * best.cx + (1 - alpha) * _smoothPrev.cx;
      best.cy = alpha * best.cy + (1 - alpha) * _smoothPrev.cy;
    }
    _smoothPrev.cx = best.cx;
    _smoothPrev.cy = best.cy;
  }
  if (type === 'box' && document.getElementById('camBoxSmooth').checked) {
    if (_smoothPrev.minX !== null) {
      const ba = 1 / (parseInt(document.getElementById('camBoxSmoothStrength')?.value || 3) * 0.5 + 1);
      best.minX = ba * best.minX + (1 - ba) * _smoothPrev.minX;
      best.minY = ba * best.minY + (1 - ba) * _smoothPrev.minY;
      best.maxX = ba * best.maxX + (1 - ba) * _smoothPrev.maxX;
      best.maxY = ba * best.maxY + (1 - ba) * _smoothPrev.maxY;
    }
    _smoothPrev.minX = best.minX;
    _smoothPrev.minY = best.minY;
    _smoothPrev.maxX = best.maxX;
    _smoothPrev.maxY = best.maxY;
  }
  return best;
}

// --- Tracking parameter preview (Step 6) ---
function startTrackStepCamera() {
  const deviceId = document.getElementById('camSelect').value;
  if (!deviceId) { toast('请先选择摄像头', 'warn'); return; }
  if (cameraStream) {
    cameraStream.getTracks().forEach(t => t.stop());
    cameraStream = null;
  }
  navigator.mediaDevices.getUserMedia({
    video: { deviceId: { exact: deviceId }, width: { ideal: 640 }, height: { ideal: 480 } },
    audio: false,
  }).then(stream => {
    cameraStream = stream;
    const track = stream.getVideoTracks()[0];
    if (track) {
      const settings = track.getSettings();
      if (settings.width && settings.height) {
        updateObjSizeRange(settings.width, settings.height);
      }
    }
  }).catch(e => {
    toast('摄像头暂未就绪，可以重试', 'error');
  });
}

function releaseTrackCamera() {
  if (trackPreviewInterval) { clearInterval(trackPreviewInterval); trackPreviewInterval = null; }
  if (cameraStream) {
    cameraStream.getTracks().forEach(t => t.stop());
    cameraStream = null;
  }
  const canvas = document.getElementById('camTrackPreview');
  if (canvas) canvas.style.display = 'none';
  document.getElementById('btnStartTrackPreview').disabled = false;
  document.getElementById('btnStopTrackPreview').disabled = true;
  document.getElementById('camTrackStatus').textContent = '';
}

function updateObjSizeRange(videoWidth, videoHeight) {
  const totalPixels = videoWidth * videoHeight;
  if (!totalPixels || totalPixels <= 0) return;
  const minSlider = document.getElementById('camObjSizeMin');
  const maxSlider = document.getElementById('camObjSizeMax');
  const minMax = Math.floor(totalPixels * 0.5);
  // Min area slider: range [10, 50% of total_pixels]
  if (minSlider) {
    minSlider.min = 10;
    minSlider.max = minMax;
    const val = parseInt(minSlider.value);
    if (val < minSlider.min) { minSlider.value = minSlider.min; }
    if (val > minSlider.max) { minSlider.value = minSlider.max; }
    const valEl = document.getElementById('camObjSizeMinVal');
    if (valEl) valEl.textContent = minSlider.value;
  }
  // Max area slider: range [100, total_pixels]
  if (maxSlider) {
    maxSlider.min = 100;
    maxSlider.max = totalPixels;
    const val = parseInt(maxSlider.value);
    if (val < maxSlider.min) { maxSlider.value = maxSlider.min; }
    if (val > maxSlider.max) { maxSlider.value = maxSlider.max; }
    const valEl = document.getElementById('camObjSizeMaxVal');
    if (valEl) valEl.textContent = maxSlider.value;
  }
  const infoEl = document.getElementById('camObjSizeInfo');
  if (infoEl) infoEl.textContent = `帧大小 ${videoWidth}x${videoHeight} = ${totalPixels.toLocaleString()} 像素 | 下限最大 ${minMax.toLocaleString()} | 上限最大 ${totalPixels.toLocaleString()}`;
}

async function startTrackPreview() {
  if (trackPreviewInterval) { clearInterval(trackPreviewInterval); trackPreviewInterval = null; }
  if (!bgImageData) { toast('请先完成背景建模', 'warn'); return; }
  const deviceId = document.getElementById('camSelect').value;
  if (!deviceId) { toast('请先选择摄像头', 'warn'); return; }

  document.getElementById('btnStartTrackPreview').disabled = true;
  document.getElementById('btnStopTrackPreview').disabled = false;

  const canvas = document.getElementById('camTrackPreview');
  canvas.style.display = 'block';
  canvas.width = bgImageData.width;
  canvas.height = bgImageData.height;
  const ctx = canvas.getContext('2d');
  ctx.font = '13px sans-serif';

  try {
    if (!cameraStream || !cameraStream.active) {
      cameraStream = await navigator.mediaDevices.getUserMedia({
        video: { deviceId: { exact: deviceId }, width: { ideal: 640 }, height: { ideal: 480 } },
        audio: false,
      });
    }
    const video = document.createElement('video');
    video.muted = true;
    video.srcObject = cameraStream;
    video.width = canvas.width;
    video.height = canvas.height;
    await video.play();
    const track = cameraStream.getVideoTracks()[0];
    if (track) {
      const settings = track.getSettings();
      if (settings.width && settings.height) {
        updateObjSizeRange(settings.width, settings.height);
      }
    }

    const bgData = bgImageData.data;

    const offscreen = document.createElement('canvas');
    offscreen.width = canvas.width;
    offscreen.height = canvas.height;
    const offCtx = offscreen.getContext('2d');
    offCtx.font = '13px sans-serif';

    let prevFrame = null;
    let detectCount = 0;

    trackPreviewInterval = setInterval(() => {
      // 每帧从 DOM 读取当前参数值，确保滑块调整实时生效
      const sensitivity = parseInt(document.getElementById('camSensitivity').value);
      const brightnessThresh = parseInt(document.getElementById('camBrightnessThresh')?.value || 30);
      const algo = document.getElementById('camAlgo').value;
      const threshLow = parseInt(document.getElementById('camThreshLow')?.value || 30);
      const threshHigh = parseInt(document.getElementById('camThreshHigh')?.value || 220);
      const erosionIters = parseInt(document.getElementById('camContourErosion')?.value || 1);
      const dilateIters = parseInt(document.getElementById('camContourDilate')?.value || 2);
      const objSizeMin = parseInt(document.getElementById('camObjSizeMin')?.value || 100);
      const objSizeMax = parseInt(document.getElementById('camObjSizeMax')?.value || 5000);

      offCtx.drawImage(video, 0, 0, offscreen.width, offscreen.height);
      const frame = offCtx.getImageData(0, 0, offscreen.width, offscreen.height);
      const data = frame.data;
      const w = offscreen.width, h = offscreen.height;
      const motionMask = new Uint8ClampedArray(w * h * 4);

      for (let i = 0; i < data.length; i += 4) {
        let isMotion = false;
        if (algo === 'bgsub') {
          const diff = Math.abs(data[i] - bgData[i]) + Math.abs(data[i + 1] - bgData[i + 1]) + Math.abs(data[i + 2] - bgData[i + 2]);
          const lum = 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
          const bgLum = 0.299 * bgData[i] + 0.587 * bgData[i + 1] + 0.114 * bgData[i + 2];
          const lumDiff = Math.abs(lum - bgLum);
          isMotion = lumDiff > brightnessThresh && diff > sensitivity * 1.5;
        } else if (algo === 'graythresh') {
          const lum = 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
          const bgLum = 0.299 * bgData[i] + 0.587 * bgData[i + 1] + 0.114 * bgData[i + 2];
          const lumDiff = contrast === 'dark' ? (bgLum - lum) : (lum - bgLum);
          isMotion = lumDiff > brightnessThresh && lum > threshLow && lum < threshHigh;
        } else if (algo === 'silhouette' && prevFrame) {
          const diff = Math.abs(data[i] - prevFrame.data[i]) + Math.abs(data[i + 1] - prevFrame.data[i + 1]) + Math.abs(data[i + 2] - prevFrame.data[i + 2]);
          isMotion = diff > sensitivity * 2;
        }
        if (isMotion) {
          motionMask[i] = 255; motionMask[i + 1] = 255; motionMask[i + 2] = 255; motionMask[i + 3] = 255;
        }
      }

      // Morphological ops (simulated via neighbor checks)
      let morphMask = new Uint8ClampedArray(motionMask);
      for (let iter = 0; iter < erosionIters; iter++) {
        const eroded = new Uint8ClampedArray(w * h * 4);
        for (let y = 1; y < h - 1; y++) {
          for (let x = 1; x < w - 1; x++) {
            const i = (y * w + x) * 4;
            if (morphMask[i] !== 255) continue;
            let allWhite = true;
            for (let dy = -1; dy <= 1; dy++) {
              for (let dx = -1; dx <= 1; dx++) {
                if (morphMask[((y + dy) * w + (x + dx)) * 4] !== 255) { allWhite = false; break; }
              }
              if (!allWhite) break;
            }
            if (allWhite) { eroded[i] = 255; eroded[i + 1] = 255; eroded[i + 2] = 255; eroded[i + 3] = 255; }
          }
        }
        morphMask = eroded;
      }
      for (let iter = 0; iter < dilateIters; iter++) {
        const dilated = new Uint8ClampedArray(w * h * 4);
        for (let y = 0; y < h; y++) {
          for (let x = 0; x < w; x++) {
            const i = (y * w + x) * 4;
            if (morphMask[i] === 255) { dilated[i] = 255; dilated[i + 1] = 255; dilated[i + 2] = 255; dilated[i + 3] = 255; continue; }
            let hasNeighbor = false;
            for (let dy = -1; dy <= 1; dy++) {
              for (let dx = -1; dx <= 1; dx++) {
                const nx = x + dx, ny = y + dy;
                if (nx >= 0 && nx < w && ny >= 0 && ny < h && morphMask[(ny * w + nx) * 4] === 255) { hasNeighbor = true; break; }
              }
              if (hasNeighbor) break;
            }
            if (hasNeighbor) { dilated[i] = 255; dilated[i + 1] = 255; dilated[i + 2] = 255; dilated[i + 3] = 255; }
          }
        }
        morphMask = dilated;
      }

      const blobs = extractBlob(morphMask, w, h, 5);
      let best = findBestBlob(blobs, Math.max(5, objSizeMin), objSizeMax, contrast);
      best = applySmoothing(best, 'track');
      best = applySmoothing(best, 'box');

      // Render: draw frame + motion overlay + detection on offscreen canvas
      for (let i = 0; i < morphMask.length; i += 4) {
        if (morphMask[i] === 255) {
          data[i] = Math.min(255, data[i] + 80);
          data[i + 1] = Math.max(0, data[i + 1] - 40);
          data[i + 2] = Math.max(0, data[i + 2] - 40);
        }
      }
      offCtx.putImageData(frame, 0, 0);

      // Draw zones
      zones.forEach(z => {
        if (!z.points || z.points.length < 3) return;
        offCtx.strokeStyle = z.color + '80'; offCtx.lineWidth = 2;
        offCtx.fillStyle = z.color + '15';
        offCtx.beginPath();
        offCtx.moveTo(z.points[0].x, z.points[0].y);
        for (let j = 1; j < z.points.length; j++) offCtx.lineTo(z.points[j].x, z.points[j].y);
        offCtx.closePath();
        offCtx.fill();
        offCtx.stroke();
        const p0 = z.points[0];
        offCtx.fillStyle = z.color;
        offCtx.fillText(z.name, p0.x + 4, p0.y - 8);
      });

      if (best) {
        detectCount++;
        offCtx.strokeStyle = '#FFD700'; offCtx.lineWidth = 2;
        offCtx.strokeRect(best.minX, best.minY, best.maxX - best.minX, best.maxY - best.minY);
        offCtx.fillStyle = '#FFD700';
        offCtx.beginPath(); offCtx.arc(best.cx, best.cy, 6, 0, Math.PI * 2); offCtx.fill();
        offCtx.fillStyle = 'white';
        offCtx.font = 'bold 13px sans-serif';
        const label = `对象: ${best.count} px²`;
        offCtx.fillText(label, best.minX, best.minY - 6);
        document.getElementById('camTrackStatus').textContent =
          `✅ 检测到动物 | 位置(${best.cx.toFixed(0)}, ${best.cy.toFixed(0)}) | 面积 ${best.count} px² | 第 ${detectCount} 帧`;
        document.getElementById('camTrackStatus').style.color = '#4CAF50';
      } else {
        document.getElementById('camTrackStatus').textContent =
          `👀 暂未检测到动物 | 可以调整灵敏度或确保动物在画面中 | 第 ${detectCount} 帧`;
        document.getElementById('camTrackStatus').style.color = '#FF9800';
      }

      // Atomic copy: draw complete offscreen composition to visible canvas
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(offscreen, 0, 0);

      prevFrame = frame;
    }, 150);
  } catch (e) {
    toast('预览暂未启动，请重试', 'error');
    document.getElementById('btnStartTrackPreview').disabled = false;
    document.getElementById('btnStopTrackPreview').disabled = true;
  }
}

function stopTrackPreview() {
  if (trackPreviewInterval) { clearInterval(trackPreviewInterval); trackPreviewInterval = null; }
  document.getElementById('btnStartTrackPreview').disabled = false;
  document.getElementById('btnStopTrackPreview').disabled = true;
  document.getElementById('camTrackStatus').textContent = '⏹ 预览已停止';
  document.getElementById('camTrackStatus').style.color = 'var(--text-secondary)';
  const canvas = document.getElementById('camTrackPreview');
  canvas.style.display = 'none';
}

// --- Detection (Step 7) ---
async function startCameraDetection() {
  if (zones.length === 0) { toast('请先添加至少一个检测区域', 'warn'); return; }
  if (!bgImageData) { toast('请先完成背景建模', 'warn'); return; }

  document.getElementById('btnStartDetection').disabled = true;
  document.getElementById('btnStopDetection').disabled = false;
  document.getElementById('camDetectionLog').style.display = 'block';
  const eventTypeLabels = { enter: '进入区域', leave: '离开区域', accumulate: '累计进入N次', dwell: '停留超过X秒' };
  const roleLabels = { trigger: '作为触发信号', record: '仅记录' };
  let initLog = '══════ 检测已启动 ══════\n';
  if (Array.isArray(eventRules) && eventRules.length > 0) {
    initLog += `📋 已定义 ${eventRules.length} 条事件规则:\n`;
    eventRules.forEach((r, i) => {
      const etLabel = eventTypeLabels[r.event] || r.event;
      const rLabel = roleLabels[r.role] || r.role;
      const param = r.event === 'accumulate' ? `(每${r.n || 5}次)` : r.event === 'dwell' ? `(${r.seconds || 3}秒)` : '';
      initLog += `  ${i + 1}. ${r.name || '未命名'} | 区域: ${r.zone} | 触发: ${etLabel}${param} | 用途: ${rLabel}\n`;
    });
    initLog += '──────────────────────────\n';
  } else {
    initLog += '💡 未配置事件规则，将自动记录进入和离开事件\n──────────────────────────\n';
  }
  document.getElementById('camEventLog').innerHTML = initLog;
  toast('摄像头检测已启动', 'success');

  const deviceId = document.getElementById('camSelect').value;
  const bgData = bgImageData.data;

  try {
    if (!cameraStream || !cameraStream.active) {
      cameraStream = await navigator.mediaDevices.getUserMedia({
        video: { deviceId: { exact: deviceId }, width: { ideal: 640 }, height: { ideal: 480 } },
        audio: false,
      });
    }
    const video = document.createElement('video');
    video.muted = true;
    video.srcObject = cameraStream; video.width = 640; video.height = 480;
    await video.play();
    updateObjSizeRange(video.videoWidth, video.videoHeight);
    const canvas = document.getElementById('camCanvas');
    const previewCanvas = document.getElementById('camDetectPreview');
    const analysisCanvas = document.createElement('canvas');
    analysisCanvas.width = canvas.width;
    analysisCanvas.height = canvas.height;
    const actx = analysisCanvas.getContext('2d');
    if (previewCanvas) {
      previewCanvas.style.display = 'block';
      previewCanvas.width = canvas.width;
      previewCanvas.height = canvas.height;
      previewCanvas.getContext('2d').font = '14px sans-serif';
    }
    const aw = analysisCanvas.width, ah = analysisCanvas.height;
    let prevFrame = null;
    let inZone = {};
    let dwellTimers = {};
    let dwellFired = {};
    let accumulateCounts = {};
    let accumulateLastFired = {};
    let enterDebounce = {};
    let leaveDebounce = {};

    detectInterval = setInterval(() => {
      // 每帧从 DOM 读取当前参数值，确保滑块调整实时生效
      const sensitivity = parseInt(document.getElementById('camSensitivity').value);
      const brightnessThresh = parseInt(document.getElementById('camBrightnessThresh')?.value || 30);
      const algo = document.getElementById('camAlgo').value;
      const threshLow = parseInt(document.getElementById('camThreshLow')?.value || 30);
      const threshHigh = parseInt(document.getElementById('camThreshHigh')?.value || 220);
      const erosionIters = parseInt(document.getElementById('camContourErosion')?.value || 1);
      const dilateIters = parseInt(document.getElementById('camContourDilate')?.value || 2);
      const objSizeMin = parseInt(document.getElementById('camObjSizeMin')?.value || 100);
      const objSizeMax = parseInt(document.getElementById('camObjSizeMax')?.value || 5000);

      actx.drawImage(video, 0, 0, aw, ah);
      const frame = actx.getImageData(0, 0, aw, ah);
      const data = frame.data;
      const motionMask = new Uint8ClampedArray(aw * ah * 4);

      for (let i = 0; i < data.length; i += 4) {
        let isMotion = false;
        if (algo === 'bgsub') {
          const diff = Math.abs(data[i] - bgData[i]) + Math.abs(data[i + 1] - bgData[i + 1]) + Math.abs(data[i + 2] - bgData[i + 2]);
          const lum = 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
          const bgLum = 0.299 * bgData[i] + 0.587 * bgData[i + 1] + 0.114 * bgData[i + 2];
          const lumDiff = Math.abs(lum - bgLum);
          isMotion = lumDiff > brightnessThresh && diff > sensitivity * 1.5;
        } else if (algo === 'graythresh') {
          const lum = 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
          const bgLum = 0.299 * bgData[i] + 0.587 * bgData[i + 1] + 0.114 * bgData[i + 2];
          const lumDiff = contrast === 'dark' ? (bgLum - lum) : (lum - bgLum);
          isMotion = lumDiff > brightnessThresh && lum > threshLow && lum < threshHigh;
        } else if (algo === 'silhouette' && prevFrame) {
          const diff = Math.abs(data[i] - prevFrame.data[i]) + Math.abs(data[i + 1] - prevFrame.data[i + 1]) + Math.abs(data[i + 2] - prevFrame.data[i + 2]);
          isMotion = diff > sensitivity * 2;
        }
        if (isMotion) {
          motionMask[i] = 255; motionMask[i + 1] = 255; motionMask[i + 2] = 255; motionMask[i + 3] = 255;
          data[i] = 255; data[i + 1] = 0; data[i + 2] = 0; data[i + 3] = 128;
        }
      }

      // Morphological ops
      let morphMask = new Uint8ClampedArray(motionMask);
      for (let iter = 0; iter < erosionIters; iter++) {
        const eroded = new Uint8ClampedArray(aw * ah * 4);
        for (let y = 1; y < ah - 1; y++) {
          for (let x = 1; x < aw - 1; x++) {
            const i = (y * aw + x) * 4;
            if (morphMask[i] !== 255) continue;
            let allWhite = true;
            for (let dy = -1; dy <= 1; dy++)
              for (let dx = -1; dx <= 1; dx++)
                if (morphMask[((y + dy) * aw + (x + dx)) * 4] !== 255) { allWhite = false; break; }
            if (allWhite) { eroded[i] = 255; eroded[i + 1] = 255; eroded[i + 2] = 255; eroded[i + 3] = 255; }
          }
        }
        morphMask = eroded;
      }
      for (let iter = 0; iter < dilateIters; iter++) {
        const dilated = new Uint8ClampedArray(aw * ah * 4);
        for (let y = 0; y < ah; y++) {
          for (let x = 0; x < aw; x++) {
            const i = (y * aw + x) * 4;
            if (morphMask[i] === 255) { dilated[i] = 255; dilated[i + 1] = 255; dilated[i + 2] = 255; dilated[i + 3] = 255; continue; }
            let hasNeighbor = false;
            for (let dy = -1; dy <= 1; dy++)
              for (let dx = -1; dx <= 1; dx++) {
                const nx = x + dx, ny = y + dy;
                if (nx >= 0 && nx < aw && ny >= 0 && ny < ah && morphMask[(ny * aw + nx) * 4] === 255) { hasNeighbor = true; break; }
              }
            if (hasNeighbor) { dilated[i] = 255; dilated[i + 1] = 255; dilated[i + 2] = 255; dilated[i + 3] = 255; }
          }
        }
        morphMask = dilated;
      }

      const blobs = extractBlob(morphMask, aw, ah, 5);
      let best = findBestBlob(blobs, Math.max(5, objSizeMin), objSizeMax, contrast);
      best = applySmoothing(best, 'track');
      best = applySmoothing(best, 'box');

      // Render preview
      const pctx = previewCanvas.getContext('2d');
      pctx.putImageData(frame, 0, 0);

      if (best && best.count > 10) {
        pctx.strokeStyle = '#FFD700'; pctx.lineWidth = 2;
        pctx.strokeRect(best.minX, best.minY, best.maxX - best.minX, best.maxY - best.minY);
        pctx.fillStyle = '#FFD700';
        pctx.beginPath(); pctx.arc(best.cx, best.cy, 6, 0, Math.PI * 2); pctx.fill();
      }

      zones.forEach((z) => {
        if (!z.points || z.points.length < 3) return;
        pctx.strokeStyle = z.color; pctx.lineWidth = 2;
        pctx.fillStyle = z.color + '30';
        pctx.beginPath();
        pctx.moveTo(z.points[0].x, z.points[0].y);
        for (let j = 1; j < z.points.length; j++) pctx.lineTo(z.points[j].x, z.points[j].y);
        pctx.closePath();
        pctx.fill(); pctx.stroke();
        const p0 = z.points[0];
        pctx.fillStyle = z.color;
        pctx.fillText(z.name, p0.x + 6, p0.y - 18);
      });

      // Zone events: center-point based judgment
      zones.forEach(z => {
        if (!z.points || z.points.length < 3) return;
        const had = inZone[z.id];
        const has = best && best.count > 10 && pointInPolygon(best.cx, best.cy, z.points);
        const DEBOUNCE_FRAMES = 3;

        if (has) {
          enterDebounce[z.id] = (enterDebounce[z.id] || 0) + 1;
          leaveDebounce[z.id] = 0;
        } else {
          leaveDebounce[z.id] = (leaveDebounce[z.id] || 0) + 1;
          enterDebounce[z.id] = 0;
        }

        if (enterDebounce[z.id] >= DEBOUNCE_FRAMES && !had) {
          inZone[z.id] = true;
          dwellTimers[z.id] = Date.now();
          dwellFired[z.id] = false;
          accumulateCounts[z.id] = (accumulateCounts[z.id] || 0) + 1;
          const posInfo = best ? `位置(${best.cx.toFixed(0)},${best.cy.toFixed(0)})` : '位置未知';
          logCam(`🧪 [进入] ${z.name} | 触发: 动物${posInfo}进入区域 | 来源: 摄像头检测 | 第${accumulateCounts[z.id]}次进入`, 'success');
          const enterRule = findEventRuleName(z.name, 'enter');
          if (enterRule) logCam(`📌 [触发规则] 已触发「${enterRule}」`, '');
          toast(`${z.name}: 检测到动物进入`, 'info');
          fetch('/api/experiment/camera-event', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ zone: z.name, event: 'enter', ts: Date.now(), experiment_id: currentExperimentId, pos_x: best ? best.cx : null, pos_y: best ? best.cy : null }),
          }).catch(() => {});
        } else if (enterDebounce[z.id] >= DEBOUNCE_FRAMES && had) {
          if (dwellTimers[z.id] && !dwellFired[z.id] && (Date.now() - dwellTimers[z.id]) > ((z.events?.dwell?.seconds || 3) * 1000)) {
            const dwellSec = z.events?.dwell?.seconds || 3;
            const posInfo = best ? `位置(${best.cx.toFixed(0)},${best.cy.toFixed(0)})` : '';
            logCam(`⏱ [停留] ${z.name} | 触发: 停留超过${dwellSec}秒${posInfo ? ' ' + posInfo : ''} | 来源: 摄像头检测`, 'info');
            const dwellRule = findEventRuleName(z.name, 'dwell');
            if (dwellRule) logCam(`📌 [触发规则] 已触发「${dwellRule}」`, '');
            dwellFired[z.id] = true;
            fetch('/api/experiment/camera-event', {
              method: 'POST', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ zone: z.name, event: 'dwell', seconds: dwellSec, ts: Date.now(), experiment_id: currentExperimentId, pos_x: best ? best.cx : null, pos_y: best ? best.cy : null }),
            }).catch(() => {});
          }
          const accN = z.events?.accumulate?.n || 5;
          if (accumulateCounts[z.id] >= accN && accumulateCounts[z.id] > (accumulateLastFired[z.id] || 0)
              && accumulateCounts[z.id] % accN === 0) {
            logCam(`🔢 [累计] ${z.name} | 触发: 累计进入达到${accumulateCounts[z.id]}次(每${accN}次) | 来源: 摄像头检测`, 'info');
            const accRule = findEventRuleName(z.name, 'accumulate');
            if (accRule) logCam(`📌 [触发规则] 已触发「${accRule}」`, '');
            accumulateLastFired[z.id] = accumulateCounts[z.id];
            fetch('/api/experiment/camera-event', {
              method: 'POST', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ zone: z.name, event: 'accumulate', n: accN, count: accumulateCounts[z.id], ts: Date.now(), experiment_id: currentExperimentId }),
            }).catch(() => {});
          }
        } else if (leaveDebounce[z.id] >= DEBOUNCE_FRAMES && had) {
          inZone[z.id] = false;
          dwellTimers[z.id] = 0;
          dwellFired[z.id] = false;
          const posInfo = best ? `位置(${best.cx.toFixed(0)},${best.cy.toFixed(0)})` : '位置未知';
          logCam(`🚪 [离开] ${z.name} | 触发: 动物${posInfo}离开区域 | 来源: 摄像头检测`, 'warn');
          const leaveRule = findEventRuleName(z.name, 'leave');
          if (leaveRule) logCam(`📌 [触发规则] 已触发「${leaveRule}」`, '');
          fetch('/api/experiment/camera-event', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ zone: z.name, event: 'leave', ts: Date.now(), experiment_id: currentExperimentId, pos_x: best ? best.cx : null, pos_y: best ? best.cy : null }),
          }).catch(() => {});
        }
      });

      prevFrame = frame;
    }, 200);

    const algoStatus = document.getElementById('camAlgo').value;
    const algoLabel = algoStatus === 'bgsub' ? '背景差分' : algoStatus === 'graythresh' ? '灰度阈值' : '动态剪影';
    const sensStatus = parseInt(document.getElementById('camSensitivity').value);
    const sizeMinStatus = parseInt(document.getElementById('camObjSizeMin')?.value || 100);
    const sizeMaxStatus = parseInt(document.getElementById('camObjSizeMax')?.value || 5000);
    document.getElementById('cameraDetectStatus').textContent =
      `✅ 检测运行中 | ${algoLabel} | ${contrast === 'dark' ? '比背景深的动物' : '比背景浅的动物'} | 灵敏度 ${sensStatus} | 对象面积 ${sizeMinStatus}-${sizeMaxStatus}`;
  } catch (e) {
    toast('检测暂未启动，请重试', 'error');
    document.getElementById('btnStartDetection').disabled = false;
    document.getElementById('btnStopDetection').disabled = true;
  }
}

function stopCameraDetection() {
  _detectionPaused = false;
  if (detectInterval) { clearInterval(detectInterval); detectInterval = null; }
  if (cameraStream) { cameraStream.getTracks().forEach(t => t.stop()); cameraStream = null; }
  document.getElementById('btnStartDetection').disabled = false;
  document.getElementById('btnStopDetection').disabled = true;
  document.getElementById('cameraDetectStatus').textContent = '⏹ 检测已停止';
  const previewCanvas = document.getElementById('camDetectPreview');
  if (previewCanvas) {
    const pctx = previewCanvas.getContext('2d');
    pctx.fillStyle = '#000';
    pctx.fillRect(0, 0, previewCanvas.width, previewCanvas.height);
    previewCanvas.style.display = 'none';
  }
  toast('摄像头检测已停止', 'warn');
  logCam('⏹ 检测已停止', 'warn');
}

document.addEventListener('visibilitychange', () => {});

// Ruler canvas click handler
const rulerCanvas = document.getElementById('camRulerCanvas');
if (rulerCanvas) {
  rulerCanvas.addEventListener('click', (e) => {
    if (cameraStep !== 2) return;
    if (rulerPoints.length >= 2) rulerPoints = [];
    const pos = canvasPos(e, rulerCanvas);
    rulerPoints.push({ x: pos.x, y: pos.y });
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
updateCameraTabAccess();

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

const zoneCanvas = document.getElementById('camCanvas');
let mouseCanvasPos = null;

zoneCanvas.addEventListener('mousedown', (e) => {
  if (e.button !== 0) return;
  const pos = canvasPos(e, zoneCanvas);

  if (zoneDrawMode) {
    zonePoints.push({ x: pos.x, y: pos.y });
    drawZones();
    return;
  }

  const near = findNearestVertex(pos.x, pos.y);
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
  const pos = canvasPos(e, zoneCanvas);
  mouseCanvasPos = { x: pos.x, y: pos.y };

  if (dragZoneIdx >= 0 && dragPtIdx >= 0) {
    zones[dragZoneIdx].points[dragPtIdx].x = pos.x;
    zones[dragZoneIdx].points[dragPtIdx].y = pos.y;
    drawZones();
    return;
  }

  if (zoneDrawMode && zonePoints.length > 0) {
    drawZones();
    const ctx = zoneCanvas.getContext('2d');
    const last = zonePoints[zonePoints.length - 1];
    ctx.strokeStyle = '#FFD700'; ctx.lineWidth = 1; ctx.setLineDash([4, 4]);
    ctx.beginPath(); ctx.moveTo(last.x, last.y);
    ctx.lineTo(pos.x, pos.y); ctx.stroke(); ctx.setLineDash([]);
    return;
  }

  if (!zoneDrawMode) {
    const near = findNearestVertex(pos.x, pos.y);
    zoneCanvas.style.cursor = (near.zone >= 0) ? 'grab' : 'default';
  }
});

zoneCanvas.addEventListener('mouseup', () => {
  if (dragZoneIdx >= 0) {
    updateZoneList();
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
  const pos = canvasPos(e, zoneCanvas);
  const near = findNearestVertex(pos.x, pos.y);
  if (near.zone >= 0 && near.point >= 0) {
    if (zones[near.zone].points.length <= 3) {
      toast('区域至少需要3个顶点，请移除整个区域', 'warn');
      return;
    }
    if (!confirm('确认移除此顶点？区域至少需要3个顶点')) return;
    zones[near.zone].points.splice(near.point, 1);
    drawZones(); updateZoneList();
    toast('已移除顶点', 'info');
  } else {
    const zoneIdx = zones.findIndex(z => {
      if (!z.points || z.points.length < 3) return false;
      return pointInPolygon(pos.x, pos.y, z.points);
    });
    if (zoneIdx >= 0) {
      if (confirm(`确认移除区域「${zones[zoneIdx].name}」？`)) {
        zones.splice(zoneIdx, 1);
        drawZones(); updateZoneList();
        toast('已移除区域', 'warn');
      }
    }
  }
});

zoneCanvas.addEventListener('mouseleave', () => {
  dragZoneIdx = -1;
  dragPtIdx = -1;
  zoneCanvas.style.cursor = zoneDrawMode ? 'crosshair' : 'default';
});
