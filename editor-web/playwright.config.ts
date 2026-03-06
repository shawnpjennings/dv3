import { defineConfig } from '@playwright/test';
export default defineConfig({
  use: { baseURL: 'http://localhost:5174', headless: true },
  testDir: './tests-pw',
});
