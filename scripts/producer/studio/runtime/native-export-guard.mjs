/** Fail before SDK initialization when a render bypasses the shared export owner. */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

function requireValue(value, message) {
  if (!value) throw new Error(`Native export admission: ${message}`);
}

function readRecord(file) {
  requireValue(typeof file === 'string' && path.isAbsolute(file), 'missing absolute owner/request path');
  const stat = fs.lstatSync(file);
  requireValue(stat.isFile() && !stat.isSymbolicLink() && stat.size <= 64 * 1024 ** 2
    && fs.realpathSync(file) === file, 'unsafe owner/request file');
  const bytes = fs.readFileSync(file);
  return { value: JSON.parse(bytes), sha: crypto.createHash('sha256').update(bytes).digest('hex') };
}

export function assertNativeRenderOwner(argv = process.argv.slice(2), environment = process.env) {
  if (argv.includes('--help') || argv.includes('-h')) return;
  const render = argv.findIndex(argument => argument === 'render' || argument === 'render-batch');
  if (render < 0) return;
  requireValue(render === 0 && argv[0] === 'render', 'batch/custom renders require the shared exporter');
  const file = environment.SNIPER_NATIVE_EXPORT_REQUEST;
  const request = readRecord(file), owner = readRecord(environment.SNIPER_NATIVE_EXPORT_OWNER).value;
  const pid = Number(environment.SNIPER_NATIVE_EXPORT_PID);
  requireValue(Number.isSafeInteger(pid) && pid > 1, 'missing live supervisor');
  process.kill(pid, 0);
  const record = request.value, pins = owner.additionalFilePinsBefore;
  requireValue(owner.project === record.project && path.dirname(file) === record.output
    && pins?.[file] === request.sha, 'owner does not bind the current request');
  requireValue(['preparing', 'waiting-for-capacity', 'running'].includes(owner.status)
    && !owner.abortReason && !owner.completedAt, 'owner is not active');
  const expectedWorker = record.adapter === 'native-long' ? 'native_long_worker.py' : 'native_short_worker.py';
  const phase = record.adapter === 'native-long' ? 'picture' : 'render';
  const args = owner.args;
  requireValue(Array.isArray(args) && args.length === 7 && args[0] === '/usr/bin/sandbox-exec'
    && path.basename(args[4]) === expectedWorker && args[5] === file && args[6] === phase,
  'render did not originate from the shared export worker');
  requireValue(path.resolve(argv[1]) === record.project && argv[argv.indexOf('--output') + 1]
    === path.join(record.output, 'picture.mp4'), 'SDK project/output differs from the admitted export');
  if (record.adapter === 'native-long') {
    const sampleFile = path.join(record.output, 'sample-qc/result.json');
    const samples = readRecord(sampleFile);
    requireValue(samples.value.passed === true && pins[sampleFile] === samples.sha,
      'long render omitted or changed its encoded seam checks');
  }
}

export function assertNativeCaptureOwner(file, environment = process.env) {
  requireValue(file === environment.SNIPER_NATIVE_EXPORT_REQUEST, 'capture requires the shared export supervisor');
  const request = readRecord(file), owner = readRecord(environment.SNIPER_NATIVE_EXPORT_OWNER).value;
  const pid = Number(environment.SNIPER_NATIVE_EXPORT_PID);
  requireValue(Number.isSafeInteger(pid) && pid > 1, 'capture has no live supervisor');
  process.kill(pid, 0);
  requireValue(owner.project === request.value.project && !owner.completedAt && !owner.abortReason
    && owner.additionalFilePinsBefore?.[file] === request.sha, 'capture owner/request differs');
  const args = owner.args;
  requireValue(Array.isArray(args) && args[0] === '/usr/bin/sandbox-exec' && args[5] === file
    && (args[6] === 'capture' || (args.length === 6 && path.basename(args[4]) === 'native_short_capture.mjs')),
  'capture did not originate from its shared worker');
}

/** Preview capture is restricted to its own shared worker and output phase. */
export function assertNativePreviewOwner(file, environment = process.env) {
  requireValue(file === environment.SNIPER_NATIVE_EXPORT_REQUEST, 'preview requires the shared export supervisor');
  const request = readRecord(file), owner = readRecord(environment.SNIPER_NATIVE_EXPORT_OWNER).value;
  const pid = Number(environment.SNIPER_NATIVE_EXPORT_PID);
  requireValue(Number.isSafeInteger(pid) && pid > 1, 'preview has no live supervisor');
  process.kill(pid, 0);
  const worker = request.value.adapter === 'native-long' ? 'native_long_worker.py' : 'native_short_worker.py';
  requireValue(owner.project === request.value.project && !owner.completedAt && !owner.abortReason
    && owner.additionalFilePinsBefore?.[file] === request.sha, 'preview owner/request differs');
  const args = owner.args;
  const phase=Array.isArray(args)?args[6]:null;
  const match=/^preview-picture-(0|[1-9][0-9]{0,2})$/.exec(phase??'');
  requireValue(match&&Number(match[1])<768&&args.length===7&&args[0]==='/usr/bin/sandbox-exec'
    &&path.basename(args[4])===worker&&args[5]===file
    &&owner.output===path.join(request.value.output,`${phase}.json`), 'preview did not originate from its shared section worker');
}

/** Kept separate from module import so tests never initialize or launch the SDK. */
export function admitNativeCommand() {
  try {
    assertNativeRenderOwner();
  } catch (error) {
    console.error(`${error.message}\nUse scripts/producer/studio/native_export.py PROJECT NEW_ATTEMPT.`);
    process.exitCode = 1;
    return false;
  }
  return true;
}
