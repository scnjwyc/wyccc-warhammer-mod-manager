import { describe, expect, it } from 'vitest'

import { renderWorkshopBbcode } from '../workshopBbcode'

describe('Steam Workshop BBCode renderer', () => {
  it('supports common Workshop formatting tags', () => {
    const html = renderWorkshopBbcode(
      '[h1]标题[/h1][quote]引用[/quote][olist][*]一[/*][*][i]二[/i][/*][/olist][hr]',
    )

    expect(html).toContain('class="workshop-heading workshop-heading-1">标题</h4>')
    expect(html).toContain('<blockquote class="workshop-quote">引用</blockquote>')
    expect(html).toContain('<ol class="workshop-list workshop-list-ordered">')
    expect(html).toContain('<li>一</li>')
    expect(html).toContain('<li><em>二</em></li>')
    expect(html).toContain('<hr class="workshop-rule">')
  })

  it('escapes raw HTML and refuses executable link or image protocols', () => {
    const html = renderWorkshopBbcode(
      '<script>alert(1)</script>[url=javascript:alert(2)]危险链接[/url]'
      + '[img]javascript:alert(3)[/img]',
    )

    expect(html).toContain('&lt;script&gt;alert(1)&lt;/script&gt;')
    expect(html).not.toContain('<script>')
    expect(html).not.toContain('href="javascript:')
    expect(html).not.toContain('src="javascript:')
    expect(html).toContain('危险链接')
  })

  it('keeps unknown tags visible instead of silently deleting description text', () => {
    const html = renderWorkshopBbcode('[unknown]保留内容[/unknown]')

    expect(html).toBe('[unknown]保留内容[/unknown]')
  })
})
