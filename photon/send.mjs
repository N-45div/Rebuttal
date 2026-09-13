// Photon (iMessage/RCS) sidecar: send one text into an EXISTING thread with a phone number.
//   node send.mjs "+15551234567" "message text"
// A shared Photon line will not open a cold thread, so the number must have texted the line before.
// Reuses the spectrum-ts SDK and credentials from a sibling project (see PHOTON_SDK_DIR / PHOTON_ENV_FILE).
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const sdkDir = process.env.PHOTON_SDK_DIR ?? "C:/Users/DivijN/powlo/node_modules/spectrum-ts/dist";
const envFile = process.env.PHOTON_ENV_FILE ?? "C:/Users/DivijN/powlo/.env";
for (const line of readFileSync(envFile, "utf8").split(/\r?\n/)) {
  const m = line.match(/^([A-Z_]+)=(.*)$/);
  if (m && !process.env[m[1]]) process.env[m[1]] = m[2].replace(/^"|"$/g, "");
}
const [handle, ...rest] = process.argv.slice(2);
const text = rest.join(" ");
if (!handle || !text) { console.error("usage: node send.mjs <phone> <text>"); process.exit(2); }

const { Spectrum } = await import(pathToFileURL(`${sdkDir}/index.js`).href);
const { imessage } = await import(pathToFileURL(`${sdkDir}/providers/imessage/index.js`).href);
const app = await Spectrum({ projectId: process.env.SPECTRUM_PROJECT_ID, projectSecret: process.env.SPECTRUM_PROJECT_SECRET, providers: [imessage.config()] });
const im = imessage(app);
let space;
try { space = await im.space.get(`any;-;${handle}`); } catch { space = null; }
if (!space) { console.log(JSON.stringify({ ok: false, error: "no_existing_thread" })); process.exit(3); }
await space.send(text);
console.log(JSON.stringify({ ok: true, to: handle, chars: text.length }));
process.exit(0);
