# thinfilmengineer.com

Landing page for **Thin Film Engineer** — thin film deposition, plasma etch, metrology,
process statistics and fab careers, for semiconductor professionals.

## Layout

```
index.html            THE SITE — image-based scroll experience (self-contained single file)
interview-pack.pdf    lead magnet: 50 interview Q&A + PVD/ALD/CVD/ETCH/SPC reference sheets (22 pages)
deploy/               exactly the two files above — drag this folder into Cloudflare Pages
legacy-3d/            earlier real-time WebGL (Three.js) version, kept for reference
CNAME                 custom domain for GitHub Pages (thinfilmengineer.com)
```

## Deploy to Cloudflare Pages (drag & drop)

1. dash.cloudflare.com → Workers & Pages → Create → Pages → **Upload assets**
2. Drag the `deploy/` folder in (index.html + interview-pack.pdf)
3. Deploy → you get a `*.pages.dev` URL; add `thinfilmengineer.com` under Custom domains

## Email capture

The signup form posts to Web3Forms (access key embedded in `index.html`). On success —
or on the mailto fallback — the page reveals a **Download the Interview Pack (PDF)** button
pointing at `interview-pack.pdf`, so subscribers get the pack instantly.

## Regenerating the PDF

The pack is generated with ReportLab; the generator script lives with the session that
produced it. To change content, edit the QA/SHEETS data and rerun — output is
`interview-pack.pdf` at repo root (copy it into `deploy/` too).
