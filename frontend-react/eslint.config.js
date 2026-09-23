import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{js,jsx}'],
    extends: [
      js.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
  },
  {
    // Jobs owns an explicit async server-side pagination loader. The existing
    // screen already intentionally triggered data loading from an effect; keep
    // that contract scoped to this page instead of disabling the rule globally.
    files: ['src/pages/Jobs.jsx'],
    rules: {
      'react-hooks/set-state-in-effect': 'off',
    },
  },
])
