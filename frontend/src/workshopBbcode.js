import { t } from './languages'

const TAG_ALIASES = {
  s: 'strike',
  ul: 'list',
  ol: 'olist',
}

const CONTAINER_TAGS = new Set([
  'b',
  'i',
  'u',
  'strike',
  'h1',
  'h2',
  'h3',
  'list',
  'olist',
  'quote',
  'code',
  'url',
  'img',
  'spoiler',
  'center',
  'table',
  'tr',
  'th',
  'td',
  'p',
  'color',
  'size',
])
const VOID_TAGS = new Set(['hr', 'br', 'previewyoutube'])
const SUPPORTED_TAGS = new Set([...CONTAINER_TAGS, ...VOID_TAGS, '*'])

const normalizeTag = name => TAG_ALIASES[name.toLocaleLowerCase()] || name.toLocaleLowerCase()

const parseTag = raw => {
  const value = raw.trim()
  const closing = value.startsWith('/')
  const body = closing ? value.slice(1).trim() : value
  const match = body.match(/^([a-z][a-z0-9]*|\*)(?:=(.*))?$/i)
  if (!match) return null
  const name = normalizeTag(match[1])
  if (!SUPPORTED_TAGS.has(name)) return null
  return {
    name,
    closing,
    option: (match[2] || '').trim().replace(/^(["'])(.*)\1$/, '$2'),
  }
}

const appendText = (stack, value) => {
  if (!value) return
  const children = stack[stack.length - 1].children
  const previous = children[children.length - 1]
  if (previous?.type === 'text') previous.value += value
  else children.push({ type: 'text', value })
}

export const parseWorkshopBbcode = source => {
  const root = { type: 'tag', name: 'root', option: '', children: [] }
  const stack = [root]
  const input = String(source || '')
  const tokenPattern = /\[([^\]\r\n]{1,300})\]/g
  let cursor = 0
  let match

  while ((match = tokenPattern.exec(input))) {
    appendText(stack, input.slice(cursor, match.index))
    const token = parseTag(match[1])
    if (!token) {
      appendText(stack, match[0])
      cursor = tokenPattern.lastIndex
      continue
    }

    if (token.closing) {
      const closingName = token.name === '*' ? 'li' : token.name
      let openIndex = -1
      for (let index = stack.length - 1; index > 0; index -= 1) {
        if (stack[index].name === closingName) {
          openIndex = index
          break
        }
      }
      if (openIndex < 0) appendText(stack, match[0])
      else stack.length = openIndex
      cursor = tokenPattern.lastIndex
      continue
    }

    if (token.name === '*') {
      let listIndex = -1
      for (let index = stack.length - 1; index > 0; index -= 1) {
        if (stack[index].name === 'list' || stack[index].name === 'olist') {
          listIndex = index
          break
        }
      }
      if (listIndex < 0) {
        appendText(stack, match[0])
      } else {
        stack.length = listIndex + 1
        const item = { type: 'tag', name: 'li', option: '', children: [] }
        stack[listIndex].children.push(item)
        stack.push(item)
      }
      cursor = tokenPattern.lastIndex
      continue
    }

    const node = { type: 'tag', name: token.name, option: token.option, children: [] }
    stack[stack.length - 1].children.push(node)
    if (!VOID_TAGS.has(node.name)) stack.push(node)
    cursor = tokenPattern.lastIndex
  }

  appendText(stack, input.slice(cursor))
  return root.children
}

const escapeHtml = value => String(value)
  .replaceAll('&', '&amp;')
  .replaceAll('<', '&lt;')
  .replaceAll('>', '&gt;')
  .replaceAll('"', '&quot;')
  .replaceAll("'", '&#39;')

const textContent = node => (node.children || [])
  .map(child => child.type === 'text' ? child.value : textContent(child))
  .join('')

const safeWebUrl = value => {
  try {
    const url = new URL(String(value || '').trim())
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : ''
  } catch {
    return ''
  }
}

const renderNodes = nodes => nodes.map(renderNode).join('')

const renderNode = node => {
  if (node.type === 'text') return escapeHtml(node.value)
  const children = () => renderNodes(node.children || [])

  switch (node.name) {
    case 'b': return `<strong>${children()}</strong>`
    case 'i': return `<em>${children()}</em>`
    case 'u': return `<u>${children()}</u>`
    case 'strike': return `<s>${children()}</s>`
    case 'h1': return `<h4 class="workshop-heading workshop-heading-1">${children()}</h4>`
    case 'h2': return `<h5 class="workshop-heading workshop-heading-2">${children()}</h5>`
    case 'h3': return `<h6 class="workshop-heading workshop-heading-3">${children()}</h6>`
    case 'list': return `<ul class="workshop-list">${children()}</ul>`
    case 'olist': return `<ol class="workshop-list workshop-list-ordered">${children()}</ol>`
    case 'li': return `<li>${children()}</li>`
    case 'quote': return `<blockquote class="workshop-quote">${children()}</blockquote>`
    case 'code':
      return `<pre class="workshop-code"><code>${escapeHtml(textContent(node))}</code></pre>`
    case 'url': {
      const target = safeWebUrl(node.option || textContent(node))
      if (!target) return children()
      return `<a href="${escapeHtml(target)}" target="_blank" rel="noopener noreferrer">${children()}</a>`
    }
    case 'img': {
      const target = safeWebUrl(textContent(node))
      if (!target) return escapeHtml(textContent(node))
      return `<img class="workshop-image" src="${escapeHtml(target)}" alt="" loading="lazy">`
    }
    case 'previewyoutube': {
      const videoId = node.option.split(';')[0].trim()
      if (!/^[a-z0-9_-]{6,20}$/i.test(videoId)) return ''
      const target = `https://www.youtube.com/watch?v=${encodeURIComponent(videoId)}`
      return `<a class="workshop-video" href="${target}" target="_blank" rel="noopener noreferrer">${t('details.youtubePreview')}</a>`
    }
    case 'spoiler':
      return `<details class="workshop-spoiler"><summary>${t('details.showSpoiler')}</summary>${children()}</details>`
    case 'center': return `<div class="workshop-center">${children()}</div>`
    case 'table': return `<table class="workshop-table"><tbody>${children()}</tbody></table>`
    case 'tr': return `<tr>${children()}</tr>`
    case 'th': return `<th>${children()}</th>`
    case 'td': return `<td>${children()}</td>`
    case 'p': return `<p>${children()}</p>`
    case 'color': {
      const color = node.option.trim()
      if (!/^(#[0-9a-f]{3,8}|[a-z]{3,20})$/i.test(color)) return children()
      return `<span style="color:${escapeHtml(color)}">${children()}</span>`
    }
    case 'size': {
      const size = /^(small|large|[1-7])$/i.test(node.option) ? node.option.toLocaleLowerCase() : ''
      return size ? `<span class="workshop-size-${escapeHtml(size)}">${children()}</span>` : children()
    }
    case 'hr': return '<hr class="workshop-rule">'
    case 'br': return '<br>'
    default: return children()
  }
}

export const renderWorkshopBbcode = source => renderNodes(parseWorkshopBbcode(source))
