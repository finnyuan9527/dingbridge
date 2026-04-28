# Admin Console Layout Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the OIDC Client admin console into a professional, form-first admin layout with a top control bar, a dominant left editor, and a compact right browser table.

**Architecture:** Keep the current route, template, and script structure, but rearrange the HTML into a top-level control bar plus an asymmetric workspace. Update the CSS to shift the visual hierarchy from equal-weight cards to an operator-focused admin console while preserving existing JavaScript behavior and DOM ids.

**Tech Stack:** FastAPI templates, plain HTML, CSS, JavaScript, pytest

---

### Task 1: Lock the new layout structure with failing tests

**Files:**
- Modify: `tests/test_admin_console.py`
- Test: `tests/test_admin_console.py`

- [ ] **Step 1: Write the failing tests**

```python
    def test_oidc_client_console_page_uses_control_bar_layout(self):
        resp = self.client.get("/admin/console/oidc-clients")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIn("control-bar", resp.text)
        self.assertIn("workspace", resp.text)
        self.assertIn("editor-panel", resp.text)
        self.assertIn("browser-panel", resp.text)

    def test_oidc_client_console_page_groups_editor_sections(self):
        resp = self.client.get("/admin/console/oidc-clients")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIn("Identity", resp.text)
        self.assertIn("Security", resp.text)
        self.assertIn("Access", resp.text)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest -q tests/test_admin_console.py::AdminConsoleTests::test_oidc_client_console_page_uses_control_bar_layout tests/test_admin_console.py::AdminConsoleTests::test_oidc_client_console_page_groups_editor_sections`
Expected: FAIL because the current page still uses the older equal-weight card layout.

- [ ] **Step 3: Commit**

```bash
git add tests/test_admin_console.py
git commit -m "test: cover admin console layout redesign"
```

### Task 2: Restructure the template into a form-first admin console

**Files:**
- Modify: `app/templates/admin/oidc_clients.html`
- Test: `tests/test_admin_console.py`

- [ ] **Step 1: Move operator controls into a top control bar**

```html
<section class="control-bar">
  <div class="control-bar__intro">
    <p class="eyebrow">OIDC Administration</p>
    <h1>{{ page_title }}</h1>
    <p class="muted">Manage clients, rotate credentials, and keep DingTalk mappings organized.</p>
  </div>
  <div class="control-bar__tools">
    <label for="admin-key">...</label>
    <div class="control-actions">...</div>
    <div id="status" class="status" aria-live="polite"></div>
  </div>
</section>
```

- [ ] **Step 2: Build the two-column workspace**

```html
<section class="workspace">
  <form id="client-form" class="panel editor-panel stack">...</form>
  <aside class="panel browser-panel stack">...</aside>
</section>
```

- [ ] **Step 3: Group the form into `Identity`, `Security`, and `Access` sections**

```html
<section class="editor-section stack">
  <div class="section-heading">
    <p class="section-kicker">Identity</p>
    <h2>Client identity</h2>
  </div>
  ...
</section>
```

- [ ] **Step 4: Keep existing ids and JavaScript hooks stable**

```html
<input id="client_id" ... />
<input id="name" ... />
<input id="client_secret" ... />
<textarea id="redirect_uris" ...></textarea>
<select id="dingtalk_app_id" ...></select>
<input id="enabled" ... />
```

- [ ] **Step 5: Run focused layout tests**

Run: `python3 -m pytest -q tests/test_admin_console.py`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/templates/admin/oidc_clients.html tests/test_admin_console.py
git commit -m "refactor: restructure admin console layout"
```

### Task 3: Restyle the page to match the approved admin-console direction

**Files:**
- Modify: `app/static/admin/oidc_clients.css`
- Test: `tests/test_admin_console.py`

- [ ] **Step 1: Replace the current card-equality styling with operator-console styling**

```css
.control-bar { ... }
.workspace { ... }
.editor-panel { ... }
.browser-panel { ... }
```

- [ ] **Step 2: Make the left editor dominant and the right table compact**

```css
.workspace {
  display: grid;
  grid-template-columns: minmax(0, 1.65fr) minmax(320px, 0.95fr);
  gap: 20px;
}
```

- [ ] **Step 3: Tighten table presentation and reduce decorative emphasis**

```css
.browser-table td,
.browser-table th { ... }
.row-edit { ... }
.badge { ... }
```

- [ ] **Step 4: Preserve responsive stacking on narrow widths**

```css
@media (max-width: 960px) {
  .workspace {
    grid-template-columns: 1fr;
  }
}
```

- [ ] **Step 5: Run admin console tests again**

Run: `python3 -m pytest -q tests/test_admin_console.py`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/static/admin/oidc_clients.css
git commit -m "style: polish admin console layout"
```

### Task 4: Run regression verification

**Files:**
- Test: `tests/test_admin_auth.py`
- Test: `tests/test_admin_console.py`
- Test: `tests/test_config_surface.py`
- Test: `tests/test_oidc_flow.py`
- Test: `tests/test_oidc_refresh_token.py`
- Test: `tests/test_saml_removed.py`

- [ ] **Step 1: Run the regression suite**

Run: `python3 -m pytest -q tests/test_admin_auth.py tests/test_admin_console.py tests/test_config_surface.py tests/test_oidc_flow.py tests/test_oidc_refresh_token.py tests/test_saml_removed.py`
Expected: PASS

- [ ] **Step 2: Check the redesign against the accepted spec**

Checklist:

- top control bar is present
- left editor is the dominant workspace region
- right panel is a compact client browser
- editor sections are grouped into `Identity`, `Security`, and `Access`
- no API or route contract changed

- [ ] **Step 3: Commit**

```bash
git add app/templates/admin/oidc_clients.html app/static/admin/oidc_clients.css tests/test_admin_console.py docs/superpowers/plans/2026-04-28-admin-console-layout-redesign.md
git commit -m "feat: redesign admin console layout"
```
