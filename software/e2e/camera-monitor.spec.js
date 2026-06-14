const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  
  // Step 2: Navigate to main page
  console.log("=== STEP 2: Navigate and edit test-1 ===");
  await page.goto('http://localhost:8000');
  await page.waitForTimeout(2000);
  
  // Take initial screenshot
  await page.screenshot({ path: '/tmp/test_step2_initial.png', fullPage: true });
  
  // Check if test-1 exists
  const bodyText = await page.locator('body').textContent();
  console.log("test-1 in page:", bodyText.includes('test-1'));
  
  // Find edit buttons
  const editButtons = page.locator('button').filter({ hasText: '编辑' });
  const editCount = await editButtons.count();
  console.log("Edit buttons found:", editCount);
  
  if (editCount === 0) {
    // Maybe it uses a different label
    const allButtons = await page.locator('button').allTextContents();
    console.log("All buttons:", allButtons.map(t => t.trim()).filter(Boolean).join(' | '));
  }
  
  // Click edit for test-1
  let clicked = false;
  for (let i = 0; i < editCount; i++) {
    const btn = editButtons.nth(i);
    const row = btn.locator('xpath=ancestor::*[contains(@class,"experiment") or contains(@class,"exp") or self::tr or self::li]').first();
    let rowText = '';
    try { rowText = await row.textContent(); } catch(e) { rowText = ''; }
    if (rowText.includes('test-1')) {
      console.log(`Clicking edit button #${i} for test-1`);
      await btn.click();
      clicked = true;
      break;
    }
  }
  
  if (!clicked && editCount > 0) {
    console.log("Clicking first edit button as fallback");
    await editButtons.first().click();
  }
  
  // Wait for experiment context to load
  await page.waitForTimeout(4000);
  
  // Step 2 evaluate
  console.log("\n=== STEP 2 EVALUATE ===");
  const step2Data = await page.evaluate(() => ({
    currentExperimentId: typeof currentExperimentId !== 'undefined' ? currentExperimentId : 'MISSING',
    bgImageData: typeof bgImageData !== 'undefined' ? (bgImageData ? `${bgImageData.width}x${bgImageData.height}` : 'null') : 'MISSING',
    zonesCount: typeof zones !== 'undefined' ? zones.length : 'MISSING',
    detectInterval: typeof detectInterval !== 'undefined' ? (detectInterval ? 'RUNNING' : 'null') : 'MISSING',
    camSelectValue: document.getElementById('camSelect')?.value || '(empty)',
    camSelectText: document.getElementById('camSelect')?.selectedOptions[0]?.textContent || '',
    _detectFrame: !!window._detectFrame,
    _detectFrameTs: window._detectFrameTs || 'undefined',
    cameraStreamActive: !!(typeof cameraStream !== 'undefined' && cameraStream && cameraStream.active),
    _cameraListReady: typeof _cameraListReady !== 'undefined' ? 'exists' : 'MISSING',
  }));
  console.log(JSON.stringify(step2Data, null, 2));
  
  await page.screenshot({ path: '/tmp/test_step2_after_edit.png', fullPage: true });
  
  // Step 3: Click "运行监控" tab
  console.log("\n=== STEP 3: Switch to monitor tab ===");
  
  // Find tabs
  const tabElements = page.locator('.tab-btn, [role="tab"], .nav-tab');
  const tabCount = await tabElements.count();
  console.log("Tab elements:", tabCount);
  
  // Try multiple strategies
  const monitorTab = page.locator('button:has-text("运行监控"), a:has-text("运行监控"), [data-tab="monitor"], .tab-btn:has-text("运行监控")');
  const monitorCount = await monitorTab.count();
  console.log("Monitor tab matches:", monitorCount);
  
  if (monitorCount > 0) {
    await monitorTab.first().click();
  } else {
    // Click by text content
    const allBtns = await page.locator('button, .tab-btn').allTextContents();
    console.log("All clickable texts:", allBtns.filter(t => t.trim()).join(' | '));
    
    // Try finding with broader text match
    const broader = page.locator(':text("监控")');
    const broaderCount = await broader.count();
    console.log("Elements with '监控':", broaderCount);
    if (broaderCount > 0) {
      await broader.first().click();
    }
  }
  
  await page.waitForTimeout(2000);
  
  // Step 3 evaluate
  console.log("\n=== STEP 3 EVALUATE ===");
  const step3Data = await page.evaluate(() => ({
    hasFresh: !!(window._detectFrame && window._detectFrameTs && (Date.now() - window._detectFrameTs) < 500),
    _detectFrameAge: window._detectFrameTs ? (Date.now() - window._detectFrameTs) + 'ms' : 'no ts',
    monitorStatus: document.getElementById('monitorCameraStatus')?.textContent || '(element not found)',
    monitorCardDisplay: document.getElementById('monitorCameraCard')?.style?.display || '(no style)',
    monitorVideoSrcSet: !!(document.getElementById('monitorCamVideo')?.srcObject),
  }));
  console.log(JSON.stringify(step3Data, null, 2));
  
  await page.screenshot({ path: '/tmp/test_step3_monitor.png', fullPage: true });
  
  // Also check the monitor camera card visibility
  const monitorCard = page.locator('#monitorCameraCard');
  const monitorCardVisible = await monitorCard.isVisible().catch(() => false);
  console.log("monitorCameraCard visible:", monitorCardVisible);
  
  await browser.close();
  console.log("\n=== BROWSER TESTS DONE ===");
})();
