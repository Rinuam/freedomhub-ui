# Thin Film Engineer — thinfilmengineer.com

A single-page marketing/education site for the Thin Film Engineer brand.
Design direction **"Interference"**: cleanroom-light editorial layout, serif
display type, iridescent thin-film accents, and a real-time WebGL centrepiece
(wafer, deposition, etch, metrology, multilayer stack) driven by scroll.

The deployable site is the **`site/`** folder — plain static HTML/CSS/JS, no
server code, no trackers, no cookies.

```
site/
├── index.html            ← the whole page (copy, charts, form)
└── assets/
    ├── css/main.css      ← design system + all styling
    ├── js/main.js        ← bundled app (GSAP, ScrollTrigger, Lenis)
    ├── js/chunks/…       ← lazy-loaded Three.js WebGL chunk
    ├── fonts/…           ← self-hosted Fraunces, Inter, IBM Plex Mono
    └── img/…             ← favicon, OG image, poster fallbacks (WebP)
```

## Deploy to Cloudflare Workers (static assets)

**Drag-folder method (no CLI):**

1. Cloudflare dashboard → **Workers & Pages** → **Create** → **Pages** →
   **Upload assets** (direct upload).
2. Drag the **contents of the `site/` folder** (or the folder itself) into the
   upload area. `index.html` must end up at the root of the upload.
3. Deploy, then add the custom domain `thinfilmengineer.com` under
   **Custom domains**.

**Wrangler method:** from the repo root:

```bash
npx wrangler pages deploy site --project-name thinfilmengineer
```

All asset paths are relative, so the site also works from any static host or
subpath.

## Web3Forms key (the signup form)

The form POSTs JSON to `https://api.web3forms.com/submit`. The access key is a
clearly-marked constant at the **top of `site/index.html`** (inside the first
`<script>` tag in `<head>`):

```js
window.W3F_KEY = 'PASTE-YOUR-ACCESS-KEY-HERE';
```

1. Get a free access key at <https://web3forms.com> (it is emailed to you —
   use info@thinfilmengineer.com so submissions arrive there).
2. Replace `PASTE-YOUR-ACCESS-KEY-HERE` with the key and redeploy.

While the placeholder is unchanged the form runs in **demo mode**: it
validates and shows the success state without sending anything, so the page
can be previewed safely.

## Regenerating / swapping the 3D media

The 3D is real-time WebGL (Three.js) rendered from `src/webgl.js`, bundled
into `site/assets/js/chunks/`. The WebP images in `site/assets/img/poster-*`
are **fallback posters** shown when WebGL is unavailable, on reduced-motion,
or with JavaScript disabled — they are screenshots of the same scenes.

After changing `src/webgl.js` (or `src/main.js`):

```bash
npm install                       # once
npm run build                     # rebuilds site/assets/js
npm run posters                   # re-captures the poster WebPs + needs a local server
```

`npm run posters` expects the site served at `http://localhost:8080`
(`npm run serve` in a second terminal) and headless Chromium available to
Playwright. To swap in different artwork entirely, just replace the
`poster-*.webp` files (keep the filenames and 4:3 aspect) and the `og.jpg`.

## Editing content

Everything the visitor reads lives in `site/index.html` — copy, chart values
and their `--w`/`--h` custom properties, salary-band positions, and the
"How thin is thin?" scale SVG. `site/assets/css/main.css` holds the design
tokens (colours, type, spacing) at the top under `:root`.

## Performance / accessibility budget

- Initial JS ≈ 51 KB gzipped; the Three.js chunk (~126 KB gz) loads lazily
  and only when motion is allowed, WebGL exists, and Save-Data is off.
- Fonts are self-hosted WOFF2 (~250 KB total, `font-display: swap`).
- `prefers-reduced-motion`: no pinning, no scrub, no WebGL — full content
  with static posters.
- The page is fully readable and the form fully usable with JavaScript
  disabled.
