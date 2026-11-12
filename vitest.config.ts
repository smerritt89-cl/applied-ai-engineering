import { defineConfig } from 'vitest/config';

// Unit tests cover the pure logic in src/lib (grading, progress).
export default defineConfig({
  test: { include: ['tests/**/*.test.ts'], environment: 'node' },
});
