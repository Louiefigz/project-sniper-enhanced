import { execFile } from "node:child_process";
import path from "node:path";
import { pythonInterpreter, SCRIPTS_DIR } from "../../_lib/spawn-python";
import { StudioError, type StudioInspection } from "./model";
import { hasImportedPlan } from "./import/chain";

export const STUDIO_CLI = path.join(process.cwd(), "templates", "motion", "node_modules", "hyperframes", "dist", "cli.js");
const PRODUCER_SCRIPTS = path.join(SCRIPTS_DIR, "producer");

/** Bounded argv-only execution. Never pass user text to a shell. */
export function runStudioCommand(command: string, args: string[], timeout = 15_000,
  preview = false): Promise<string> {
  return new Promise((resolve, reject) => {
    execFile(command, args, {
      timeout, maxBuffer: 1024 * 1024, encoding: "utf8",
      env: { ...process.env, HYPERFRAMES_PREVIEW_HOST: "127.0.0.1",
        ...(preview ? { HYPERFRAMES_NO_TELEMETRY: "1", DO_NOT_TRACK: "1", NODE_OPTIONS: `--require ${JSON.stringify(path.join(process.cwd(),
          "src", "app", "api", "producer", "studio", "loopback-only.cjs"))}` } : {}) },
    }, (error, stdout, stderr) => {
      if (!error) return resolve(stdout);
      const timedOut = "killed" in error && error.killed;
      reject(new StudioError(timedOut ? "Studio operation timed out; existing edits were not discarded"
        : `Studio could not open: ${(stderr || stdout || error.message).slice(-1_200)}`,
      timedOut ? 504 : 502, timedOut ? "STUDIO_TIMEOUT" : "STUDIO_PROCESS_FAILED"));
    });
  });
}

// Read-only admission: opening legacy host HTML must not cause upstream's
// ID persistence to rewrite it. Do not migrate or rebaseline pending edits.
const HOST_IDS_CHECK = `
from html.parser import HTMLParser
class HostIds(HTMLParser):
 def __init__(self) -> None:
  super().__init__(); self.body=False; self.hosts=0; self.seen=set(); self.invalid=False
 def handle_starttag(self, tag:str, attrs:list) -> None:
  if tag=='body': self.body=True; return
  if not self.body: return
  ids=[value for name,value in attrs if name=='data-hf-id']; value=ids[0] if ids else None
  if len(ids)>1 or (value and value in self.seen): self.invalid=True
  if value: self.seen.add(value)
  if tag in {'script','style','template','meta','link','noscript','base'}: return
  self.hosts+=1
  if not value or not value.strip(): self.invalid=True
 def handle_endtag(self, tag:str) -> None:
  if tag=='body': self.body=False
def host_id_blocker(studio_dir:str) -> bool:
 source=os.path.join(studio_dir,'index.html')
 if not os.path.isfile(source): return False
 parser=HostIds()
 with open(source,encoding='utf-8') as handle: parser.feed(handle.read())
 return parser.invalid or parser.hosts==0
`;

// Reuse the renderer's actual fingerprint and Studio's actual diff semantics.
// This bridge only inspects files; none of these functions render or write.
const INSPECT = `
import hashlib,json,os,sys
${HOST_IDS_CHECK}
sys.path.insert(0,sys.argv[1])
from assemble import _base_state
from studio.sync_diff import load_state
from studio.sync_model import StudioSyncError
from studio.view_manifest import unsynced_changes
d=sys.argv[2]; s=os.path.join(d,'studio'); blockers=[]
p=os.path.join(d,'edit_plan.json'); b=os.path.join(d,'base_final.mp4')
f=os.path.join(d,'base.fingerprint.json'); exists=os.path.isfile(os.path.join(s,'studio.manifest.json'))
current=False; pending=[]; seed=hashlib.sha256()
for v in [p,f,os.path.join(d,'base_plan.json'),os.path.join(os.path.dirname(d),'project.json')]:
 if os.path.isfile(v): seed.update(v.encode()); seed.update(open(v,'rb').read())
if not os.path.isfile(p): blockers.append('Create an edit plan before opening Studio')
elif not os.path.isfile(b): blockers.append('Render a graphics-free base in Sniper before opening Studio')
else:
 st=os.stat(b); seed.update(str((st.st_size,st.st_mtime_ns,st.st_ino)).encode())
 plan=json.load(open(p)); state=_base_state(b,plan,f)
 if state!='current': blockers.append('The graphics-free base is '+state+'; render updated video in Sniper first')
 if not plan.get('graphicsTrack'): blockers.append('This plan has no graphics to review in Studio')
if os.path.isdir(s):
 pending=[x for x in unsynced_changes(s) if not x.startswith('.studio-server.json:')]
 if host_id_blocker(s): blockers.append('This saved Studio host has missing or duplicate element IDs. Opening could rewrite your source. Preserve and review any pending edits, then explicitly regenerate a clean Studio view; no files were changed.')
if exists:
 try:
  loaded=load_state(s,p); fp=loaded.fingerprint.get('base',{}); st=os.stat(b)
  current=fp.get('path')==b and fp.get('bytes')==st.st_size and fp.get('mtimeNs')==st.st_mtime_ns
 except (StudioSyncError,OSError,ValueError,KeyError,TypeError): current=False
if not current and pending: blockers.append('Studio edits belong to an older or unbound plan/base; resolve them before refreshing')
print(json.dumps(dict(parent=seed.hexdigest(),viewExists=exists,viewCurrent=current,pendingEdits=pending,blockers=blockers)))
`;

export async function inspectStudio(dir: string): Promise<StudioInspection> {
  const raw = await runStudioCommand(pythonInterpreter(), ["-c", INSPECT, PRODUCER_SCRIPTS, dir]);
  const result = JSON.parse(raw) as StudioInspection;
  if (!result.viewCurrent && await hasImportedPlan(dir)) {
    result.viewCurrent = true;
    result.blockers = result.blockers.filter((message) => !message.startsWith("Studio edits belong to an older or unbound plan/base"));
  }
  return result;
}

const SERVE = `
import sys
sys.path.insert(0,sys.argv[1])
from studio.studio_review import ProducerPaths,_serve,cmd_open
paths=ProducerPaths.resolve(sys.argv[2])
sys.exit(_serve(paths) if sys.argv[3]=='reuse' else cmd_open(paths))
`;

/** Existing view: serve it unchanged. New/stale clean view: guarded generator. */
export async function startStudio(dir: string, reuseView: boolean): Promise<void> {
  await runStudioCommand(pythonInterpreter(), ["-c", SERVE, PRODUCER_SCRIPTS, dir,
    reuseView ? "reuse" : "generate"], 30_000, true);
}
