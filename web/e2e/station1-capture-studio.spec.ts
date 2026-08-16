import { test, expect } from '@playwright/test';

test.describe('Station 1: Unified Capture Studio', () => {
  test.beforeEach(async ({ page }) => {
    // Intercept backend API calls with mock responses
    await page.route('**/api/camera/status', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          connected: true,
          model: 'Sony ILCE-7RM3',
          port: 'usb:001,005',
          battery_level: 95,
        }),
      });
    });

    await page.route('**/api/camera/autofocus', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          distance_meters: 0.82,
          lens: 'FE 90mm F2.8 Macro G OSS',
        }),
      });
    });

    await page.route('**/api/capture/images', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          folder: 'session_captures',
          count: 1,
          files: ['IMG_4356.ARW'],
        }),
      });
    });

    await page.route('**/api/camera/setting*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true }),
      });
    });

    await page.route('**/api/liveview/source', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          available: true,
          active: true,
          active_source: 'ptp',
          device_name: 'Sony ILCE-7RM3 Direct Preview',
        }),
      });
    });

    await page.goto('/');
  });

  test('CAP-01: renders live stream viewport, HW-encoded H.264 badge, and stream source switcher', async ({ page }) => {
    // Live Stream HUD badge
    await expect(page.getByText('LIVE STREAM (30 FPS)')).toBeVisible();
    await expect(page.getByText(/1080p H.264 \(HDMI HW Encoded\)/i)).toBeVisible();
    await expect(page.getByText(/SRC: HDMI/i)).toBeVisible();

    // Stream HUD overlay values
    await expect(page.getByText(/HIST:/)).toBeVisible();
    await expect(page.getByText(/BALANCED/)).toBeVisible();
    await expect(page.getByText(/EV:/)).toBeVisible();
    await expect(page.getByText(/TEMP:/)).toBeVisible();
    await expect(page.getByText(/AF-LOCK/)).toBeVisible();

    // Toggle Stream Source via UI button
    const srcBtn = page.getByRole('button', { name: /SRC: HDMI/i });
    await expect(srcBtn).toBeVisible();
    await srcBtn.click();
    await expect(page.getByText(/SRC: PTP/i)).toBeVisible();
    await expect(page.getByText(/Sensor Preview \(PTP USB\)/i)).toBeVisible();

    // Toggle back via 'S' keyboard shortcut
    await page.keyboard.press('s');
    await expect(page.getByText(/SRC: HDMI/i)).toBeVisible();
    await expect(page.getByText(/1080p H.264 \(HDMI HW Encoded\)/i)).toBeVisible();
  });

  test('CAP-02: toggles stream visual overlays (Grid, Zebra clipping, Focus peaking)', async ({ page }) => {
    // Toggle Grid
    const gridBtn = page.getByTitle('Toggle Grid Overlay');
    await expect(gridBtn).toBeVisible();
    await gridBtn.click();
    await expect(page.getByText(/Grid Overlay: OFF/i)).toBeVisible();
    await gridBtn.click();
    await expect(page.getByText(/Grid Overlay: ON/i)).toBeVisible();

    // Toggle Zebra Clipping
    const zebraBtn = page.getByTitle('Zebra Clipping Indicator');
    await expect(zebraBtn).toBeVisible();
    await zebraBtn.click();
    await expect(page.getByText(/Zebra Clipping: ACTIVE/i)).toBeVisible();

    // Toggle Focus Peaking
    const peakingBtn = page.getByTitle('Focus Peaking Edge Detect');
    await expect(peakingBtn).toBeVisible();
    await peakingBtn.click();
    await expect(page.getByText(/Focus Peaking Edge-Detection: ON/i)).toBeVisible();
  });

  test('CAP-03: triggers single autofocus and displays optical lock feedback', async ({ page }) => {
    const afBtn = page.getByRole('button', { name: /Trigger Autofocus/i });
    await expect(afBtn).toBeVisible();
    await afBtn.click();

    // Verify AF feedback toast
    await expect(page.getByText(/Autofocus locked: 0.82m/i).first()).toBeVisible();

    // Trigger AF via 'F' shortcut
    await page.keyboard.press('f');
    await expect(page.getByText(/Autofocus locked: 0.82m/i).first()).toBeVisible();
  });

  test('CAP-04: freezes and resumes live feed via button and L key shortcut', async ({ page }) => {
    const freezeBtn = page.getByRole('button', { name: /Freeze Frame/i });
    await expect(freezeBtn).toBeVisible();
    await freezeBtn.click();

    // Verify feed is frozen
    await expect(page.getByText('FROZEN', { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: /Resume Live Feed/i })).toBeVisible();

    // Resume via button
    await page.getByRole('button', { name: /Resume Live Feed/i }).click();
    await expect(page.getByText('FROZEN', { exact: true })).not.toBeVisible();

    // Toggle via 'L' key
    await page.keyboard.press('l');
    await expect(page.getByText('FROZEN', { exact: true })).toBeVisible();
    await page.keyboard.press('l');
    await expect(page.getByText('FROZEN', { exact: true })).not.toBeVisible();
  });

  test('CAP-05: captures 61MP RAW image and updates filmstrip', async ({ page }) => {
    const captureBtn = page.getByRole('button', { name: /CAPTURE RAW \(61MP\)/i });
    await expect(captureBtn).toBeVisible();
    await captureBtn.click();

    // Verify capture feedback toast
    await expect(page.getByText(/Captured RAW: IMG_4356.ARW/i)).toBeVisible();

    // Verify filmstrip updated with new alt image
    await expect(page.getByAltText('IMG_4356.ARW')).toBeVisible();

    // Trigger capture via Ctrl+S shortcut
    await page.keyboard.press('Control+s');
    await expect(page.getByText(/Captured RAW:/i)).toBeVisible();
  });

  test('CAP-06: adjusts PTP exposure parameters (Shutter, Aperture, ISO, White Balance)', async ({ page }) => {
    // Initial exposure dials
    await expect(page.getByText('1/125s')).toBeVisible();
    await expect(page.getByText('f/8.0').first()).toBeVisible();
    await expect(page.getByText('ISO 100')).toBeVisible();
    await expect(page.getByText('5600K').first()).toBeVisible();

    // Shutter speed slider interaction
    const sliders = page.locator('input[type="range"]');
    // First slider: Shutter
    await sliders.nth(0).fill('4'); // index 4 = 1/500s
    await sliders.nth(0).dispatchEvent('change');
    await expect(page.getByText('1/500s').first()).toBeVisible();

    // Second slider: Aperture
    await sliders.nth(1).fill('1'); // index 1 = f/4.0
    await sliders.nth(1).dispatchEvent('change');
    await expect(page.getByText('f/4.0').first()).toBeVisible();

    // Third slider: ISO
    await sliders.nth(2).fill('3'); // index 3 = ISO 400
    await sliders.nth(2).dispatchEvent('change');
    await expect(page.getByText('ISO 400').first()).toBeVisible();

    // Fourth slider: White Balance
    await expect(page.getByText('5600K').first()).toBeVisible();
    await sliders.nth(3).fill('4500');
    await sliders.nth(3).dispatchEvent('change');
    await expect(page.getByText('4500K').first()).toBeVisible();
  });

  test('CAP-07: controls integrated 9-LED radial lighting rig and master lux dimmer', async ({ page }) => {
    // Verify 9-Panel LED Rig title and Synced indicator
    await expect(page.getByText('9-PANEL LED RIG')).toBeVisible();

    // Center Top Dome button
    const topDome = page.getByTitle(/Top Dome Light/i);
    await expect(topDome).toBeVisible();
    await topDome.click();
    await expect(page.getByText(/TOP DOME:/i).first()).toBeVisible();

    // Side spot buttons 1-8
    const spot1 = page.getByTitle(/Side 1/i);
    await expect(spot1).toBeVisible();
    await spot1.click();
    await expect(page.getByText(/SIDE SPOT #1:/i).first()).toBeVisible();

    // Master Dimmer slider (5th slider on page)
    const masterSlider = page.locator('input[type="range"]').nth(4);
    await masterSlider.fill('75');
    await masterSlider.dispatchEvent('change');
    await expect(page.getByText('75 %')).toBeVisible();

    // ALL OFF / ALL ON master buttons
    const allOffBtn = page.getByRole('button', { name: 'ALL OFF' });
    await allOffBtn.click();
    await expect(page.getByText('All 9 LEDs turned OFF')).toBeVisible();

    const allOnBtn = page.getByRole('button', { name: 'ALL ON' });
    await allOnBtn.click();
    await expect(page.getByText('All 9 LEDs turned ON').first()).toBeVisible();

    // Spacebar toggles all lights
    await page.keyboard.press('Space');
    await expect(page.getByText(/All 9 LEDs turned/i).first()).toBeVisible();

    // 'T' key toggles top dome
    await page.keyboard.press('t');
    await expect(page.getByText(/TOP DOME:/i).first()).toBeVisible();

    // Number keys '1'..'8' toggle respective spotlights
    await page.keyboard.press('3');
    await expect(page.getByText(/SIDE SPOT #3:/i).first()).toBeVisible();
  });

  test('CAP-08: displays session filmstrip with link to asset lightbox gallery', async ({ page }) => {
    await expect(page.getByText('SESSION FILMSTRIP')).toBeVisible();
    await expect(page.getByAltText('IMG_4355.ARW')).toBeVisible();
    await expect(page.getByAltText('IMG_4354.ARW')).toBeVisible();

    const viewAllLink = page.getByRole('link', { name: /View All/i });
    await expect(viewAllLink).toBeVisible();
    await viewAllLink.click();
    await expect(page).toHaveURL(/\/gallery/);
  });
});
