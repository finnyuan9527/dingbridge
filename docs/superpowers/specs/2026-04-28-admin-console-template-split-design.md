# Admin Console Template Split Design

Date: 2026-04-28

## Context

The current OIDC Client admin console was added as the fastest possible MVP. It works, but the implementation keeps the HTML, CSS, and JavaScript inside `app/routers/admin.py`.

That structure is acceptable for proving the feature, but it is a poor long-term fit for this repository:

- the router file now mixes HTTP API logic and page assets
- small UI changes require Python edits
- adding more admin pages will make `admin.py` grow quickly
- frontend behavior is harder to reason about and reuse

## Goal

Refactor the OIDC Client admin console into a small server-rendered structure using Jinja2 templates plus static assets, while keeping the current feature scope and URL stable.

## Non-Goals

- no React, Vite, or separate frontend app
- no redesign of the admin interaction model
- no new admin authentication mechanism
- no DingTalk App management page in this step
- no API contract changes for existing admin endpoints

## Recommended Approach

Use a lightweight FastAPI server-rendered page:

- `app/routers/admin.py` keeps the route entrypoint and existing admin APIs
- `app/templates/admin/oidc_clients.html` contains the page markup
- `app/static/admin/oidc_clients.css` contains styling
- `app/static/admin/oidc_clients.js` contains browser-side behavior
- `app/main.py` mounts static files and configures Jinja2 templates

The page will continue to call the existing admin APIs from the browser with the user-provided `x-admin-key`.

## Why This Approach

Compared with the current inline HTML approach:

- it restores router-layer clarity
- it keeps the repo lightweight
- it avoids introducing a frontend build pipeline
- it gives us an easy path to add a DingTalk App page later

Compared with a full SPA:

- lower maintenance cost
- fewer dependencies
- better fit for the current project size and release model

## Functional Scope

The refactor must preserve the current user-visible behavior:

- `GET /admin/console/oidc-clients` remains the page URL
- page contains an `Admin API Key` input
- page loads `/admin/oidc-clients`
- page loads `/admin/dingtalk-apps`
- page supports listing existing OIDC clients
- page supports creating a client
- page supports editing `name`, `enabled`, `redirect_uris`, and `dingtalk_app_id`
- page supports optional `client_secret` update without exposing stored secrets

## Proposed File Layout

```text
app/
  main.py
  routers/
    admin.py
  templates/
    admin/
      oidc_clients.html
  static/
    admin/
      oidc_clients.css
      oidc_clients.js
```

## Rendering Plan

`admin.py` will render the template with a minimal context, likely limited to page title and endpoint URLs. The template should not embed large scripts or styles inline.

The JavaScript file will own:

- reading the Admin API key from the page
- loading DingTalk apps
- loading OIDC clients
- populating the form
- posting updates to `/admin/oidc-clients`
- status messaging

The CSS file will own the current visual presentation or a close equivalent.

## Dependency Plan

Add `jinja2` to `requirements.txt`.

No Node.js tooling or asset pipeline will be added.

## Testing Plan

Preserve and update the current console test coverage:

- `tests/test_admin_console.py` should still verify the page renders
- tests should continue checking for the key field names and endpoint references

Run the existing admin and OIDC regression coverage after the refactor:

- `tests/test_admin_auth.py`
- `tests/test_admin_console.py`
- `tests/test_config_surface.py`
- `tests/test_oidc_flow.py`
- `tests/test_oidc_refresh_token.py`
- `tests/test_saml_removed.py`

## Risks And Mitigations

Risk: static files are not mounted correctly.
Mitigation: add an integration-style render test and verify the page loads through FastAPI.

Risk: template references break after file moves.
Mitigation: keep endpoint names and DOM ids stable during the refactor.

Risk: scope creep into a broader admin frontend rewrite.
Mitigation: keep this change limited to structural cleanup of the existing OIDC Client page.

## Rollout Notes

This refactor should land before building additional admin pages. Otherwise, more UI code will accumulate inside `admin.py` and make the later extraction noisier.

## Acceptance Criteria

- `admin.py` no longer embeds the full HTML/CSS/JS document
- `/admin/console/oidc-clients` still works
- existing console behavior is preserved
- tests pass without introducing a frontend build step
