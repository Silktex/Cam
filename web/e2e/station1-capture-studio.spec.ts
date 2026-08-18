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

    // Real gphoto2-shaped Exposure Dial settings, stateful across GET/POST so
    // a slider commit is reflected back on the next read - the confirmed
    // camera value, not the value the user requested (#5, #8).
    const cameraSettings: Record<string, { name: string; label: string; type: string; readonly: boolean; value: string; choices?: string[]; range?: [number, number, number] }> = {
      shutterspeed: { name: 'shutterspeed', label: 'Shutter Speed', type: 'radio', readonly: false, value: '1/125', choices: ['1/8000', '1/4000', '1/2000', '1/1000', '1/500', '1/250', '1/125', '1/60', '1/30', '1/15', '1/8', '1/4', '1/2', '1'] },
      'f-number': { name: 'f-number', label: 'Aperture', type: 'radio', readonly: false, value: '8', choices: ['2.8', '4', '5.6', '8', '11', '16', '22'] },
      iso: { name: 'iso', label: 'ISO', type: 'radio', readonly: false, value: '100', choices: ['50', '100', '200', '400', '800', '1600', '3200', '6400'] },
      colortemperature: { name: 'colortemperature', label: 'Color Temperature', type: 'range', readonly: false, value: '5600', range: [2800, 7500, 100] },
    };

    await page.route('**/api/camera/settings', async (route) => {
      if (route.request().method() === 'POST') {
        const { name, value } = route.request().postDataJSON();
        if (cameraSettings[name]) cameraSettings[name].value = String(value);
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ success: true, name, value }),
        });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(Object.values(cameraSettings)),
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

  test('CAP-06: adjusts PTP exposure parameters using real camera-reported values (#8, #10, #11)', async ({ page }) => {
    // Initial exposure dials reflect the mocked /api/camera/settings response,
    // not a hardcoded guess.
    await expect(page.getByText('1/125s')).toBeVisible();
    await expect(page.getByText('f/8').first()).toBeVisible();
    await expect(page.getByText('ISO 100')).toBeVisible();
    await expect(page.getByText('5600K').first()).toBeVisible();

    // Dials are index-into-real-choices sliders (0-100 visual position mapped
    // to the nearest camera-supported value), not the old fixed value lists.
    // These are React-controlled range inputs with step="any", so drive them
    // via direct value assignment + native events rather than locator.fill()
    // (which rejects the non-integer percentages a fluid drag lands on).
    const sliders = page.locator('input[type="range"]');
    const pctForChoice = (idx: number, len: number) => (idx / (len - 1)) * 100;
    const setSlider = (index: number, percent: number) =>
      sliders.nth(index).evaluate((el: HTMLInputElement, value: number) => {
        el.value = String(value);
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
      }, percent);

    // Shutter: choices has 14 entries, move to index 4 ("1/500").
    await setSlider(0, pctForChoice(4, 14));
    await expect(page.getByText('1/500s').first()).toBeVisible();
    await expect(page.getByText(/Shutter Speed updated: 1\/500/i)).toBeVisible();

    // Aperture: choices has 7 entries, move to index 1 ("4").
    await setSlider(1, pctForChoice(1, 7));
    await expect(page.getByText('f/4').first()).toBeVisible();

    // ISO: choices has 8 entries, move to index 3 ("400").
    await setSlider(2, pctForChoice(3, 8));
    await expect(page.getByText('ISO 400').first()).toBeVisible();

    // White Balance: continuous range 2800-7500 step 100, move to 4500.
    await setSlider(3, ((4500 - 2800) / (7500 - 2800)) * 100);
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

    // Side spot buttons 1-8 (radial visualizer dot; the toggle-card grid
    // below also has a title containing "Side 1", so scope to the exact one)
    const spot1 = page.getByTitle('Side 1 (N)');
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
