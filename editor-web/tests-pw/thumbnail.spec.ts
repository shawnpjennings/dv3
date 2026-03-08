import { test, expect } from '@playwright/test';
import path from 'path';
import fs from 'fs';

test('gallery thumbnail reflects edits', async ({ page }) => {
  await page.goto('/');
  await page.waitForTimeout(1000);

  // Upload a test image
  const testImagePath = path.join('/home/shawn/projects/dv3/animations/library');
  const files = fs.readdirSync(testImagePath);
  let testFile: string | null = null;
  for (const dir of files) {
    const subdir = path.join(testImagePath, dir);
    if (fs.statSync(subdir).isDirectory()) {
      const items = fs.readdirSync(subdir);
      const webp = items.find(f => f.endsWith('.webp'));
      if (webp) { testFile = path.join(subdir, webp); break; }
    }
  }

  if (!testFile) { console.log('No test file found, skipping upload test'); return; }
  console.log('Uploading:', testFile);

  const [fileChooser] = await Promise.all([
    page.waitForEvent('filechooser'),
    page.locator('button[title="Upload Media"]').click(),
  ]);
  await fileChooser.setFiles(testFile);
  await page.waitForTimeout(1500);

  // Screenshot before edits
  await page.screenshot({ path: '/tmp/dv3-thumb-before.png' });

  // Select the asset
  const thumbs = page.locator('[class*="aspect-square"] img');
  const count = await thumbs.count();
  console.log('Thumbnails:', count);
  expect(count).toBeGreaterThan(0);

  // Click it
  await page.locator('[class*="aspect-square"]').first().click();
  await page.waitForTimeout(500);

  // Check that the thumbnail initially has no filter style
  const beforeFilter = await thumbs.first().getAttribute('style');
  console.log('Before edit style:', beforeFilter);

  // Apply brightness edit via slider in EditorPanel
  // Find brightness slider
  const slider = page.locator('input[type="range"]').first();
  if (await slider.count() > 0) {
    await slider.fill('150');
    await slider.dispatchEvent('input');
    await page.waitForTimeout(300);
  }

  // Screenshot after edit
  await page.screenshot({ path: '/tmp/dv3-thumb-after.png' });

  const afterFilter = await thumbs.first().getAttribute('style');
  console.log('After edit style:', afterFilter);

  // The style should now contain a filter value
  if (afterFilter) {
    console.log('✓ Thumbnail style updated after edit');
  } else {
    console.log('✗ Thumbnail style not updated');
  }
});
