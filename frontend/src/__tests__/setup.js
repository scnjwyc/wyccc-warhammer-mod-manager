import { beforeEach } from 'vitest'

import { applyInterfaceLanguage } from '../languages'

// Component assertions intentionally run in one explicit language. Tests that
// cover language selection switch away from Chinese themselves.
beforeEach(() => applyInterfaceLanguage('zh-CN'))
