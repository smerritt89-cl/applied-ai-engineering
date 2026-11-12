#!/usr/bin/env node
/**
 * Verifies every <Video id="..."> in lessons and projects against YouTube's
 * oEmbed endpoint, and prints the real title and channel for each.
 * Fails (exit 1) if any id doesn't resolve, so a typo never ships.
 *
 *   npm run check:videos
 */
import { readFileSync } from 'node:fs';
import { globSync } from 'node:fs';

const files = globSync('src/content/**/*.mdx');
const found = new Map(); // id -> [files]
for (const f of files) {
  const src = readFileSync(f, 'utf8');
  for (const m of src.matchAll(/<Video[^>]*\bid="([A-Za-z0-9_-]{11})"/g)) {
    found.set(m[1], [...(found.get(m[1]) ?? []), f.replace('src/content/', '')]);
  }
}

let bad = 0;
for (const [id, where] of found) {
  const res = await fetch(`https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v=${id}&format=json`);
  if (res.ok) {
    const j = await res.json();
    console.log(`ok   ${id}  ${j.title}  (${j.author_name})`);
  } else {
    bad++;
    console.log(`FAIL ${id}  HTTP ${res.status}  used in ${where.join(', ')}`);
  }
}
console.log(`\n${found.size} videos checked, ${bad} failed.`);
process.exit(bad ? 1 : 0);
