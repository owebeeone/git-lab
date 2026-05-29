import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { globalIgnores } from 'eslint/config'

export default tseslint.config([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs['recommended-latest'],
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    rules: {
      // grip-lab: no React local state — use grips/taps instead (see GLCodingRules.md).
      'no-restricted-syntax': [
        'error',
        { selector: "CallExpression[callee.name='useState']", message: 'Use a grip + atom tap instead of useState (see dev-docs/GLCodingRules.md).' },
        { selector: "CallExpression[callee.name='useEffect']", message: 'Use grips/taps, ref callbacks, or overlays instead of useEffect (see dev-docs/GLCodingRules.md).' },
        { selector: "ImportSpecifier[imported.name='useState']", message: 'Do not import useState — use grips (see dev-docs/GLCodingRules.md).' },
        { selector: "ImportSpecifier[imported.name='useEffect']", message: 'Do not import useEffect — use grips/taps (see dev-docs/GLCodingRules.md).' },
      ],
    },
  },
])
