/**
 * detection.js — 检测算法 + 渲染（独立模块，供 camera.js 和 monitor-camera.js 共用）
 *
 * 职责：
 *  - 运动蒙版计算（bgsub / graythresh / silhouette）
 *  - 形态学后处理（腐蚀 + 膨胀）
 *  - blob 提取 + 最佳 blob 选择 + 平滑
 *  - 渲染检测帧（蒙版涂红 + zones + 轮廓）
 *
 * 不依赖 camera.js 的任何变量。DOM 读取仅限 readCamParams / applySmoothing。
 */

// ---- 形态学 ----

function applyMaskMorphology(mask, width, height, erosionIters, dilateIters) {
  let morphMask = new Uint8ClampedArray(mask);
  for (let iter = 0; iter < erosionIters; iter++) {
    const eroded = new Uint8ClampedArray(width * height * 4);
    for (let y = 1; y < height - 1; y++) {
      for (let x = 1; x < width - 1; x++) {
        const i = (y * width + x) * 4;
        if (morphMask[i] !== 255) continue;
        let allWhite = true;
        for (let dy = -1; dy <= 1; dy++) {
          for (let dx = -1; dx <= 1; dx++) {
            if (morphMask[((y + dy) * width + (x + dx)) * 4] !== 255) { allWhite = false; break; }
          }
          if (!allWhite) break;
        }
        if (allWhite) { eroded[i] = 255; eroded[i + 1] = 255; eroded[i + 2] = 255; eroded[i + 3] = 255; }
      }
    }
    morphMask = eroded;
  }
  for (let iter = 0; iter < dilateIters; iter++) {
    const dilated = new Uint8ClampedArray(width * height * 4);
    for (let y = 0; y < height; y++) {
      for (let x = 0; x < width; x++) {
        const i = (y * width + x) * 4;
        if (morphMask[i] === 255) { dilated[i] = 255; dilated[i + 1] = 255; dilated[i + 2] = 255; dilated[i + 3] = 255; continue; }
        let hasNeighbor = false;
        for (let dy = -1; dy <= 1; dy++) {
          for (let dx = -1; dx <= 1; dx++) {
            const nx = x + dx, ny = y + dy;
            if (nx >= 0 && nx < width && ny >= 0 && ny < height && morphMask[(ny * width + nx) * 4] === 255) { hasNeighbor = true; break; }
          }
          if (hasNeighbor) break;
        }
        if (hasNeighbor) { dilated[i] = 255; dilated[i + 1] = 255; dilated[i + 2] = 255; dilated[i + 3] = 255; }
      }
    }
    morphMask = dilated;
  }
  return morphMask;
}

function countMaskPixels(mask) {
  let count = 0;
  for (let i = 0; i < mask.length; i += 4) {
    if (mask[i] === 255) count++;
  }
  return count;
}

// ---- blob 提取 ----

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

        for (const [dx, dy] of [[-1,0],[1,0],[0,-1],[0,1],[-1,-1],[-1,1],[1,-1],[1,1]]) {
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

// ---- 平滑（依赖 DOM 滑块 + _smoothPrev 状态） ----

let _smoothPrev = { cx: null, cy: null, minX: null, minY: null, maxX: null, maxY: null };

function resetSmoothing() {
  _smoothPrev = { cx: null, cy: null, minX: null, minY: null, maxX: null, maxY: null };
}

function applySmoothing(best, type) {
  if (!best) return best;
  const alpha = type === 'track'
    ? (1 / (parseInt(document.getElementById('camTrackSmoothStrength')?.value || 3) * 0.5 + 1))
    : (1 / (parseInt(document.getElementById('camBoxSmoothStrength')?.value || 3) * 0.5 + 1));
  if (type === 'track' && document.getElementById('camTrackSmooth')?.checked) {
    if (_smoothPrev.cx !== null) {
      best.cx = alpha * best.cx + (1 - alpha) * _smoothPrev.cx;
      best.cy = alpha * best.cy + (1 - alpha) * _smoothPrev.cy;
    }
    _smoothPrev.cx = best.cx;
    _smoothPrev.cy = best.cy;
  }
  if (type === 'box' && document.getElementById('camBoxSmooth')?.checked) {
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

// ---- 轮廓绘制 ----

function drawDetectionOverlay(ctx, best, opts = {}) {
  if (!best || !ctx) return;
  const color = opts.color || '#FFD700';
  const showLabel = opts.showLabel !== false;
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.strokeRect(best.minX, best.minY, best.maxX - best.minX, best.maxY - best.minY);
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.arc(best.cx, best.cy, 6, 0, Math.PI * 2);
  ctx.fill();
  if (showLabel && best.count) {
    ctx.fillStyle = 'white';
    ctx.font = 'bold 13px sans-serif';
    ctx.fillText(`对象: ${best.count} px²`, best.minX, best.minY - 6);
  }
}

// ---- 参数读取 ----

/**
 * 从 DOM 滑块读取当前检测参数
 */
function readCamParams() {
  return {
    sensitivity: parseInt(document.getElementById('camSensitivity').value),
    brightnessThresh: parseInt(document.getElementById('camBrightnessThresh')?.value || 30),
    algo: document.getElementById('camAlgo').value,
    threshLow: parseInt(document.getElementById('camThreshLow')?.value || 30),
    threshHigh: parseInt(document.getElementById('camThreshHigh')?.value || 220),
    erosionIters: parseInt(document.getElementById('camContourErosion')?.value || 1),
    dilateIters: parseInt(document.getElementById('camContourDilate')?.value || 2),
    objSizeMin: parseInt(document.getElementById('camObjSizeMin')?.value || 100),
    objSizeMax: parseInt(document.getElementById('camObjSizeMax')?.value || 5000),
  };
}

// ---- 检测管线 ----

/**
 * 检测管线：一帧像素 → 运动蒙版 + 检测结果（纯函数，不读 DOM）
 * @param {Uint8ClampedArray} data - 当前帧像素 (frame.data)
 * @param {Uint8ClampedArray} bgData - 背景像素 (bgImageData.data)
 * @param {number} w - 帧宽
 * @param {number} h - 帧高
 * @param {Object} params - 检测参数
 * @param {ImageData|null} prevFrame - 前一帧 (silhouette 算法需要)
 * @param {string} contrastDir - 对比方向 ('dark' 或 'light')
 * @returns {{ morphMask: Uint8ClampedArray, best: Object|null }}
 */
function runDetectionPipeline(data, bgData, w, h, params, prevFrame, contrastDir) {
  const { sensitivity, brightnessThresh, algo, threshLow, threshHigh, erosionIters, dilateIters, objSizeMin, objSizeMax } = params;

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
      const lumDiff = contrastDir === 'dark' ? (bgLum - lum) : (lum - bgLum);
      isMotion = lumDiff > brightnessThresh && lum > threshLow && lum < threshHigh;
    } else if (algo === 'silhouette' && prevFrame) {
      const diff = Math.abs(data[i] - prevFrame.data[i]) + Math.abs(data[i + 1] - prevFrame.data[i + 1]) + Math.abs(data[i + 2] - prevFrame.data[i + 2]);
      isMotion = diff > sensitivity * 2;
    }
    if (isMotion) {
      motionMask[i] = 255; motionMask[i + 1] = 255; motionMask[i + 2] = 255; motionMask[i + 3] = 255;
    }
  }

  const morphMask = applyMaskMorphology(motionMask, w, h, erosionIters, dilateIters);

  let best = null;
  const blobs = extractBlob(morphMask, w, h, 5);
  best = findBestBlob(blobs, Math.max(5, objSizeMin), objSizeMax, contrastDir);
  best = applySmoothing(best, 'track');
  best = applySmoothing(best, 'box');

  return { morphMask, best };
}

// ---- 渲染 ----

/**
 * 渲染检测帧：蒙版 + 轮廓 + zones
 * @param {CanvasRenderingContext2D} ctx - 目标画布上下文
 * @param {ImageData} frame - 当前帧 (会被修改：运动像素涂红)
 * @param {Uint8ClampedArray} morphMask - 形态学后的蒙版
 * @param {Object|null} best - 检测结果
 * @param {Array} zones - 区域列表
 */
function renderDetectionFrame(ctx, frame, morphMask, best, zones) {
  for (let i = 0; i < morphMask.length; i += 4) {
    if (morphMask[i] === 255) {
      frame.data[i] = 255; frame.data[i + 1] = 0; frame.data[i + 2] = 0; frame.data[i + 3] = 128;
    }
  }
  ctx.putImageData(frame, 0, 0);

  zones.forEach(z => {
    if (!z.points || z.points.length < 3) return;
    ctx.strokeStyle = z.color + '80'; ctx.lineWidth = 2;
    ctx.fillStyle = z.color + '15';
    ctx.beginPath();
    ctx.moveTo(z.points[0].x, z.points[0].y);
    for (let j = 1; j < z.points.length; j++) ctx.lineTo(z.points[j].x, z.points[j].y);
    ctx.closePath();
    ctx.fill(); ctx.stroke();
    const p0 = z.points[0];
    ctx.fillStyle = z.color;
    ctx.fillText(z.name, p0.x + 4, p0.y - 8);
  });

  if (best) {
    drawDetectionOverlay(ctx, best, { showLabel: true });
  }

  if (best) {
    window._monitorDetectResult = {
      best: { cx: best.cx, cy: best.cy, minX: best.minX, maxX: best.maxX, minY: best.minY, maxY: best.maxY, count: best.count },
      ts: Date.now(),
    };
  } else {
    window._monitorDetectResult = { best: null, ts: Date.now() };
  }
}
