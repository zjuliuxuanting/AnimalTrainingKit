/**
 * monitor-camera.js — 运行监控页只读摄像头预览
 *
 * 职责（只读）：
 *  - 仅在“启用了摄像头且配置了 zone”的实验运行监控页显示实时画面
 *  - 叠加 zone 多边形（复用 camera.json 中保存的 zones）
 *  - 某个 zone 触发（camera-event enter/dwell/accumulate）时短暂高亮
 *  - 不提供任何改区能力，不做运动检测，不 fire 事件
 *
 * 依赖：camera.js 的 ZONE_COLORS（全局），app.js 的 escapeHtml/api（可选）。
 * 与 camera.js 的检测循环相互独立：本模块只画 video + zone，不分析像素。
 */

(function () {
  'use strict';

  // 监控预览本地状态（与 camera.js 的 zones/cameraStream 隔离，避免互相污染）
  let monStream = null;
  let monRAF = null;
  let monZones = [];
  let monActive = false;
  // zoneName -> 高亮到期时间戳(ms)
  const monFlashUntil = {};
  // 最近触发的 zone 名（用于状态提示）
  let monLastZone = '';
  let monLastZoneTs = 0;

  const FLASH_MS = 1200;
  const MON_COLORS = (typeof ZONE_COLORS !== 'undefined' && ZONE_COLORS) || ['#FF9800', '#4CAF50', '#2196F3', '#E91E63', '#9C27B0'];

  function $(id) { return document.getElementById(id); }

  function setStatus(text) {
    const el = $('monitorCameraStatus');
    if (el) el.textContent = text;
  }

  // 加载当前实验 camera.json 的 zones（只读）
  async function loadMonitorZones(expId) {
    try {
      let url = '/api/camera/config';
      if (expId) url += '?experiment_id=' + encodeURIComponent(expId);
      const resp = await fetch(url);
      const data = await resp.json();
      const cfg = (data && data.config) || {};
      if (!cfg.zones || cfg.zones.length === 0) return [];
      return cfg.zones.map((z, i) => ({
        id: 'mzone_' + i,
        name: z.name || ('区域' + (i + 1)),
        points: z.points || (
          (z.x !== undefined && z.w !== undefined)
            ? [{ x: z.x, y: z.y }, { x: z.x + z.w, y: z.y }, { x: z.x + z.w, y: z.y + z.h }, { x: z.x, y: z.y + z.h }]
            : []
        ),
        color: MON_COLORS[i % MON_COLORS.length],
      })).filter(z => z.points && z.points.length >= 3);
    } catch (e) {
      return [];
    }
  }

  // 把帧画到 canvas，并叠加 zone（按帧分辨率做坐标缩放）
  function drawMonitorFrame() {
    const canvas = $('monitorCamCanvas');
    const video = $('monitorCamVideo');
    if (!canvas || !video) { monActive = false; return; }
    const ctx = canvas.getContext('2d');

    const vw = video.videoWidth || 640;
    const vh = video.videoHeight || 480;
    // canvas 内部像素跟随视频分辨率，保证 zone 坐标（基于检测帧）对齐
    if (canvas.width !== vw || canvas.height !== vh) {
      canvas.width = vw;
      canvas.height = vh;
    }

    if (video.readyState >= 2) {
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    } else {
      ctx.fillStyle = '#000';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
    }

    const now = Date.now();
    ctx.font = '14px sans-serif';
    ctx.textBaseline = 'top';
    monZones.forEach((z) => {
      const flashing = (monFlashUntil[z.name] || 0) > now;
      ctx.lineWidth = flashing ? 5 : 2;
      ctx.strokeStyle = flashing ? '#FFD700' : z.color;
      ctx.fillStyle = (flashing ? '#FFD70055' : z.color + '22');
      ctx.beginPath();
      ctx.moveTo(z.points[0].x, z.points[0].y);
      for (let i = 1; i < z.points.length; i++) ctx.lineTo(z.points[i].x, z.points[i].y);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();

      const p0 = z.points[0];
      const label = flashing ? (z.name + ' ●触发') : z.name;
      ctx.fillStyle = flashing ? '#FFD700' : z.color;
      const labelW = ctx.measureText(label).width + 12;
      ctx.fillRect(p0.x, p0.y - 20, labelW, 20);
      ctx.fillStyle = flashing ? '#000' : '#fff';
      ctx.fillText(label, p0.x + 6, p0.y - 18);
    });

    if (monActive) monRAF = requestAnimationFrame(drawMonitorFrame);
  }

  function refreshStatusText() {
    if (!monActive) return;
    let txt;
    if (!monStream || !monStream.active) {
      txt = '⚠ 无画面：未获取到摄像头视频流';
    } else {
      txt = '● 画面正常';
      if (monLastZone && (Date.now() - monLastZoneTs) < 5000) {
        txt += ` ｜ 最近触发区域：${monLastZone}`;
      }
    }
    setStatus(txt);
  }

  /**
   * 启动只读预览。仅当实验启用摄像头且有 zone 时显示卡片并开画。
   * @param {string} expId 当前实验 id
   * @param {boolean} cameraEnabled 实验是否启用摄像头
   */
  async function startMonitorCameraPreview(expId, cameraEnabled) {
    stopMonitorCameraPreview();
    const card = $('monitorCameraCard');
    if (!card) return;

    if (!cameraEnabled || !expId) {
      card.style.display = 'none';
      return;
    }

    monZones = await loadMonitorZones(expId);
    if (monZones.length === 0) {
      // 启用摄像头但还没配区域：不显示只读预览卡片
      card.style.display = 'none';
      return;
    }

    card.style.display = 'block';
    monActive = true;
    setStatus('正在打开摄像头…');

    const video = $('monitorCamVideo');
    try {
      monStream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 640 }, height: { ideal: 480 } },
        audio: false,
      });
      video.srcObject = monStream;
      await video.play();
      refreshStatusText();
    } catch (e) {
      // 摄像头被占用或无权限：仍显示 zone 叠加（黑底），给出提示
      setStatus('⚠ 无画面：摄像头不可用或被占用，仅显示区域示意');
    }

    if (monRAF) cancelAnimationFrame(monRAF);
    monRAF = requestAnimationFrame(drawMonitorFrame);

    // 每 2s 刷新一次状态文案
    if (startMonitorCameraPreview._statusTimer) clearInterval(startMonitorCameraPreview._statusTimer);
    startMonitorCameraPreview._statusTimer = setInterval(refreshStatusText, 2000);
  }

  function stopMonitorCameraPreview() {
    monActive = false;
    if (monRAF) { cancelAnimationFrame(monRAF); monRAF = null; }
    if (startMonitorCameraPreview._statusTimer) {
      clearInterval(startMonitorCameraPreview._statusTimer);
      startMonitorCameraPreview._statusTimer = null;
    }
    if (monStream) {
      monStream.getTracks().forEach(t => t.stop());
      monStream = null;
    }
    const video = $('monitorCamVideo');
    if (video) video.srcObject = null;
    monZones = [];
    monLastZone = '';
    for (const k in monFlashUntil) delete monFlashUntil[k];
    const card = $('monitorCameraCard');
    if (card) card.style.display = 'none';
  }

  /**
   * 某个 zone 刚触发时调用，短暂高亮该区域并更新状态。
   * @param {string} zoneName
   */
  function flashMonitorZone(zoneName) {
    if (!zoneName) return;
    monFlashUntil[zoneName] = Date.now() + FLASH_MS;
    monLastZone = zoneName;
    monLastZoneTs = Date.now();
    refreshStatusText();
  }

  // 暴露到全局，供 app.js / camera.js 调用
  window.startMonitorCameraPreview = startMonitorCameraPreview;
  window.stopMonitorCameraPreview = stopMonitorCameraPreview;
  window.flashMonitorZone = flashMonitorZone;
})();
