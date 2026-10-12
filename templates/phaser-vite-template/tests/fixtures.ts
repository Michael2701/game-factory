import { test as base, expect } from '@playwright/test';

// Locked (M21): every spec imports { test, expect } from './fixtures'. Browser errors fail the test,
// so the fixer sees uncaught exceptions and console.error messages (with stacks) in the report.
export const test = base.extend({
  page: async ({ page }, use) => {
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(`pageerror: ${error.stack ?? error.message}`));
    page.on('console', (message) => {
      if (message.type() === 'error') {
        const where = message.location();
        errors.push(`console.error: ${message.text()} (${where.url}:${where.lineNumber}:${where.columnNumber})`);
      }
    });
    await use(page);
    if (errors.length) {
      throw new Error(`Browser errors:\n${[...new Set(errors)].slice(0, 5).join('\n')}`);
    }
  },
});

export { expect };
