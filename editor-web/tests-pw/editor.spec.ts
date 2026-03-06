import { test, expect } from '@playwright/test';

test('editor loads', async ({ page }) => {
  await page.goto('/');
  await page.waitForTimeout(2000);
  await page.screenshot({ path: '/tmp/dv3-initial.png' });
  const buttons = await page.locator('button').count();
  console.log('Buttons visible:', buttons);
  expect(buttons).toBeGreaterThan(0);
});

test('settings modal shows folder picker', async ({ page }) => {
  await page.goto('/');
  await page.waitForTimeout(1500);

  // Find the settings/gear button
  const gearBtn = page.locator('button svg').filter({ has: page.locator('[data-lucide="settings"]') }).locator('..');
  const gearCount = await gearBtn.count();
  console.log('Gear buttons found:', gearCount);

  // Try clicking the last button in the toolbar (typically settings)
  const allBtns = await page.locator('button').all();
  console.log('Total buttons:', allBtns.length);

  // Look for a button near the end that might be settings
  for (let i = Math.max(0, allBtns.length - 5); i < allBtns.length; i++) {
    const txt = await allBtns[i].textContent().catch(() => '');
    const title = await allBtns[i].getAttribute('title').catch(() => '');
    console.log(`Button ${i}: text="${txt}" title="${title}"`);
  }

  await page.screenshot({ path: '/tmp/dv3-loaded.png' });
});
