import { defineConfig } from 'vite';

// Locked (M21). Agent test builds (GAME_FACTORY_DEBUG_BUILD=1, set by the test runner) keep function
// names and source maps so browser errors point at real code; a normal `npm run build` stays minified.
const debug = process.env.GAME_FACTORY_DEBUG_BUILD === '1';

export default defineConfig({
  build: { sourcemap: debug, minify: !debug },
});
