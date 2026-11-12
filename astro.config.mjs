// @ts-check
/**
 * Astro configuration for the Applied AI Engineering platform.
 *
 * GitHub Pages serves a project site from /<repo-name>/, so every internal
 * URL must be prefixed with `base`. Use the `url()` helper in src/lib/paths.ts
 * rather than hard-coding "/..." links anywhere.
 *
 * Override at build time if you rename the repo or use a custom domain:
 *   SITE_URL=https://you.github.io BASE_PATH=/my-repo npm run build
 */
import { defineConfig } from 'astro/config';
import mdx from '@astrojs/mdx';
import preact from '@astrojs/preact';

const site = process.env.SITE_URL ?? 'https://example.github.io';
const base = process.env.BASE_PATH ?? '/applied-ai-engineering'; // '' means site root

export default defineConfig({
  site,
  base: base || '/',
  trailingSlash: 'ignore',
  integrations: [mdx(), preact()],
  markdown: {
    shikiConfig: {
      // Dual themes: CSS in global.css switches between them with the site theme.
      themes: { light: 'github-light', dark: 'github-dark' },
      wrap: true,
    },
  },
  vite: {
    // Mermaid is large; keep it out of the main bundle (it is imported lazily).
    build: { chunkSizeWarningLimit: 2500 },
  },
});
