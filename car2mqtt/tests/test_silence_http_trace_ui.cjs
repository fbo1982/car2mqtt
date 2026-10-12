// Usage: node tests/test_silence_http_trace_ui.cjs rendered-index.html [screenshot-dir]
// Requires Playwright; CHROMIUM_PATH optionally selects an installed browser.
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const { chromium } = require('playwright');

(async () => {
  const html = await fs.readFile(process.argv[2], 'utf8');
  const downloadsPath = path.resolve(path.dirname(process.argv[2]), 'browser-downloads');
  await fs.mkdir(downloadsPath, {recursive:true});
  const browser = await chromium.launch({headless: true, downloadsPath,
    ...(process.env.CHROMIUM_PATH ? {executablePath: process.env.CHROMIUM_PATH} : {})});
  let checks = 0;
  const check = (value, name) => { assert.ok(value, name); checks++; console.log('PASS ' + name); };
  try {
    for (const prefix of ['/', '/api/hassio_ingress/test-token/']) {
      const page = await browser.newPage({viewport:{width:1280,height:960}, acceptDownloads:true});
      page.setDefaultTimeout(7000);
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      let vehicle = {id:'TEST', label:'Silence Test', manufacturer:'acconia', license_plate:'TEST', enabled:true,
        provider_config:{account:'test@example.invalid',password:'dummy',http_raw_debug:false},
        provider_state:{auth_state:'authorized'},mqtt_client_ids:[]};
      let created = null;
      let mode = 'available';
      let delayed = null;
      let releaseDelay;
      const logText = 'HTTP 200 – Prüfung\n<script>window.traceExecuted=true</script>\n<img src=x onerror="window.traceExecuted=true">\n';
      const missingText = 'Noch keine HTTP-Diagnoselogdatei vorhanden. HTTP-Rohdaten-Diagnose einschalten, speichern und den nächsten Poll abwarten.';
      const traceRequests = [];
      await page.route('**/*', async route => {
        const request = route.request();
        const url = new URL(request.url());
        assert.equal(url.origin, 'http://127.0.0.1');
        assert.ok(url.pathname.startsWith(prefix), 'Ingress prefix must be retained');
        const endpoint = url.pathname.slice(prefix.length);
        if (!endpoint) return route.fulfill({contentType:'text/html; charset=utf-8',body:html});
        if (endpoint.endsWith('/mysilence/http-trace')) {
          traceRequests.push(url.pathname + url.search);
          if (mode === 'network-error') return route.abort('failed');
          if (mode === 'delayed') {
            delayed = new Promise(resolve => { releaseDelay = resolve; });
            await delayed;
            return route.fulfill({contentType:'text/plain; charset=utf-8',body:'OLD VEHICLE LOG'});
          }
          const status = mode === 'missing' || mode === 'wrong-vehicle' ? 404 : mode === 'error' ? 500 : 200;
          const body = mode === 'missing' ? missingText : mode === 'empty' ? '' : mode === 'wrong-vehicle' ? 'MySilence Fahrzeug nicht gefunden' : mode === 'error' ? 'HTTP-Diagnoselog konnte nicht gelesen werden.' : logText;
          const headers = {'Content-Type':'text/plain; charset=utf-8', 'Cache-Control':'no-store'};
          if (mode !== 'wrong-vehicle') headers['X-Car2MQTT-Trace-Status'] = mode;
          return route.fulfill({status,headers,body});
        }
        if (endpoint.endsWith('/logs')) return route.fulfill({contentType:'text/plain',body:'Test vehicle log'});
        if (endpoint === 'api/dashboard') return route.fulfill({json:{vehicles:[],mqtt:{}}});
        if (endpoint === 'api/vehicles' && request.method() === 'POST') {
          created = request.postDataJSON();
          return route.fulfill({json:{status:'ok',vehicle_id:created.id}});
        }
        if (endpoint.startsWith('api/vehicles/')) {
          if (request.method() === 'PUT') {
            vehicle = {...vehicle,...request.postDataJSON()};
            return route.fulfill({json:{status:'ok',vehicle_id:vehicle.id}});
          }
          return route.fulfill({json:{...vehicle,id:endpoint.split('/').pop()}});
        }
        throw new Error('Unexpected request: ' + request.url());
      });
      await page.goto('http://127.0.0.1' + prefix);
      check(await page.evaluate(() => {
        const ids = [...document.querySelectorAll('[id]')].map(el=>el.id);
        return new Set(ids).size === ids.length;
      }), prefix + ' all HTML IDs unique');
      await page.evaluate(() => { document.getElementById('acconiaHttpRawDebug').checked = true; });
      await page.evaluate(() => editVehicle('TEST'));
      check(!await page.locator('#editAcconiaHttpRawDebug').isChecked(), 'edit reads saved setting');
      check(await page.locator('#acconiaHttpRawDebug').isChecked(), 'edit leaves create checkbox independent');
      await page.locator('#editAcconiaHttpRawDebug').check();
      await page.locator('#saveEditKeepOpenBtn').click();
      await page.waitForFunction(() => !document.getElementById('saveEditKeepOpenBtn').disabled);
      check(vehicle.provider_config.http_raw_debug === true, 'edit saves enabled setting');
      await page.locator('#closeEditBtn').click();
      await page.evaluate(() => editVehicle('TEST'));
      check(await page.locator('#editAcconiaHttpRawDebug').isChecked(), 'reopen restores saved setting');
      await page.locator('#editAcconiaHttpRawDebug').uncheck();
      await page.locator('#saveEditKeepOpenBtn').click();
      await page.waitForFunction(() => !document.getElementById('saveEditKeepOpenBtn').disabled);
      check(vehicle.provider_config.http_raw_debug === false, 'edit saves disabled setting');
      const load = async () => {
        await page.locator('#silenceRawLogBtn').click();
        await page.waitForFunction(() => !document.getElementById('silenceRawLogBtn').disabled);
      };
      await load();
      check(await page.locator('#silenceRawLogViewer').textContent() === logText, 'log visible as exact text');
      check(await page.locator('#silenceRawLogViewer script, #silenceRawLogViewer img').count() === 0 &&
        !await page.evaluate(() => window.traceExecuted), 'log HTML cannot execute');
      if (process.argv[3]) {
        await fs.mkdir(process.argv[3], {recursive:true});
        await page.locator('#silenceRawLogPanel').screenshot({path:path.join(process.argv[3], prefix==='/'?'log-direct.png':'log-ingress.png')});
      }
      const downloadPromise = page.waitForEvent('download');
      await page.locator('#silenceRawLogDownloadBtn').click();
      const download = await downloadPromise;
      check(download.suggestedFilename() === 'mysilence-http-diagnose.log' &&
        await fs.readFile(await download.path(), 'utf8') === logText, 'download filename and text match');
      check(traceRequests.at(-1).endsWith('?download=true'), 'download endpoint is used');
      mode = 'missing';
      await load();
      check((await page.locator('#silenceRawLogStatus').textContent()).includes('Noch keine') &&
        await page.locator('#silenceRawLogDownloadBtn').isDisabled() &&
        await page.locator('#silenceRawLogViewer').textContent() === '', 'missing file status and stale log cleared');
      mode = 'empty';
      await load();
      check((await page.locator('#silenceRawLogStatus').textContent()).includes('noch keine Einträge') &&
        !await page.locator('#silenceRawLogDownloadBtn').isDisabled(), 'empty file differs from missing file');
      for (mode of ['error','network-error','wrong-vehicle']) {
        await load();
        check((await page.locator('#silenceRawLogStatus').textContent()).includes('konnte nicht geladen werden') &&
          await page.locator('#silenceRawLogDownloadBtn').isDisabled(), mode + ' visible and retry enabled');
      }
      mode = 'delayed';
      await page.locator('#silenceRawLogBtn').click();
      await page.waitForFunction(() => document.getElementById('silenceRawLogBtn').disabled);
      // Wait until the intercepted request is held, without depending on a fixed delay.
      while (!releaseDelay) await new Promise(resolve => setImmediate(resolve));
      await page.locator('#closeEditBtn').click();
      await page.evaluate(() => editVehicle('OTHER'));
      const staleResponse = page.waitForResponse(response=>response.url().includes('/TEST/mysilence/http-trace'));
      releaseDelay();
      await staleResponse;
      await page.evaluate(() => new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
      check(await page.locator('#silenceRawLogPanel').isHidden() &&
        await page.locator('#silenceRawLogViewer').textContent() === '', 'late response cannot overwrite another vehicle');
      await page.locator('#closeEditBtn').click();
      await page.evaluate(() => openWizard());
      await page.locator('#createManufacturer').selectOption('acconia');
      check(!await page.locator('#acconiaHttpRawDebug').isChecked(), 'create resets diagnosis to off');
      await page.locator('#vehicleLabel').fill('New Silence');
      await page.locator('#vehiclePlate').fill('NEW');
      await page.locator('#acconiaAccount').fill('new@example.invalid');
      await page.locator('#acconiaPassword').fill('dummy');
      await page.locator('#acconiaHttpRawDebug').check();
      await page.locator('#saveCreateBtn').click();
      await page.waitForFunction(() => !document.getElementById('wizardDialog').open);
      check(created.provider_config.http_raw_debug === true, 'create sends its own diagnosis setting');
      check(errors.length === 0, 'no browser JavaScript errors: ' + errors.join('; '));
      await page.close();
    }
    console.log(`RESULT: ${checks} browser checks passed`);
  } finally {
    await browser.close();
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
