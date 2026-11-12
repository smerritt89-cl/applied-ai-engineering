#!/usr/bin/env node
/**
 * Checks every source URL in src/content/sources/*.yaml.
 * Some sites refuse automated requests (403/429) even though the page exists;
 * those are reported as "blocked" for a manual check rather than failures.
 *
 *   npm run check:links
 */
import { readFileSync, readdirSync } from 'node:fs';
import { parse } from 'yaml';

const dir = 'src/content/sources';
const entries = readdirSync(dir)
  .filter((f) => f.endsWith('.yaml'))
  .flatMap((f) => (parse(readFileSync(`${dir}/${f}`, 'utf8')) ?? []).map((e) => ({ ...e, file: f })));

const UA = { 'user-agent': 'Mozilla/5.0 (link checker for a personal course site)' };
let failed = 0;
let blocked = 0;

async function check(url) {
  try {
    let res = await fetch(url, { method: 'HEAD', redirect: 'follow', headers: UA });
    if (res.status === 405 || res.status === 404 || res.status >= 500) res = await fetch(url, { redirect: 'follow', headers: UA });
    return res.status;
  } catch (e) {
    return `error: ${e.cause?.code ?? e.message}`;
  }
}

const results = await Promise.all(entries.map(async (e) => ({ e, status: await check(e.url) })));
for (const { e, status } of results) {
  if (status === 200) continue;
  if (status === 403 || status === 429 || status === 401) {
    blocked++;
    console.log(`blocked ${status}  ${e.id}  ${e.url}`);
  } else {
    failed++;
    console.log(`FAIL    ${status}  ${e.id}  ${e.url}  (${e.file})`);
  }
}
console.log(`\n${entries.length} sources checked: ${entries.length - failed - blocked} ok, ${blocked} blocked (verify by hand), ${failed} failed.`);
process.exit(failed ? 1 : 0);
