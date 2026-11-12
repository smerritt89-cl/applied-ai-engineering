/**
 * URL helper that respects Astro's `base` (needed for GitHub Pages project sites).
 * Always build internal links with url('/lessons/x/') instead of '/lessons/x/'.
 */
const BASE = import.meta.env.BASE_URL.replace(/\/$/, '');

export function url(path = '/'): string {
  if (/^https?:\/\//.test(path)) return path;
  const clean = path.startsWith('/') ? path : `/${path}`;
  return `${BASE}${clean}`;
}
