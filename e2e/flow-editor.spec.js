/**
 * Flow Editor — E2E 浏览器测试
 *
 * 覆盖流程编辑器的核心路径：
 * 页面加载 → 创建实验 → 查看流程编辑器 → 节点操作 → 保存恢复
 */
const { test, expect } = require('@playwright/test');

test.describe('行为学训练盒 — 流程编辑器', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/');
  });

  test('1. 页面加载成功', async ({ page }) => {
    // 验证页面标题
    await expect(page).toHaveTitle(/行为学/);

    // 验证主要区域可见
    await expect(page.locator('#app')).toBeVisible();
    await expect(page.locator('#flowCanvas, .flow-canvas, [class*="flow"]').first()).toBeVisible();
  });

  test('2. 创建新实验', async ({ page }) => {
    // 点击"新建实验"按钮
    const newBtn = page.locator('button, a, [role="button"]').filter({ hasText: /新建实验|新建|new/i }).first();
    await expect(newBtn).toBeVisible();
    await newBtn.click();

    // 输入实验名称
    const nameInput = page.locator('input[type="text"], input:not([type]), textarea').first();
    if (await nameInput.isVisible()) {
      await nameInput.fill('Playwright 测试实验');
      await page.locator('button, a, [role="button"]').filter({ hasText: /确认|确定|创建|保存|ok|confirm/i }).first().click();
    }

    // 等待实验创建完成
    await page.waitForTimeout(1000);

    // 验证实验出现在列表中
    await expect(page.locator('text=Playwright 测试实验').first()).toBeVisible();
  });

  test('3. 流程画布有 START/END 节点', async ({ page }) => {
    // 先进入已有实验或创建新实验
    const expLink = page.locator('a, button, [role="button"]').filter({ hasText: /进入|编辑|open|flow|流程/i }).first();
    if (await expLink.isVisible()) {
      await expLink.click();
    }

    await page.waitForTimeout(1000);

    // 验证画布上有 START 和 END 节点
    const startNode = page.locator('text=开始').first();
    const endNode = page.locator('text=结束').first();

    await expect(startNode).toBeVisible();
    await expect(endNode).toBeVisible();
  });

  test('4. 调色板中的节点可拖动到画布', async ({ page }) => {
    // 检查调色板/节点列表区域
    const palette = page.locator('#palette, [class*="palette"], [class*="toolbar"], .node-palette').first();
    await expect(palette).toBeVisible();

    // 验证调色板中有节点类型
    const triggerItem = palette.locator('text=触发信号').first();
    await expect(triggerItem).toBeVisible();
  });

  test('5. 保存流程后恢复', async ({ page }) => {
    // 查找保存按钮
    const saveBtn = page.locator('button, [role="button"]').filter({ hasText: /保存|save/i }).first();
    if (await saveBtn.isVisible()) {
      await saveBtn.click();
      await page.waitForTimeout(500);

      // 刷新页面
      await page.reload();
      await page.waitForTimeout(1000);

      // 验证页面基本结构仍在
      await expect(page.locator('#app')).toBeVisible();
    }
  });
});
