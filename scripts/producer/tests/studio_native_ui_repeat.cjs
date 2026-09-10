/* Normal UI repeat/Undo imports for the opt-in headless Studio harness only.
 * No hidden API/DOM mutations; disk reads verify exact saved draft and cuts.
 */
async function importCopy(context, expected, version, label) {
  const {page, fixture, result, textClick, remaining, record, screenshot, fs, path} = context;
  await textClick(page, 'Preview Studio changes');
  await textClick(page, 'Apply to Sniper draft');
  await page.waitForFunction(() => document.querySelector('[aria-label="Import Studio changes"]')
    ?.textContent.includes('imported into the Sniper draft'), {timeout: remaining()});
  const plan = JSON.parse(fs.readFileSync(path.join(fixture.producer, 'edit_plan.json')));
  if (plan.planVersion !== version || plan.graphicsTrack[0].spec.text !== expected
      || JSON.stringify(plan.cutTrack) !== JSON.stringify(result.beforePlan.cutTrack)) {
    throw Error('Repeated native import changed unexpected canonical draft content');
  }
  await screenshot(label); record(label, {planVersion: version, text: expected});
  return plan;
}

async function repeatNativeImport(context) {
  const {studio, result, editNative, assertRenderedCopy, remaining, record} = context;
  const next = 'Review another clear point';
  await editNative(studio, next);
  await assertRenderedCopy(next);
  result.secondImport = await importCopy(context, next, 3, '09-second-copy-import');
  const undo = await studio.waitForSelector('button[aria-label="Undo"]:not([disabled])', {timeout: remaining()});
  const title = await undo.evaluate(node => node.title);
  if (!/Edit text/.test(title)) throw Error(`Native Undo is not bound to the just-edited text: ${title}`);
  await undo.click(); record('native-undo-copy', {title});
  await assertRenderedCopy('Review timing clearly');
  result.undoImport = await importCopy(context, 'Review timing clearly', 4, '10-native-undo-import');
  const final = context.path.join(context.fixture.producer, 'final.mp4');
  const approval = context.path.join(context.fixture.producer, '.sniper-qc-approved.json');
  if (context.fs.existsSync(final) || context.fs.existsSync(approval)) throw Error('Unexpected final or approval after native Undo import');
  result.nativeRepeatUndoPassed = true;
}

async function visiblePlayback(context, studio, expected, name) {
  const {assertRenderedCopy, remaining, sleep, screenshot, record} = context;
  await assertRenderedCopy(expected);
  await studio.waitForSelector('button[aria-label="Play"]:not([disabled])', {timeout: remaining()});
  await sleep(1500);
  await studio.click('button[aria-label="Play"]');
  await studio.waitForSelector('button[aria-label="Pause"]', {timeout: remaining()});
  await sleep(800);
  await studio.click('button[aria-label="Pause"]');
  const facts = await assertRenderedCopy(expected);
  if (facts.effectiveOpacity < 0.99 || facts.display === 'none' || facts.visibility !== 'visible') {
    throw Error('Copy exists but is not visibly painted at the held playback time');
  }
  await screenshot(name); record(name, facts); return facts;
}

module.exports = {repeatNativeImport, visiblePlayback};
