// @ts-check
const { defineConfig, devices } = require('@playwright/test');

/**
 * @see https://playwright.dev/docs/test-configuration
 */
module.exports = defineConfig({
  testDir: './software/e2e',
  /* 测试文件匹配模式 */
  testMatch: '*.spec.js',
  /* 超时时间 */
  timeout: 30000,
  expect: {
    timeout: 10000,
  },
  /* 启用失败重试 */
  retries: 1,
  /* workers 数量 */
  workers: 1,
  /* 报告生成 */
  reporter: [
    ['list'],
    ['html', { outputFolder: 'playwright-report' }],
  ],
  /* 全局设置 */
  use: {
    /* 基础 URL */
    baseURL: 'http://localhost:8000',
    /* 跟踪：仅在失败时记录 */
    trace: 'retain-on-failure',
    /* 截图：仅在失败时 */
    screenshot: 'only-on-failure',
    /* 浏览器上下文 */
    viewport: { width: 1280, height: 720 },
    /* 模拟移动设备 */
    isMobile: false,
  },

  /* 项目配置 */
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        /* headless 模式 */
        launchOptions: {
          headless: true,
        },
      },
    },
  ],
});
