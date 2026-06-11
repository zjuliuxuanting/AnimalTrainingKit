/**
 * Sprint v1.2.0 任务C：运行监控只读摄像头预览 验证
 * 使用 Chromium fake 摄像头（playwright launch flags）。
 */
const { test, expect } = require('@playwright/test');

test.use({
  baseURL: 'http://localhost:8001',
  launchOptions: {
    args: [
      '--use-fake-ui-for-media-stream',
      '--use-fake-device-for-media-stream',
    ],
  },
  permissions: ['camera'],
});
test.setTimeout(90_000);

test('C. 摄像头实验运行监控显示只读预览+zone叠加', async ({ page }) => {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#nodePalette', { state: 'attached', timeout: 15000 });

  // 1. 创建启用摄像头的实验
  const created = await page.request.post('/api/experiments', {
    headers: { 'Content-Type': 'application/json' },
    data: {
      name: 'TMP_camera_monitor_test',
      subject_id: 'cam-mouse', species: 'mouse',
      max_duration_min: 1, max_trigger_count: 0,
      trigger_manual: true, trigger_camera: true, trigger_hardware: false,
      start_mode: 'manual',
    },
  });
  const exp = await created.json();
  const expId = exp.id;

  try {
    // 2. 保存一个含 zone 的 camera.json
    await page.request.post('/api/camera/config', {
      headers: { 'Content-Type': 'application/json' },
      data: {
        experiment_id: expId,
        config: {
          zones: [{
            name: '奖励区',
            points: [{ x: 100, y: 100 }, { x: 300, y: 100 }, { x: 300, y: 280 }, { x: 100, y: 280 }],
          }],
        },
      },
    });

    // 3. 保存一个最小可跑流程
    await page.request.post(`/api/experiments/${expId}/flow/save`, {
      headers: { 'Content-Type': 'application/json' },
      data: {
        flow: {
          id: 'f', name: 'TMP_camera_monitor_test',
          nodes: {
            s: { id: 's', node_type: 'start', label: '开始', params: {}, x: 40, y: 200 },
            t: { id: 't', node_type: 'trigger', label: '触发', params: { signal_id: 'manual:trigger' }, x: 220, y: 200 },
            e: { id: 'e', node_type: 'end', label: '结束', params: {}, x: 400, y: 200 },
          },
          edges: [
            { id: 'e1', source_node: 's', source_port: 'out', target_node: 't', target_port: 'in', condition: '' },
            { id: 'e2', source_node: 't', source_port: 'out', target_node: 'e', target_port: 'in', condition: '' },
          ],
        },
      },
    });

    // 4. 进入实验并启动运行预览（直接调用前端函数）
    await page.evaluate((id) => enterExperiment(id), expId);
    await page.waitForTimeout(1500);
    // 切到运行监控页（卡片在 tab-monitor 内，需激活该 tab 才可见）
    await page.locator('[data-tab="monitor"]').click();
    await page.waitForTimeout(300);

    // 直接触发只读预览（模拟 runFlow 后的调用）
    const previewResult = await page.evaluate(async (id) => {
      await startMonitorCameraPreview(id, true);
      return true;
    }, expId);
    await page.waitForTimeout(2500);

    // 调试：确认 camera.json zones 被读到
    const zonesLoaded = await page.evaluate(async (id) => {
      const r = await fetch('/api/camera/config?experiment_id=' + encodeURIComponent(id));
      const d = await r.json();
      return (d.config && d.config.zones) ? d.config.zones.length : 0;
    }, expId);
    expect(zonesLoaded).toBeGreaterThan(0);

    // 5. 断言：预览卡片可见
    const cardVisible = await page.locator('#monitorCameraCard').isVisible();
    expect(cardVisible).toBeTruthy();

    // canvas 已绘制（尺寸 > 0）
    const canvasInfo = await page.evaluate(() => {
      const c = document.getElementById('monitorCamCanvas');
      return { w: c.width, h: c.height };
    });
    expect(canvasInfo.w).toBeGreaterThan(0);
    expect(canvasInfo.h).toBeGreaterThan(0);

    // 状态提示存在（有画面 或 仅区域示意）
    const status = await page.locator('#monitorCameraStatus').textContent();
    expect(status.length).toBeGreaterThan(0);

    // 6. flashMonitorZone 高亮可调用且更新状态
    await page.evaluate(() => flashMonitorZone('奖励区'));
    await page.waitForTimeout(300);
    const status2 = await page.locator('#monitorCameraStatus').textContent();
    expect(status2).toContain('奖励区');

    // 7. 停止预览后卡片隐藏
    await page.evaluate(() => stopMonitorCameraPreview());
    await page.waitForTimeout(300);
    const hidden = await page.locator('#monitorCameraCard').isVisible();
    expect(hidden).toBeFalsy();
  } finally {
    await page.request.delete(`/api/experiments/${expId}`).catch(() => {});
  }
});
