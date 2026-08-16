import { test, expect } from '@playwright/test';

test.describe('Station 3: Color Science & ColorChecker Calibration', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/calibration');
  });

  test('CAL-01: renders 24-patch ColorChecker grid and corner anchors', async ({ page }) => {
    await expect(page.getByText('X-Rite ColorChecker Classic (24 Patch)')).toBeVisible();

    // Verify swatch buttons exist (#1 to #24)
    await expect(page.getByRole('button', { name: '#1', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: '#15', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: '#24', exact: true })).toBeVisible();
  });

  test('CAL-02: selects individual swatches and updates deep patch inspector', async ({ page }) => {
    // Select Patch #3 (Blue Sky)
    const patch3 = page.getByRole('button', { name: '#3', exact: true });
    await patch3.click();

    // Verify deep inspector card updated
    await expect(page.getByText('Selected: Patch #3 (Blue Sky)')).toBeVisible();
    await expect(page.getByText('RGB(98, 122, 157)')).toBeVisible(); // Reference sRGB
    await expect(page.getByText('RGB(95, 126, 160)')).toBeVisible(); // Measured RGB
    await expect(page.getByText('0.94 ΔE', { exact: true })).toBeVisible();

    // Select Patch #12 (Orange Yellow)
    const patch12 = page.getByRole('button', { name: '#12', exact: true });
    await patch12.click();

    await expect(page.getByText('Selected: Patch #12 (Orange Yellow)')).toBeVisible();
    await expect(page.getByText('RGB(229, 160, 46)')).toBeVisible();
  });

  test('CAL-03: rotates target canvas by 90-degree increments and flips horizontally', async ({ page }) => {
    // Rotate canvas
    const rotateBtn = page.getByRole('button', { name: /Rotate 90°/i });
    await expect(rotateBtn).toBeVisible();
    await rotateBtn.click();
    await expect(page.getByText('Target canvas rotated to 90°')).toBeVisible();

    await rotateBtn.click();
    await expect(page.getByText('Target canvas rotated to 180°')).toBeVisible();

    // Flip canvas
    const flipBtn = page.getByRole('button', { name: /Flip H/i });
    await expect(flipBtn).toBeVisible();
    await flipBtn.click();
    await expect(page.getByText('Target flipped horizontally')).toBeVisible();
    await flipBtn.click();
    await expect(page.getByText('Target reset flip')).toBeVisible();
  });

  test('CAL-04: executes SAM auto-detection with confidence verification', async ({ page }) => {
    const autoDetectBtn = page.getByRole('button', { name: /Auto-Detect Swatches \(SAM\)/i });
    await expect(autoDetectBtn).toBeVisible();
    await autoDetectBtn.click();

    await expect(page.getByText(/Scanning ColorChecker grid/i)).toBeVisible();
    await expect(page.getByText(/24 \/ 24 Swatches Locked \(Confidence: 99.8%\)/i)).toBeVisible();
  });

  test('CAL-05: displays spectral Delta-E metrics and 3x3 CCM color correction matrix', async ({ page }) => {
    await expect(page.getByText('Calibration Metrics')).toBeVisible();
    await expect(page.getByText('AVG DELTA-E (CIE2000)')).toBeVisible();
    await expect(page.getByText('MAX DELTA-E')).toBeVisible();

    // 3x3 Color Correction Matrix
    await expect(page.getByText('CALCULATED 3x3 CCM MATRIX:')).toBeVisible();
    await expect(page.getByText(/\[ \+1\.542, -0\.412, -0\.098 \]/)).toBeVisible();
  });

  test('CAL-06: saves profile and exports ICC color profile (.icc)', async ({ page }) => {
    const profileInput = page.locator('input[type="text"]').last();
    await expect(profileInput).toBeVisible();
    await profileInput.fill('TEST-PROFILE-D65');

    const saveBtn = page.getByRole('button', { name: /SAVE & APPLY PROFILE/i });
    await saveBtn.click();
    await expect(page.getByText(/Profile "TEST-PROFILE-D65" saved/i)).toBeVisible();

    const exportBtn = page.getByRole('button', { name: /Export ICC Profile/i });
    await exportBtn.click();
    await expect(page.getByText(/Generated ICC Profile: TEST-PROFILE-D65\.icc/i)).toBeVisible();
  });
});
