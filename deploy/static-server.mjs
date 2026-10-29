// Serves the built Vite SPA (frontend/dist) over HTTP with history-API
// fallback. Zero dependencies on purpose: the production box should not need
// an npm install to serve static files, and `vite preview` is a dev tool that
// binds loosely and prints a banner nobody reads in a journal.
//
//   node deploy/static-server.mjs --root /opt/GSTBot/frontend/dist \
//                                 --host 172.18.0.1 --port 3009
//
// This exists because Caddy runs in a container on this host and cannot read
// the filesystem the build writes to. On a box where Caddy is a host service,
// `root * <dist>` + `file_server` does the same job with one less process —
// see deploy/README.md for why that is not the arrangement here.
//
// Public pages are prerendered to dist/<route>/index.html (scripts/prerender.mjs
// in frontend/) and served as directory indexes. Anything else that isn't an
// existing file resolves to app-shell.html — the SPA with no canonical and
// noindex — because the router is client-side: /invoices/42 is a real route to
// React and a 404 to the filesystem. index.html is now the prerendered
// homepage, so serving it there would hand every app URL the homepage canonical.
import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { createServer } from "node:http";
import { extname, join, normalize, resolve, sep } from "node:path";

function arg(name, fallback) {
  const i = process.argv.indexOf(`--${name}`);
  return i !== -1 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}

const ROOT = resolve(arg("root", "frontend/dist"));
const HOST = arg("host", "127.0.0.1");
const PORT = Number(arg("port", "3009"));

const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".ico": "image/x-icon",
  ".webp": "image/webp",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".ttf": "font/ttf",
  ".map": "application/json; charset=utf-8",
  ".txt": "text/plain; charset=utf-8",
  ".xml": "application/xml; charset=utf-8",
  ".webmanifest": "application/manifest+json",
};

const ASSETS = join(ROOT, "assets");

// Vite fingerprints everything under /assets, so those are immutable. The
// entry HTML is the one name that does not change between releases: a cached
// copy pins the user to a bundle that is no longer on disk, which reads as a
// blank page.
//
// Decided by the file served, not the URL asked for. Going by the URL,
// /assets/, /assets/foo or a chunk name missing its extension got the SPA shell
// with a year's immutability, so the one page that must never be kept was
// kept until next year at that address.
function cacheControl(file) {
  return file.startsWith(ASSETS + sep)
    ? "public, max-age=31536000, immutable"
    : "no-store";
}

async function resolveFile(pathname) {
  // normalize() collapses `..` before the prefix check, so a crafted
  // /../../etc/passwd cannot escape ROOT.
  const candidate = join(ROOT, normalize(decodeURIComponent(pathname)));
  if (candidate !== ROOT && !candidate.startsWith(ROOT + sep)) return null;
  try {
    const s = await stat(candidate);
    if (s.isFile()) return candidate;
    if (s.isDirectory()) {
      const index = join(candidate, "index.html");
      if ((await stat(index)).isFile()) return index;
    }
  } catch {
    /* fall through to the SPA fallback */
  }
  return null;
}

const server = createServer(async (req, res) => {
  if (req.method !== "GET" && req.method !== "HEAD") {
    res.writeHead(405, { Allow: "GET, HEAD" }).end("Method Not Allowed");
    return;
  }

  let pathname;
  try {
    pathname = new URL(req.url, "http://localhost").pathname;
  } catch {
    res.writeHead(400, { "Content-Type": "text/plain; charset=utf-8" }).end("Bad Request");
    return;
  }

  let file;
  try {
    file = await resolveFile(pathname);
  } catch {
    // A malformed percent-encoding makes decodeURIComponent throw. That is a
    // bad request, not a reason to drop the connection with no status.
    res.writeHead(400, { "Content-Type": "text/plain; charset=utf-8" }).end("Bad Request");
    return;
  }

  if (!file) {
    // A missing asset is a genuine 404 — only unknown *routes* get the shell,
    // otherwise a typo'd script src silently returns HTML and the console
    // fills with "Unexpected token '<'".
    if (extname(pathname)) {
      // Not stored: a chunk is missing for a moment during a deploy, and a
      // 404 anything kept would outlive the release that restores it.
      res
        .writeHead(404, { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" })
        .end("Not Found");
      return;
    }
    const shell = join(ROOT, "app-shell.html");
    file = (await stat(shell).then((s) => s.isFile(), () => false)) ? shell : join(ROOT, "index.html");
  }

  res.writeHead(200, {
    "Content-Type": TYPES[extname(file).toLowerCase()] ?? "application/octet-stream",
    "Cache-Control": cacheControl(file),
    // Defence in depth: Caddy sets this too, but this process is reachable
    // from anything on the Docker bridge, not only from the edge.
    "X-Content-Type-Options": "nosniff",
  });
  if (req.method === "HEAD") {
    res.end();
    return;
  }
  createReadStream(file)
    .on("error", () => res.destroy())
    .pipe(res);
});

server.listen(PORT, HOST, () => {
  console.log(`gstbot-web: serving ${ROOT} on http://${HOST}:${PORT}`);
});
