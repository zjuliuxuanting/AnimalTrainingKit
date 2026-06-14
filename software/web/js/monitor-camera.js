/**
 * monitor-camera.js — 运行监控页独立摄像头检测
 *
 * 职责：
 *  - 独立加载摄像头配置（zones + params + bgImageData + event_rules）
 *  - 独立打开摄像头流
 *  - 使用 detection.js 的 runDetectionPipeline + renderDetectionFrame 跑检测
 *  - 区域事件判断 → fetch /api/experiment/camera-event
 *  - 事件日志、规则名反馈、轨迹采样
 *  - zone 触发时短暂高亮
 *
 * 不依赖 camera.js 的任何变量。
 */

(function () {
  'use strict';

  let monInterval = null;
  let monStream = null;
  let monVideo = null;
  let monActive = false;
  let monZones = [];
  let monBgData = null;
  let monContrast = 'dark';
  let monPrevFrame = null;

  // 事件规则（从配置加载）
  let monEventRules = [];

  // zone 事件状态
  let monInZone = {};
  let monDwellTimers = {};
  let monDwellFired = {};
  let monAccumulateCounts = {};
  let monAccumulateLastFired = {};
  let monEnterDebounce = {};
  let monLeaveDebounce = {};

  // 轨迹采样
  let monTrajBuffer = [];
  let monTrajLastFlush = 0;

  // zoneName -> 高亮到期时间戳(ms)
  const monFlashUntil = {};
  let monLastZone = '';
  let monLastZoneTs = 0;

  const FLASH_MS = 1200;
  const MON_COLORS = (typeof ZONE_COLORS !== 'undefined' && ZONE_COLORS) || ['#FF9800', '#4CAF50', '#2196F3', '#E91E63', '#9C27B0'];

  function $(id) { return document.getElementById(id); }

  function setStatus(text) {
    const el = $('monitorCameraStatus');
    if (el) el.textContent = text;
  }

  function logMon(msg, type) {
    const el = $('monitorEventLog');
    if (!el) return;
    const ts = new Date().toLocaleTimeString();
    el.innerHTML += `<span class="${type || ''}">[${ts}] ${msg}</span>\n`;
    el.scrollTop = el.scrollHeight;
  }

  function findMonEventRuleName(zone, eventType) {
    if (!Array.isArray(monEventRules)) return null;
    const rule = monEventRules.find(r => r.zone === zone && r.event === eventType);
    return rule ? rule.name : null;
  }

  // 从 API 加载配置（zones + params + contrast + event_rules）
  async function loadMonitorConfig(expId) {
    try {
      let url = '/api/camera/config';
      if (expId) url += '?experiment_id=' + encodeURIComponent(expId);
      const resp = await fetch(url);
      const data = await resp.json();
      const cfg = (data && data.config) || {};
      monEventRules = Array.isArray(cfg.event_rules) ? cfg.event_rules : [];
      return cfg;
    } catch (e) {
      monEventRules = [];
      return {};
    }
  }

  // 从 API 加载背景图像
  async function loadMonitorBackground(expId) {
    try {
      let url = '/api/camera/background';
      if (expId) url += '?experiment_id=' + encodeURIComponent(expId);
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

  // 从 config 构造检测参数对象
  function buildParamsFromConfig(cfg) {
    return {
      sensitivity: cfg.sensitivity !== undefined ? cfg.sensitivity : 30,
      brightnessThresh: cfg.brightness_threshold !== undefined ? cfg.brightness_threshold : 30,
      algo: cfg.algorithm || 'bgsub',
      threshLow: 30,
      threshHigh: 220,
      erosionIters: 1,
      dilateIters: 2,
      objSizeMin: cfg.obj_size_min || cfg.min_area || 100,
      objSizeMax: cfg.obj_size_max || 5000,
    };
  }

  // 从 config 构造 zones 数组（根据 event_rules 同步 enabled 状态）
  function buildZonesFromConfig(cfg) {
    if (!cfg.zones || cfg.zones.length === 0) return [];
    const ruleSet = new Set(monEventRules.map(r => `${r.zone}:${r.event}`));
    return cfg.zones.map((z, i) => {
      const evts = z.events || {
        enter: { enabled: true, role: 'trigger' },
        leave: { enabled: false, role: 'trigger' },
        accumulate: { enabled: false, n: 5, role: 'trigger' },
        dwell: { enabled: false, seconds: 3, role: 'trigger' }
      };
      if (evts.accumulate) evts.accumulate.enabled = ruleSet.has(`${z.name}:accumulate`);
      if (evts.dwell) evts.dwell.enabled = ruleSet.has(`${z.name}:dwell`);
      return {
        id: 'mzone_' + i,
        name: z.name || ('区域' + (i + 1)),
        points: z.points || (
          (z.x !== undefined && z.w !== undefined)
            ? [{ x: z.x, y: z.y }, { x: z.x + z.w, y: z.y }, { x: z.x + z.w, y: z.y + z.h }, { x: z.x, y: z.y + z.h }]
            : []
        ),
        color: MON_COLORS[i % MON_COLORS.length],
        events: evts,
      };
    }).filter(z => z.points && z.points.length >= 3);
  }

  // 检测循环
  function monDetectionTick(canvas, actx, params) {
    if (!monVideo || monVideo.readyState < 2 || !monBgData) return;

    const w = monBgData.width, h = monBgData.height;
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w; canvas.height = h;
    }

    actx.drawImage(monVideo, 0, 0, w, h);
    const frame = actx.getImageData(0, 0, w, h);

    const { morphMask, best } = runDetectionPipeline(frame.data, monBgData.data, w, h, params, monPrevFrame, monContrast);

    renderDetectionFrame(canvas.getContext('2d'), frame, morphMask, best, monZones);

    // zone 事件判断
    handleZoneEvents(best);

    // 轨迹采样 — 每帧记录位置，每5秒批量上传
    if (best && best.count > 10 && typeof window.currentSessionId !== 'undefined' && window.currentSessionId) {
      const currentZone = monZones.find(z => z.points && z.points.length >= 3 && pointInPolygon(best.cx, best.cy, z.points));
      monTrajBuffer.push({ ts_ms: Date.now(), x: Math.round(best.cx), y: Math.round(best.cy), zone_name: currentZone ? currentZone.name : '' });
      const now = Date.now();
      if (now - monTrajLastFlush >= 5000 && monTrajBuffer.length > 0) {
        const batch = monTrajBuffer.splice(0, monTrajBuffer.length);
        monTrajLastFlush = now;
        fetch(`/api/sessions/${window.currentSessionId}/trajectories`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ points: batch, experiment_id: window.currentExperimentId || '' }),
        }).catch(() => {});
      }
    }

    monPrevFrame = frame;
  }

  // 区域事件处理
  function handleZoneEvents(best) {
    const DEBOUNCE_FRAMES = 3;

    monZones.forEach(z => {
      if (!z.points || z.points.length < 3) return;
      const had = monInZone[z.id];
      const has = best && best.count > 10 && pointInPolygon(best.cx, best.cy, z.points);

      if (has) {
        monEnterDebounce[z.id] = (monEnterDebounce[z.id] || 0) + 1;
        monLeaveDebounce[z.id] = 0;
      } else {
        monLeaveDebounce[z.id] = (monLeaveDebounce[z.id] || 0) + 1;
        monEnterDebounce[z.id] = 0;
      }

      if (monEnterDebounce[z.id] >= DEBOUNCE_FRAMES && !had) {
        monInZone[z.id] = true;
        monDwellTimers[z.id] = Date.now();
        monDwellFired[z.id] = false;
        monAccumulateCounts[z.id] = (monAccumulateCounts[z.id] || 0) + 1;
        monFlashUntil[z.name] = Date.now() + FLASH_MS;
        monLastZone = z.name;
        monLastZoneTs = Date.now();
        if (typeof flashMonitorZone === 'function') flashMonitorZone(z.name);
        const posInfo = best ? `位置(${best.cx.toFixed(0)},${best.cy.toFixed(0)})` : '位置未知';
        logMon(`🧪 [进入] ${z.name} | 触发: 动物${posInfo}进入区域 | 来源: 摄像头检测 | 第${monAccumulateCounts[z.id]}次进入`, 'success');
        const enterRule = findMonEventRuleName(z.name, 'enter');
        if (enterRule) logMon(`📌 [触发规则] 已触发「${enterRule}」`, '');
        if (typeof toast === 'function') toast(`${z.name}: 检测到动物进入`, 'info');
        fetch('/api/experiment/camera-event', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ zone: z.name, event: 'enter', ts: Date.now(), experiment_id: window.currentExperimentId, pos_x: best ? best.cx : null, pos_y: best ? best.cy : null }),
        }).catch(() => {});
      } else if (monEnterDebounce[z.id] >= DEBOUNCE_FRAMES && had) {
        if (z.events?.dwell?.enabled && monDwellTimers[z.id] && !monDwellFired[z.id] && (Date.now() - monDwellTimers[z.id]) > ((z.events.dwell.seconds || 3) * 1000)) {
          const dwellSec = z.events.dwell.seconds || 3;
          const posInfo = best ? `位置(${best.cx.toFixed(0)},${best.cy.toFixed(0)})` : '';
          logMon(`⏱ [停留] ${z.name} | 触发: 停留超过${dwellSec}秒${posInfo ? ' ' + posInfo : ''} | 来源: 摄像头检测`, 'info');
          const dwellRule = findMonEventRuleName(z.name, 'dwell');
          if (dwellRule) logMon(`📌 [触发规则] 已触发「${dwellRule}」`, '');
          monDwellFired[z.id] = true;
          fetch('/api/experiment/camera-event', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ zone: z.name, event: 'dwell', seconds: dwellSec, ts: Date.now(), experiment_id: window.currentExperimentId, pos_x: best ? best.cx : null, pos_y: best ? best.cy : null }),
          }).catch(() => {});
        }
        if (z.events?.accumulate?.enabled) {
          const accN = z.events.accumulate.n || 5;
          if (monAccumulateCounts[z.id] >= accN && monAccumulateCounts[z.id] > (monAccumulateLastFired[z.id] || 0) && monAccumulateCounts[z.id] % accN === 0) {
            logMon(`🔢 [累计] ${z.name} | 触发: 累计进入达到${monAccumulateCounts[z.id]}次(每${accN}次) | 来源: 摄像头检测`, 'info');
            const accRule = findMonEventRuleName(z.name, 'accumulate');
            if (accRule) logMon(`📌 [触发规则] 已触发「${accRule}」`, '');
            monAccumulateLastFired[z.id] = monAccumulateCounts[z.id];
            fetch('/api/experiment/camera-event', {
              method: 'POST', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ zone: z.name, event: 'accumulate', n: accN, count: monAccumulateCounts[z.id], ts: Date.now(), experiment_id: window.currentExperimentId }),
            }).catch(() => {});
          }
        }
      } else if (monLeaveDebounce[z.id] >= DEBOUNCE_FRAMES && had) {
        monInZone[z.id] = false;
        monDwellTimers[z.id] = 0;
        monDwellFired[z.id] = false;
        const posInfo = best ? `位置(${best.cx.toFixed(0)},${best.cy.toFixed(0)})` : '位置未知';
        logMon(`🚪 [离开] ${z.name} | 触发: 动物${posInfo}离开区域 | 来源: 摄像头检测`, 'warn');
        const leaveRule = findMonEventRuleName(z.name, 'leave');
        if (leaveRule) logMon(`📌 [触发规则] 已触发「${leaveRule}」`, '');
        fetch('/api/experiment/camera-event', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ zone: z.name, event: 'leave', ts: Date.now(), experiment_id: window.currentExperimentId, pos_x: best ? best.cx : null, pos_y: best ? best.cy : null }),
        }).catch(() => {});
      }
    });
  }

  // pointInPolygon 复用（如果 app.js 已定义则用全局的，否则本地实现）
  const _pip = (typeof pointInPolygon === 'function') ? pointInPolygon : function (px, py, points) {
    let inside = false;
    for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
      const xi = points[i].x, yi = points[i].y, xj = points[j].x, yj = points[j].y;
      if ((yi > py) !== (yj > py) && px < (xj - xi) * (py - yi) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
  };

  function refreshStatusText() {
    if (!monActive) return;
    if (!monStream || !monStream.active) {
      setStatus('⚠ 检测未启动：请检查摄像头、背景建模和检测区域配置');
    } else {
      const det = window._monitorDetectResult;
      if (det && det.best) {
        setStatus(`● 检测中：识别到对象 位置(${det.best.cx.toFixed(0)},${det.best.cy.toFixed(0)})`);
      } else {
        setStatus('● 检测运行中：当前未识别到对象');
      }
      if (monLastZone && (Date.now() - monLastZoneTs) < 5000) {
        setStatus(`● 检测中 ｜ 最近触发区域：${monLastZone}`);
      }
    }
  }

  /**
   * 启动独立检测预览。
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

    setStatus('正在加载配置…');

    // 1. 加载配置
    const cfg = await loadMonitorConfig(expId);
    monZones = buildZonesFromConfig(cfg);
    if (monZones.length === 0) {
      card.style.display = 'none';
      return;
    }

    // 2. 加载背景
    monBgData = await loadMonitorBackground(expId);
    if (!monBgData) {
      setStatus('⚠ 背景数据未加载，请先在摄像头页完成背景建模');
      card.style.display = 'block';
      return;
    }

    // 3. 构造检测参数
    const params = buildParamsFromConfig(cfg);
    monContrast = cfg.contrast || 'dark';

    // 4. 打开摄像头流
    setStatus('正在打开摄像头…');
    try {
      const deviceId = (typeof getSelectedCameraId === 'function') ? getSelectedCameraId() : '';
      const constraints = deviceId
        ? { video: { deviceId: { exact: deviceId }, width: { ideal: 640 }, height: { ideal: 480 } }, audio: false }
        : { video: true, audio: false };
      monStream = await navigator.mediaDevices.getUserMedia(constraints);
    } catch (e) {
      setStatus('⚠ 摄像头打开失败，请检查权限');
      card.style.display = 'block';
      return;
    }

    // 5. 创建 video 元素
    monVideo = document.createElement('video');
    monVideo.muted = true;
    monVideo.srcObject = monStream;
    monVideo.width = monBgData.width;
    monVideo.height = monBgData.height;
    try { await monVideo.play(); } catch (e) { /* 自动播放限制忽略 */ }

    // 6. 显示卡片，启动检测循环
    card.style.display = 'block';
    monActive = true;

    const canvas = $('monitorCamCanvas');
    const analysisCanvas = document.createElement('canvas');
    analysisCanvas.width = monBgData.width;
    analysisCanvas.height = monBgData.height;
    const actx = analysisCanvas.getContext('2d');

    // 重置 zone 事件状态
    monInZone = {}; monDwellTimers = {}; monDwellFired = {};
    monAccumulateCounts = {}; monAccumulateLastFired = {};
    monEnterDebounce = {}; monLeaveDebounce = {};
    monTrajBuffer = []; monTrajLastFlush = 0;
    monPrevFrame = null;

    monInterval = setInterval(() => {
      monDetectionTick(canvas, actx, params);
      refreshStatusText();
    }, 200);

    setStatus('● 检测已启动');
  }

  function stopMonitorCameraPreview() {
    monActive = false;
    if (monInterval) { clearInterval(monInterval); monInterval = null; }
    if (monStream) {
      monStream.getTracks().forEach(t => t.stop());
      monStream = null;
    }
    monVideo = null;
    monBgData = null;
    monZones = [];
    monEventRules = [];
    monTrajBuffer = []; monTrajLastFlush = 0;
    monPrevFrame = null;
    monLastZone = '';
    for (const k in monFlashUntil) delete monFlashUntil[k];
    const card = $('monitorCameraCard');
    if (card) card.style.display = 'none';
  }

  function flashMonitorZone(zoneName) {
    if (!zoneName) return;
    monFlashUntil[zoneName] = Date.now() + FLASH_MS;
    monLastZone = zoneName;
    monLastZoneTs = Date.now();
  }

  // 暴露到全局
  window.startMonitorCameraPreview = startMonitorCameraPreview;
  window.stopMonitorCameraPreview = stopMonitorCameraPreview;
  window.flashMonitorZone = flashMonitorZone;
})();
