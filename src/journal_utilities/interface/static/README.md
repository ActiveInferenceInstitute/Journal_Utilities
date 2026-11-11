# static/ — web-interface front-end

Static assets served by the FastAPI SPA in [`../app.py`](../app.py).

| File | Purpose |
| --- | --- |
| `index.html` | Single-page app shell. |
| `app.js` | Search, video library, transcript viewer, chat client. |
| `styles.css` | Design tokens and theme (monochrome + red accents). |
| `ActInferServe.png` | Active Inference Institute mark. |

These are hand-written sources (never generated). Edit them here; the interface
serves this directory at runtime. See the parent package [`README.md`](../README.md)
and [`../../../../docs/web_interface.md`](../../../../docs/web_interface.md).
