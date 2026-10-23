async (page) => {
  const check = (condition, message) => { if (!condition) throw new Error(message); };
  const base = 'http://127.0.0.1:8000';
  await page.locator('.mail-row').filter({hasText: 'Live delivery - automatic inbox refresh'}).waitFor({timeout: 20000});
  check(await page.evaluate(() => window.__inboxVisit === 'initial-render'), 'Delivery caused a full page reload');
  await page.clock.install();
  await page.goto(base + '/');
  await page.clock.pauseAt(new Date(Date.now() + 1000));
  let requests = 0;
  let fail = true;
  const routePattern = '**/inbox/updates/**';
  await page.route(routePattern, async route => {
    requests += 1;
    if (fail) await route.fulfill({status: 503, contentType: 'text/plain', body: 'Simulated outage'});
    else await route.continue();
  });
  try {
    const before = await page.locator('#inbox-content').innerHTML();
    await page.clock.runFor(10000);
    await page.locator('#inbox-status[data-state="error"]').waitFor();
    check(await page.locator('#inbox-content').innerHTML() === before, 'Failed request erased inbox');
    fail = false;
    await page.clock.runFor(10000);
    await page.locator('#inbox-status[data-state="live"]').waitFor();
    check(requests >= 2, 'Failed request was not retried');

    await page.evaluate(() => {
      Object.defineProperty(document, 'hidden', {configurable: true, get: () => true});
      document.dispatchEvent(new Event('visibilitychange'));
    });
    const hiddenCount = requests;
    await page.clock.runFor(30000);
    check(requests === hiddenCount, 'Polling continued in a hidden tab');
    const resumed = page.waitForResponse(response => response.url().includes('/inbox/updates/'));
    await page.evaluate(() => {
      delete document.hidden;
      document.dispatchEvent(new Event('visibilitychange'));
    });
    await resumed;
    await page.locator('#inbox-status[data-state="live"]').waitFor();
    check(requests > hiddenCount, 'Returning to the tab did not refresh');

    await page.context().setOffline(true);
    await page.getByText('Offline · waiting for connection', {exact: true}).waitFor();
    const offlineCount = requests;
    await page.clock.runFor(30000);
    check(requests === offlineCount, 'Polling continued offline');
    const reconnected = page.waitForResponse(response => response.url().includes('/inbox/updates/'));
    await page.context().setOffline(false);
    await reconnected;
    await page.locator('#inbox-status[data-state="live"]').waitFor();

    const manualCount = requests;
    const manual = page.waitForResponse(response => response.url().includes('/inbox/updates/'));
    await page.getByRole('link', {name: 'Refresh', exact: true}).click();
    await manual;
    check(requests === manualCount + 1, 'Manual refresh did not make exactly one request');
    const token = await page.locator('input[name="csrfmiddlewaretoken"]').first().inputValue();
    const logout = await page.request.post(base + '/logout/', {form: {csrfmiddlewaretoken: token}, headers: {Origin: base, Referer: base + '/'}});
    check(logout.ok(), 'Logout failed');
    await page.clock.runFor(10000);
    await page.waitForURL(url => url.pathname === '/login/');
    check(await page.locator('.mail-row').count() === 0, 'Private mail remained after session expiry');
    return {passed: ['real SMTP arrival without reload', 'network error preserves inbox', 'automatic retry', 'hidden-tab pause/resume', 'offline pause/reconnect', 'manual refresh', 'session-expiry redirect'], requests};
  } finally {
    await page.context().setOffline(false);
    await page.unroute(routePattern);
    await page.clock.resume();
  }
}
