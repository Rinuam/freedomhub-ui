# thinfilmengineer.com

A cinematic, scroll-driven landing page for **Thin Film Engineer** — teaching semiconductor
professionals thin film deposition, plasma etch, metrology, process statistics, and fab careers.

## The scroll experience

The hero is a real-time WebGL "wafer journey" (Three.js, vendored locally — no CDN):
scrolling scrubs through the process like a film.

| Stage | What happens in 3D |
|---|---|
| Intro | Silicon wafer floating in a dark chamber, slow orbit |
| 01 · Substrate | Camera drops to a grazing close-up of the polished wafer |
| 02 · Deposition | Sputter target descends, atoms rain down, a copper film grows |
| 03 · Plasma etch | Coil ignites, violet plasma + ion streaks, trenches open in a cross-section stack |
| 04 · Metrology | A laser sweeps the wafer; the HUD readout settles on 42.3 nm |
| Finale | The film pattern resolves into a glowing grid of dies |

Below it: animated stat counters, a revenue trend chart, a log-scale "how thin is thin" chart,
skills/career infographics, the troubleshooting loop, and an email-capture card — all
hand-rolled canvas/CSS, no chart library.

## Structure

```
index.html            single page, all content
css/style.css         design system (dark cinematic, plasma accents)
js/scene.js           Three.js scroll-driven hero (ES module)
js/main.js            scroll orchestration, reveals, charts, form
vendor/               three.module.min.js (r160) + license
assets/favicon.svg
```

## Run locally

Any static server works:

```bash
python3 -m http.server 8000
# open http://localhost:8000
```

(A server is required — `js/scene.js` is an ES module, which `file://` blocks.)

## Deploy

Static hosting: GitHub Pages, Netlify, Vercel, Cloudflare Pages. `CNAME` is included for
GitHub Pages with the custom domain `thinfilmengineer.com` (point the domain's DNS at
GitHub Pages and enable Pages on this branch/root).

## Notes

- **Fallbacks**: `prefers-reduced-motion` gets a static composition with all copy readable;
  no-WebGL browsers keep the gradient backdrop and full content.
- **Email form** is front-end only — wire the submit handler in `js/main.js`
  (`#packForm`) to your email service (Buttondown, ConvertKit, Mailchimp…).
- Chart palette (`#2B9DB6 / #8A7BE8 / #BB853B`) is validated for contrast and
  colorblind separation on the dark surface.
- Figures cited on the page come from published industry reporting (SIA, WSTS, IDC,
  Gartner, SEMI, Deloitte); forward numbers are forecasts and labeled as such.
