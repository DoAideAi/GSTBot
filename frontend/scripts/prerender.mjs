// Post-build prerender (adapted from DoAide-TaxFile): writes dist/<route>/index.html
// for every URL in public/sitemap.xml, with that page's own <title>, meta description, canonical,
// Open Graph tags, JSON-LD and rendered content. Without this every URL serves the
// homepage's head, so search engines treat sub-pages as duplicates of "/".
//
// Usage: node scripts/prerender.mjs   (run after `vite build`)
//
// deploy/static-server.mjs serves dist/<route>/index.html for /<route> and falls
// back to dist/app-shell.html for anything else.
import { mkdir, readFile, rm, writeFile } from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { JSDOM } from 'jsdom'
import { build } from 'vite'
import { appShellHead, finalizeHead, SITE_URL } from './seoHead.mjs'

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const DIST = join(ROOT, 'dist')
const SSR_OUT = join(ROOT, 'node_modules', '.prerender')

// The sitemap is the list of indexable pages, so it is also the list to prerender.
const sitemap = await readFile(join(ROOT, 'public/sitemap.xml'), 'utf8')
const routes = [...sitemap.matchAll(/<loc>([^<]+)<\/loc>/g)].map(m => new URL(m[1]).pathname.replace(/(.)\/$/, '$1'))
const template = await readFile(join(DIST, 'index.html'), 'utf8')

await build({
  root: ROOT,
  logLevel: 'warn',
  build: { ssr: 'src/seo/prerenderEntry.jsx', outDir: SSR_OUT, emptyOutDir: true },
})

const dom = new JSDOM(template, { url: SITE_URL + '/', pretendToBeVisual: true })
const { window } = dom
const noop = () => {}
const stubFetch = async () => ({ ok: false, status: 503, json: async () => ({}), text: async () => '' })
Object.assign(window, {
  matchMedia: () => ({ matches: false, addListener: noop, removeListener: noop, addEventListener: noop, removeEventListener: noop }),
  scrollTo: noop,
  fetch: stubFetch,
  IntersectionObserver: class { observe() {} unobserve() {} disconnect() {} },
  ResizeObserver: class { observe() {} unobserve() {} disconnect() {} },
})
for (const key of ['window', 'document', 'navigator', 'localStorage', 'sessionStorage', 'location', 'history',
  'HTMLElement', 'Element', 'Node', 'Event', 'CustomEvent', 'KeyboardEvent', 'MouseEvent', 'getComputedStyle',
  'matchMedia', 'IntersectionObserver', 'ResizeObserver', 'requestAnimationFrame', 'cancelAnimationFrame', 'scrollTo']) {
  Object.defineProperty(globalThis, key, { value: window[key], configurable: true, writable: true })
}
globalThis.fetch = stubFetch

// Fallback for URLs that aren't prerendered: the plain SPA shell, kept out of the index.
const shell = new JSDOM(template)
appShellHead(shell.window.document)
await writeFile(join(DIST, 'app-shell.html'), shell.serialize())

const { renderRoute } = await import(pathToFileURL(join(SSR_OUT, 'prerenderEntry.js')).href)
const { document } = window
const templateHead = document.head.innerHTML

const rendered = []
const failed = []
for (const route of routes) {
  try {
    document.head.innerHTML = templateHead
    if (route !== '/') document.head.querySelectorAll('script[data-home-only]').forEach(el => el.remove())
    const container = document.getElementById('root')
    container.innerHTML = ''
    window.history.replaceState(null, '', route)
    window.localStorage.clear()
    const root = await renderRoute(route, container)
    finalizeHead(document, route)
    const html = '<!DOCTYPE html>\n' + document.documentElement.outerHTML
    root.unmount()
    const outFile = route === '/' ? join(DIST, 'index.html') : join(DIST, route.slice(1), 'index.html')
    await mkdir(dirname(outFile), { recursive: true })
    await writeFile(outFile, html)
    rendered.push(route)
  } catch (err) {
    failed.push(route)
    console.error(`prerender failed for ${route}: ${err.message}`)
    if (route === '/') continue
    // Still give the route its own indexable, self-canonical shell rather than the
    // noindex fallback, so a render bug can't de-index a real page.
    const page = new JSDOM(template)
    page.window.document.head.querySelectorAll('script[data-home-only]').forEach(el => el.remove())
    finalizeHead(page.window.document, route)
    const outFile = join(DIST, route.slice(1), 'index.html')
    await mkdir(dirname(outFile), { recursive: true })
    await writeFile(outFile, page.serialize())
  }
}

await rm(SSR_OUT, { recursive: true, force: true })
console.log(`prerendered ${rendered.length}/${routes.length} routes`)
// A broken route still gets a self-canonical shell, so only fail the build if prerendering is broadly broken.
process.exit(failed.length > routes.length * 0.2 ? 1 : 0)
