// Head fix-ups applied to every prerendered page (pure DOM functions, unit-tested).
export const SITE_URL = 'https://gst.doaide.com'

export function canonicalUrl(route) {
  const clean = route.replace(/\/+$/, '')
  return clean ? SITE_URL + clean : SITE_URL + '/'
}

function upsert(document, selector, create) {
  let el = document.head.querySelector(selector)
  if (!el) {
    el = create()
    document.head.appendChild(el)
  }
  return el
}

function hasSchemaType(document, type) {
  return [...document.head.querySelectorAll('script[type="application/ld+json"]')].some(el => {
    try {
      const data = JSON.parse(el.textContent)
      return (Array.isArray(data) ? data : [data]).some(d => d && d['@type'] === type)
    } catch {
      return false
    }
  })
}

export function pageName(title) {
  return (title || '').split(/ [—|] /)[0].trim()
}

// Canonical and og:url always point at the route itself, and every sub-page gets a
// BreadcrumbList if the page didn't provide one.
export function finalizeHead(document, route) {
  const url = canonicalUrl(route)
  const link = upsert(document, 'link[rel="canonical"]', () => {
    const el = document.createElement('link')
    el.setAttribute('rel', 'canonical')
    return el
  })
  link.setAttribute('href', url)
  const ogUrl = upsert(document, 'meta[property="og:url"]', () => {
    const el = document.createElement('meta')
    el.setAttribute('property', 'og:url')
    return el
  })
  ogUrl.setAttribute('content', url)

  if (route !== '/' && !hasSchemaType(document, 'BreadcrumbList')) {
    const segments = route.split('/').filter(Boolean)
    const items = [{ '@type': 'ListItem', position: 1, name: 'Home', item: SITE_URL + '/' }]
    if (segments.length > 1) {
      const section = '/' + segments[0]
      items.push({
        '@type': 'ListItem', position: 2,
        name: segments[0].charAt(0).toUpperCase() + segments[0].slice(1),
        item: SITE_URL + section,
      })
    }
    items.push({ '@type': 'ListItem', position: items.length + 1, name: pageName(document.title), item: url })
    const script = document.createElement('script')
    script.setAttribute('type', 'application/ld+json')
    script.textContent = JSON.stringify({ '@context': 'https://schema.org', '@type': 'BreadcrumbList', itemListElement: items })
    document.head.appendChild(script)
  }
}

// The shell served for non-prerendered URLs: no homepage canonical or homepage-only
// structured data, and noindex so stray URLs never compete with real pages.
export function appShellHead(document) {
  document.head.querySelectorAll('link[rel="canonical"], meta[property="og:url"], script[data-home-only]').forEach(el => el.remove())
  const robots = document.head.querySelector('meta[name="robots"]')
  if (robots) robots.setAttribute('content', 'noindex, follow')
}

