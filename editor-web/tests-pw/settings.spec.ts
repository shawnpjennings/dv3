import { test, expect } from '@playwright/test';

test('settings modal opens and shows folder picker section', async ({ page }) => {
  await page.goto('/');
  await page.waitForTimeout(1500);

  // Click the Settings button (title="Settings")
  await page.locator('button[title="Settings"]').click();
  await page.waitForTimeout(500);
  await page.screenshot({ path: '/tmp/dv3-settings-modal.png' });

  // Verify the folder picker section
  const folderLabel = page.getByText('DV3 Library Folder');
  expect(await folderLabel.isVisible()).toBeTruthy();
  console.log('DV3 Library Folder label: ✓');

  const notSetText = page.getByText('Not set — exports will download as ZIP');
  expect(await notSetText.isVisible()).toBeTruthy();
  console.log('Not set text: ✓');

  const selectBtn = page.getByText('Select data/animations Folder');
  expect(await selectBtn.isVisible()).toBeTruthy();
  console.log('Select folder button: ✓');

  const defaultPaddingLabel = page.getByText('Default Size / Zoom Offset (px)');
  expect(await defaultPaddingLabel.isVisible()).toBeTruthy();
  console.log('Default padding setting: ✓');

  const doneBtn = page.getByText('Done');
  expect(await doneBtn.isVisible()).toBeTruthy();
  console.log('Done button: ✓');
});
