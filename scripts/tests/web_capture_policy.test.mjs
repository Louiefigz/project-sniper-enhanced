import assert from 'node:assert/strict';
import { test } from 'node:test';
import { publicAddress, publicUrl, requestPolicy, validatePlan } from '../producer/studio/web_capture_policy.mjs';

const plan = { schemaVersion: 1, mode: 'capture', entity: 'Example brand', reason: 'Show the useful feature',
  expectedTitle: 'Example', verifiedBy: 'https://example.com', url: 'https://example.com/feature',
  allowedHosts: ['example.com'], viewport: { width: 540, height: 960, scale: 2 },
  duration: 8, fps: 25, holdStart: 1, holdEnd: 2,
  start: { selector: 'h1', text: 'Example', top: 150 }, end: { selector: 'h2', text: 'Feature', top: 150 } };

test('reject credentialed, non-HTTPS, private and nonstandard destinations', () => {
  for (const url of ['http://example.com', 'https://user:secret@example.com', 'file:///etc/passwd',
    'https://localhost', 'https://127.0.0.1', 'https://example.com:444', 'https://service.internal']) {
    assert.throws(() => publicUrl(url));
  }
  for (const address of ['127.0.0.1', '10.0.0.1', '172.16.4.1', '192.168.1.2', '169.254.169.254',
    '100.64.0.1', '::1', '::ffff:127.0.0.1', 'fe80::1', 'fc00::1', '2001:db8::1']) assert.equal(publicAddress(address), false);
  assert.equal(publicAddress('140.82.114.3'), true);
  assert.equal(publicAddress('2606:4700::1111'), true);
});

test('bound viewport, duration, holds and unique textual targets before browser launch', () => {
  assert.equal(validatePlan(plan), plan);
  for (const delta of [{ holdEnd: 0 }, { duration: 40 }, { holdStart: NaN }, { fps: 120 },
    { viewport: { width: 1920, height: 1920, scale: 2 } }, { end: { selector: 'h2', text: '', top: 100 } },
    { allowedHosts: ['other.example.com'] }]) assert.throws(() => validatePlan({ ...plan, ...delta }));
});

test('deny writes and unrelated hosts without even resolving their DNS', async () => {
  const allowed = await requestPolicy(plan);
  const request = (url, method = 'GET') => ({ url: () => url, method: () => method, isNavigationRequest: () => true });
  assert.equal(await allowed(request(plan.url, 'POST')), false);
  assert.equal(await allowed(request('https://unrelated.example.com')), false);
  assert.equal(await allowed(request('https://127.0.0.1')), false);
  assert.equal(await allowed(request('data:text/html,hi')), false);
});

test('section inspection uses the same target bounds without requiring a recording', () => {
  const inspection = { ...plan, mode: 'inspect', start: { selector: 'h4', text: 'Be specific', top: 160 } };
  delete inspection.duration;
  delete inspection.end;
  assert.equal(validatePlan(inspection), inspection);
  for (const start of [null, { selector: '', text: 'Be specific', top: 160 },
    { selector: 'h4', text: 'Be specific', top: 600 }]) {
    assert.throws(() => validatePlan({ ...inspection, start }));
  }
  delete inspection.start;
  assert.equal(validatePlan(inspection), inspection);
});
