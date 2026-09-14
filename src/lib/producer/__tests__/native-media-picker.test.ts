import assert from "node:assert/strict";
import {
  normalizePickedPath,
  pickerAppleScript,
  pickerOptions,
} from "../native-media-picker";

assert.deepEqual(pickerOptions({ kind: "folder" }), {
  kind: "folder",
  prompt: "Choose a project folder",
});
assert.deepEqual(pickerOptions({ kind: "file" }), {
  kind: "file",
  prompt: "Choose a media file",
});

// The legacy route contract stays available for references and editor music.
assert.equal(pickerOptions({ dir: true }).kind, "folder");
assert.equal(pickerOptions({ kind: "file", dir: true }).kind, "file");
assert.equal(pickerOptions({ prompt: " Pick a reference " }).prompt, "Pick a reference");
assert.throws(() => pickerOptions({ kind: "many" }), /file.*folder/);

const folderScript = pickerAppleScript({ kind: "folder", prompt: 'Choose "folder"' });
assert.match(folderScript, /choose folder/);
assert.match(folderScript, /Choose \\"folder\\"/);
assert.doesNotMatch(pickerAppleScript({ kind: "folder", prompt: "Choose\nfolder" }), /\nfolder/);

const fileScript = pickerAppleScript({ kind: "file", prompt: "Choose media" });
assert.match(fileScript, /choose file/);
assert.match(fileScript, /public\.movie/);
assert.match(fileScript, /public\.audio/);

const supporting = pickerOptions({ kind: "file", purpose: "supporting" });
assert.equal(supporting.purpose, "supporting");
const supportingScript = pickerAppleScript(supporting);
assert.match(supportingScript, /public\.png/); assert.match(supportingScript, /public\.jpeg/);
assert.match(supportingScript, /webp/); assert.match(supportingScript, /public\.mpeg-4/);
assert.doesNotMatch(supportingScript, /public\.audio|svg/);
assert.throws(() => pickerOptions({ kind: "folder", purpose: "supporting" }), /purpose/);
assert.throws(() => pickerOptions({ purpose: "anything" }), /purpose/);

assert.equal(normalizePickedPath("/Users/test/Media/\n"), "/Users/test/Media");
assert.equal(normalizePickedPath("/\n"), "/");
assert.equal(normalizePickedPath("  \n"), "");

console.log("native-media-picker.test.ts: all assertions passed");
