import { test, expect } from '@playwright/test';

test.describe('Station 4: PBR Material Synthesis Lab', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/processing?batch=batch_silk_velvet_4355');
  });

  test('PBR-01: renders 2x2 quad material map viewports (Albedo, Normal, Roughness, Displacement)', async ({ page }) => {
    await expect(page.getByText('Photometric Stereo Material Extraction')).toBeVisible();

    await expect(page.getByText('ALBEDO (DIFFUSE BASE)')).toBeVisible();
    await expect(page.getByText('TANGENT NORMAL')).toBeVisible();
    await expect(page.getByText('ROUGHNESS (SPECULAR)')).toBeVisible();
    await expect(page.getByText('DISPLACEMENT (HEIGHT)')).toBeVisible();
  });

  test('PBR-02: toggles texture synthesis resolution between 4K and 8K MASTER', async ({ page }) => {
    const btn8k = page.getByRole('button', { name: '8K MASTER' });
    await expect(btn8k).toBeVisible();
    await btn8k.click();
    await expect(page.getByText(/Texture synthesis resolution set to 8K MASTER/i)).toBeVisible();
    await expect(btn8k).toHaveClass(/bg-accent/);

    const btn4k = page.getByRole('button', { name: '4K (4096px)' });
    await btn4k.click();
    await expect(page.getByText(/Texture synthesis resolution set to 4K/i)).toBeVisible();
    await expect(btn4k).toHaveClass(/bg-accent/);
  });

  test('PBR-03: adjusts 3D virtual light probe sphere to update normal specular reflection vector', async ({ page }) => {
    const probe = page.getByTitle(/Drag to adjust virtual 3D lighting vector/i);
    await expect(probe).toBeVisible();

    // Drag probe
    const box = await probe.boundingBox();
    if (box) {
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      await page.mouse.down();
      await page.mouse.move(box.x + box.width / 2 + 50, box.y + box.height / 2 + 50);
      await page.mouse.up();
      await expect(page.getByText(/Updated 3D virtual light probe vector/i)).toBeVisible();
    }
  });

  test('PBR-04: adjusts material presets, normal strength, roughness bias, and seamless tiling', async ({ page }) => {
    // Material class select
    const materialSelect = page.locator('select').first();
    await expect(materialSelect).toBeVisible();
    await materialSelect.selectOption('leather');
    await expect(page.getByText(/Material preset loaded: LEATHER/i)).toBeVisible();

    // Normal strength slider
    const normalSlider = page.locator('input[type="range"]').first();
    await normalSlider.fill('2.2');
    await normalSlider.dispatchEvent('change');
    await expect(page.getByText('2.2x')).toBeVisible();

    // Roughness bias slider
    const roughnessSlider = page.locator('input[type="range"]').nth(1);
    await roughnessSlider.fill('0.85');
    await roughnessSlider.dispatchEvent('change');
    await expect(page.getByText('0.85')).toBeVisible();

    // Seamless tiling checkbox
    const tilingCheck = page.locator('input[type="checkbox"]');
    await expect(tilingCheck).toBeChecked();
    await tilingCheck.uncheck();
    await expect(page.getByText(/Seamless boundary tiling: DISABLED/i)).toBeVisible();
    await tilingCheck.check();
    await expect(page.getByText(/Seamless boundary tiling: ENABLED/i)).toBeVisible();
  });

  test('PBR-05: executes PBR re-generation and exports glTF 2.0 package', async ({ page }) => {
    const regenBtn = page.getByRole('button', { name: /RE-GENERATE PBR TEXTURES/i });
    await expect(regenBtn).toBeVisible();
    await regenBtn.click();

    // Progress bar solving state
    await expect(page.getByText('Solving Surface Gradients...')).toBeVisible();

    // Completion notification
    await expect(page.getByText(/PBR Material Synthesis completed/i)).toBeVisible({ timeout: 10000 });

    // glTF export
    const exportBtn = page.getByRole('button', { name: /Export glTF 2\.0 Package/i });
    await expect(exportBtn).toBeVisible();
    await exportBtn.click();
    await expect(page.getByText(/Generated glTF 2\.0 Material Archive/i)).toBeVisible();
  });
});
