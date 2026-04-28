# Admin Console Template Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the OIDC Client admin console out of `app/routers/admin.py` into Jinja2 templates plus static assets without changing the current page URL or feature scope.

**Architecture:** Keep `admin.py` focused on routes and API logic, render the page through `Jinja2Templates`, and move markup, styles, and browser behavior into `app/templates` and `app/static`. Mount `/static` from `app/main.py` so the page can serve CSS and JavaScript without adding a frontend build step.

**Tech Stack:** FastAPI, Jinja2, StaticFiles, plain HTML/CSS/JavaScript, pytest

---

### Task 1: Add a failing test for static asset references

**Files:**
- Modify: `tests/test_admin_console.py`
- Test: `tests/test_admin_console.py`

- [ ] **Step 1: Write the failing test**

```python
    def test_oidc_client_console_page_references_static_assets(self):
        resp = self.client.get("/admin/console/oidc-clients")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIn("/static/admin/oidc_clients.css", resp.text)
        self.assertIn("/static/admin/oidc_clients.js", resp.text)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest -q tests/test_admin_console.py::AdminConsoleTests::test_oidc_client_console_page_references_static_assets`
Expected: FAIL because the current page embeds inline assets and does not reference the static files yet.

- [ ] **Step 3: Commit**

```bash
git add tests/test_admin_console.py
git commit -m "test: cover admin console static asset refs"
```

### Task 2: Move the admin console into template and static files

**Files:**
- Modify: `app/routers/admin.py`
- Modify: `app/main.py`
- Modify: `requirements.txt`
- Create: `app/templates/admin/oidc_clients.html`
- Create: `app/static/admin/oidc_clients.css`
- Create: `app/static/admin/oidc_clients.js`
- Test: `tests/test_admin_console.py`

- [ ] **Step 1: Write the minimal route-layer implementation**

```python
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.templating import Jinja2Templates
from starlette.responses import HTMLResponse

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@router.get("/console/oidc-clients", response_class=HTMLResponse)
async def oidc_client_console(request: Request):
    return templates.TemplateResponse(
        request,
        "admin/oidc_clients.html",
        {
            "page_title": "OIDC Client Console",
            "oidc_clients_endpoint": "/admin/oidc-clients",
            "dingtalk_apps_endpoint": "/admin/dingtalk-apps",
            "oidc_console_css": "/static/admin/oidc_clients.css",
            "oidc_console_js": "/static/admin/oidc_clients.js",
        },
    )
```

- [ ] **Step 2: Move the page markup into the template**

```html
<link rel="stylesheet" href="{{ oidc_console_css }}" />
...
<div class="endpoint">GET {{ oidc_clients_endpoint }}</div>
<div class="endpoint">GET {{ dingtalk_apps_endpoint }}</div>
...
<script
  src="{{ oidc_console_js }}"
  data-oidc-clients-endpoint="{{ oidc_clients_endpoint }}"
  data-dingtalk-apps-endpoint="{{ dingtalk_apps_endpoint }}"
></script>
```

- [ ] **Step 3: Move the styles into `app/static/admin/oidc_clients.css`**

```css
:root {
  color-scheme: light;
  --bg: #f3f6fb;
  --panel: #ffffff;
  --line: #d8e0ea;
  --text: #102033;
  --muted: #5a6b7d;
  --accent: #1565c0;
  --accent-soft: #e8f1fc;
  --danger: #c62828;
  --ok: #2e7d32;
}
```

- [ ] **Step 4: Move the browser behavior into `app/static/admin/oidc_clients.js`**

```javascript
const scriptEl = document.currentScript;
const OIDC_CLIENTS_ENDPOINT = scriptEl.dataset.oidcClientsEndpoint;
const DINGTALK_APPS_ENDPOINT = scriptEl.dataset.dingtalkAppsEndpoint;
```

- [ ] **Step 5: Mount static files and add Jinja2 dependency**

```python
from pathlib import Path

from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
```

```text
jinja2==3.1.4
```

- [ ] **Step 6: Run the focused console tests**

Run: `python3 -m pytest -q tests/test_admin_console.py`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add app/main.py app/routers/admin.py app/templates/admin/oidc_clients.html app/static/admin/oidc_clients.css app/static/admin/oidc_clients.js requirements.txt tests/test_admin_console.py
git commit -m "refactor: split admin console template assets"
```

### Task 3: Run regression verification for admin and OIDC flows

**Files:**
- Test: `tests/test_admin_auth.py`
- Test: `tests/test_admin_console.py`
- Test: `tests/test_config_surface.py`
- Test: `tests/test_oidc_flow.py`
- Test: `tests/test_oidc_refresh_token.py`
- Test: `tests/test_saml_removed.py`

- [ ] **Step 1: Run the regression suite**

Run: `python3 -m pytest -q tests/test_admin_auth.py tests/test_admin_console.py tests/test_config_surface.py tests/test_oidc_flow.py tests/test_oidc_refresh_token.py tests/test_saml_removed.py`
Expected: PASS with the same non-blocking warnings as before, if any.

- [ ] **Step 2: Review requirements against the spec**

Checklist:

- `/admin/console/oidc-clients` still renders
- the page still exposes the OIDC client editor fields
- the page now loads template and static resources instead of embedding the full document in Python
- existing admin APIs are unchanged
- no frontend build step was introduced

- [ ] **Step 3: Commit**

```bash
git add app/main.py app/routers/admin.py app/templates/admin/oidc_clients.html app/static/admin/oidc_clients.css app/static/admin/oidc_clients.js requirements.txt tests/test_admin_console.py docs/superpowers/plans/2026-04-28-admin-console-template-split.md
git commit -m "refactor: move admin console to templates"
```
