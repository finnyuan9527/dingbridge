# OIDC Compatibility Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand OIDC compatibility coverage for authorization, token, and logout flows so the repo locks down more interop-sensitive behaviors without changing the public protocol surface unintentionally.

**Architecture:** Extend the existing protocol-focused test suite in `tests/test_oidc_flow.py`, reusing the current fake Redis and patched client registry setup. Add failing tests first for `client_secret_post`, `response_mode` behavior, tighter `authorization_code` error branches, and logout interop paths, then implement only the minimal production changes required to make the intended behavior explicit and stable.

**Tech Stack:** FastAPI, pytest via unittest `TestClient`, fake Redis, OIDC protocol routes

---

### Task 1: Add failing authorization and token compatibility tests

**Files:**
- Modify: `tests/test_oidc_flow.py`
- Test: `tests/test_oidc_flow.py`

- [ ] **Step 1: Write the failing tests**

```python
    def test_token_supports_client_secret_post(self):
        verifier = "tok-verifier-post"
        code = self._issue_code(verifier)
        resp = self.client.post(
            "/oidc/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "https://client.example/callback",
                "code_verifier": verifier,
                "client_id": "test-client",
                "client_secret": "test-secret",
            },
        )
        self.assertEqual(resp.status_code, 200, resp.text)

    def test_token_rejects_missing_redirect_uri_for_authorization_code(self):
        verifier = "tok-verifier-no-redirect"
        code = self._issue_code(verifier)
        resp = self.client.post(
            "/oidc/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
            },
            headers=self._auth_header(),
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json().get("detail"), "invalid_request")

    def test_token_rejects_missing_code_verifier_when_pkce_was_used(self):
        verifier = "tok-verifier-missing-pkce"
        code = self._issue_code(verifier)
        resp = self.client.post(
            "/oidc/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "https://client.example/callback",
            },
            headers=self._auth_header(),
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json().get("detail"), "invalid_request")
```

- [ ] **Step 2: Run tests to verify red state**

Run: `python3 -m pytest -q tests/test_oidc_flow.py -k "client_secret_post or missing_redirect_uri or missing_code_verifier"`
Expected: PASS or FAIL depending on existing behavior, but at least one test must fail before any production change is made.

- [ ] **Step 3: Commit**

```bash
git add tests/test_oidc_flow.py
git commit -m "test: expand oidc token compatibility coverage"
```

### Task 2: Add failing response mode and logout interoperability tests

**Files:**
- Modify: `tests/test_oidc_flow.py`
- Test: `tests/test_oidc_flow.py`

- [ ] **Step 1: Write the failing tests**

```python
    def test_authorize_ignores_form_post_and_still_redirects_with_query_params(self):
        session_id = "sid-auth-form-post"
        asyncio.run(session_service.create_session(session_id, User(subject="u-form-post", name="Form Post User")))
        self.client.cookies.set("dingbridge_sso", session_id)
        verifier = "flow-verifier-form-post"
        params = self._authorize_params(
            code_challenge=_pkce_s256(verifier),
            state="st-form-post",
            response_mode="form_post",
        )
        resp = self.client.get("/oidc/authorize", params=params, follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("code=", resp.headers["location"])
        self.assertIn("state=st-form-post", resp.headers["location"])

    def test_logout_redirects_with_state_when_post_logout_redirect_uri_is_valid(self):
        resp = self.client.post(
            "/oidc/logout",
            data={
                "client_id": "test-client",
                "post_logout_redirect_uri": "https://client.example/callback",
                "state": "logout-state-1",
            },
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("state=logout-state-1", resp.headers["location"])

    def test_logout_rejects_invalid_post_logout_redirect_uri(self):
        resp = self.client.post(
            "/oidc/logout",
            data={
                "client_id": "test-client",
                "post_logout_redirect_uri": "https://evil.example/logout",
            },
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json().get("detail"), "invalid_post_logout_redirect_uri")

    def test_logout_resolves_client_from_id_token_hint(self):
        user = User(subject="u-logout-hint", name="Logout Hint User")
        id_token_hint = token_service.create_id_token(user, client_id="test-client", nonce="logout-nonce")
        resp = self.client.post(
            "/oidc/logout",
            data={
                "id_token_hint": id_token_hint,
                "post_logout_redirect_uri": "https://client.example/callback",
            },
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)

    def test_logout_rejects_invalid_id_token_hint(self):
        resp = self.client.post(
            "/oidc/logout",
            data={
                "id_token_hint": "not-a-jwt",
                "post_logout_redirect_uri": "https://client.example/callback",
            },
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json().get("detail"), "invalid_id_token_hint")
```

- [ ] **Step 2: Run tests to verify red state**

Run: `python3 -m pytest -q tests/test_oidc_flow.py -k "form_post or logout"`
Expected: At least one test fails before production changes, proving the new test is meaningful.

- [ ] **Step 3: Commit**

```bash
git add tests/test_oidc_flow.py
git commit -m "test: cover oidc logout and response mode interop"
```

### Task 3: Implement only the minimal production changes required

**Files:**
- Modify: `app/routers/oidc.py`
- Test: `tests/test_oidc_flow.py`

- [ ] **Step 1: Adjust production behavior only if failing tests require it**

```python
# Examples of allowed changes:
# - make response_mode behavior explicit without changing redirect semantics
# - tighten invalid_request vs invalid_grant branches if tests reveal ambiguity
# - preserve logout redirect/state behavior in a more explicit way
```

- [ ] **Step 2: Run focused compatibility tests**

Run: `python3 -m pytest -q tests/test_oidc_flow.py`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add app/routers/oidc.py tests/test_oidc_flow.py
git commit -m "test: lock oidc interoperability behaviors"
```

### Task 4: Run regression verification

**Files:**
- Test: `tests/test_admin_auth.py`
- Test: `tests/test_admin_console.py`
- Test: `tests/test_config_surface.py`
- Test: `tests/test_oidc_flow.py`
- Test: `tests/test_oidc_refresh_token.py`
- Test: `tests/test_saml_removed.py`

- [ ] **Step 1: Run regression suite**

Run: `python3 -m pytest -q tests/test_admin_auth.py tests/test_admin_console.py tests/test_config_surface.py tests/test_oidc_flow.py tests/test_oidc_refresh_token.py tests/test_saml_removed.py`
Expected: PASS

- [ ] **Step 2: Review against roadmap intent**

Checklist:

- `client_secret_post` token auth is covered
- PKCE-required authorization-code branches are covered
- current `response_mode=form_post` interoperability behavior is explicit in tests
- logout redirect validation and `id_token_hint` flows are covered
- no unrelated admin-console behavior changed

- [ ] **Step 3: Commit**

```bash
git add tests/test_oidc_flow.py app/routers/oidc.py docs/superpowers/plans/2026-04-28-oidc-compatibility-tests.md
git commit -m "test: extend oidc compatibility coverage"
```
