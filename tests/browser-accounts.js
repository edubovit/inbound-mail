async (page) => {
  const credentials = __TEST_CREDENTIALS__;
  const config = __TEST_CONFIG__;
  const base = config.base_url;
  const check = (condition, message) => { if (!condition) throw new Error(message); };
  await page.goto(base + '/login/');
  await page.getByLabel('Username or email').fill(credentials.admin);
  await page.getByLabel('Password:', {exact: true}).fill(credentials.admin_password);
  await page.getByRole('button', {name: 'Sign in', exact: true}).click();
  await page.getByRole('link', {name: 'Accounts', exact: true}).click();
  check(await page.getByText('Disk used:', {exact: false}).count() > 0, 'Admin disk status absent');
  for (const [username, role] of [['browser-user', 'USER'], ['browser-admin', 'ADMIN']]) {
    await page.getByRole('link', {name: 'Create account', exact: true}).click();
    await page.getByLabel('Username:', {exact: true}).fill(username);
    await page.getByLabel('Role:', {exact: true}).selectOption(role);
    await page.getByLabel('Mailbox quota (MiB)').fill('64');
    await page.getByLabel('Temporary password').fill(credentials.user_password);
    await page.getByRole('button', {name: 'Create account', exact: true}).click();
    check(await page.getByRole('link', {name: username + '@' + config.mail_domain, exact: true}).count() === 1, 'Account creation failed');
  }
  await page.screenshot({path: config.artifacts_dir + '/browser-admin-desktop.png', fullPage: true});
  await page.getByRole('button', {name: 'Sign out', exact: true}).click();
  return {passed: ['HTTPS login', 'admin disk status', 'create USER', 'create ADMIN', 'logout'], url: page.url()};
}
