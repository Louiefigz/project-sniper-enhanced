/** Public, fresh-session browser capture inputs; no credentials or page-authored code. */
import { lookup } from 'node:dns/promises';
import { isIP } from 'node:net';

export function publicUrl(value) {
  const url = new URL(value);
  if (url.protocol !== 'https:' || url.username || url.password || url.port
      || isIP(url.hostname) || !url.hostname.includes('.')
      || /(?:^|\.)(?:localhost|local|internal|test|invalid)$/iu.test(url.hostname)) {
    throw new Error('Capture requires a public HTTPS URL without credentials or a custom port');
  }
  return url;
}

/** Conservative public-address admission for the explicitly allowed asset hosts. */
export function publicAddress(address) {
  if (isIP(address) === 4) {
    const [a, b] = address.split('.').map(Number);
    return a !== 0 && a !== 10 && a !== 127 && a < 224
      && !(a === 169 && b === 254) && !(a === 172 && b >= 16 && b <= 31)
      && !(a === 192 && [0, 168].includes(b)) && !(a === 198 && [18, 19].includes(b))
      && !(a === 100 && b >= 64 && b <= 127);
  }
  return isIP(address) === 6 && /^2[0-9a-f]{3}:/iu.test(address)
    && !/^2001:(?:db8|0):/iu.test(address);
}

function validateTarget(target, height) {
  if (!target || typeof target.selector !== 'string' || !target.selector.trim() || target.selector.length > 200
      || typeof target.text !== 'string' || target.text.length < 3 || target.text.length > 240
      || !Number.isFinite(target.top) || target.top < 40 || target.top > height / 2) {
    throw new Error('Capture needs inspected start/end elements, exact text and a visible top offset');
  }
}

export function validatePlan(plan) {
  const url = publicUrl(plan.url);
  if (plan.schemaVersion !== 1 || !['inspect', 'capture'].includes(plan.mode)
      || !Array.isArray(plan.allowedHosts) || !plan.allowedHosts.includes(url.hostname)
      || plan.allowedHosts.length > 24) throw new Error('Explicit bounded capture host list required');
  plan.allowedHosts.forEach(host => {
    if (publicUrl(`https://${host}`).host !== host) throw new Error('Invalid capture host');
  });
  for (const text of [plan.entity, plan.reason, plan.expectedTitle]) {
    if (typeof text !== 'string' || text.length < 3 || text.length > 1200) throw new Error('Missing capture identity or editorial reason');
  }
  publicUrl(plan.verifiedBy);
  const { width, height, scale } = plan.viewport ?? {};
  if (![width, height].every(Number.isSafeInteger) || width < 480 || height < 640
      || width > 1920 || height > 1920 || ![1, 1.5, 2].includes(scale)
      || width * height * scale ** 2 > 1080 * 1920) throw new Error('Capture viewport exceeds the bounded portrait/desktop budget');
  if (plan.mode === 'inspect') {
    if (plan.start !== undefined) validateTarget(plan.start, height);
    return plan;
  }
  const { duration, holdStart, holdEnd, fps } = plan;
  if (![duration, holdStart, holdEnd].every(Number.isFinite) || duration < 4 || duration > 20
      || holdStart < .75 || holdEnd < 1 || duration - holdStart - holdEnd < 1
      || ![25, 30].includes(fps)) throw new Error('Capture needs a 4–20 second move with readable opening/result holds');
  for (const target of [plan.start, plan.end]) validateTarget(target, height);
  return plan;
}

/** Requests are GET/HEAD to admitted public hosts only, with cached DNS admission. */
export async function requestPolicy(plan) {
  const hosts = new Set(plan.allowedHosts), dns = new Map();
  async function publicHost(host) {
    if (!dns.has(host)) dns.set(host, lookup(host, { all: true }).then(rows =>
      rows.length > 0 && rows.every(row => publicAddress(row.address))).catch(() => false));
    return dns.get(host);
  }
  return async request => {
    if (!['GET', 'HEAD'].includes(request.method())) return false;
    if (/^(?:data|blob):/u.test(request.url()) && !request.isNavigationRequest()) return true;
    try {
      const url = publicUrl(request.url());
      return hosts.has(url.hostname) && await publicHost(url.hostname);
    } catch { return false; }
  };
}
