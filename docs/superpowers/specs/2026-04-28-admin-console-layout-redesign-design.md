# Admin Console Layout Redesign

Date: 2026-04-28

## Context

The current OIDC Client admin console is functionally usable, but its layout does not feel like a focused admin tool. The page visually gives similar weight to the form and the list, while the intended usage is primarily form-driven administration.

The user preference for this redesign is clear:

- professional admin-console style
- form-first layout
- compact table on the secondary side

## Goal

Redesign the OIDC Client admin console into a more professional, form-first admin layout without changing the current route, data model, or core workflow.

## Non-Goals

- no feature expansion in this step
- no route or API changes
- no frontend framework migration
- no DingTalk App management page yet
- no visual style that feels playful, marketing-like, or overly decorative

## Recommended Layout

Use a two-level structure:

1. A top control bar for operator context and global actions
2. A two-column workspace below it with a dominant left editor and a narrower right browser table

### Top Control Bar

The top bar should contain:

- page title and short helper text
- `Admin API Key`
- `Load Clients`
- `New Client`
- status feedback

This removes the current feeling that the API key is buried inside a side panel and makes the operator controls read as page-level actions.

### Main Workspace

The main workspace should use an asymmetrical split:

- left column: primary editor, around 60 to 65 percent width
- right column: compact client table, around 35 to 40 percent width

This keeps the form as the main focus while preserving quick browsing and switching on the right.

## Left Column: Editor Design

The left side should become a cleaner admin form panel:

- a strong section header such as `Client Editor`
- a small mode indicator such as `New Client` or `Editing <client_id>`
- grouped fields with more consistent spacing
- a dedicated action area at the bottom for save and reset

Suggested grouping:

1. Identity
   - `client_id`
   - `name`

2. Security
   - `client_secret`
   - note explaining that the current secret is never shown

3. Access
   - `redirect_uris`
   - `dingtalk_app_id`
   - `enabled`

The form should read top-to-bottom as a standard admin editing flow, not as a mixed card of unrelated fields.

## Right Column: Compact Table Design

The right side should become a secondary browsing surface:

- compact header with item count
- tighter rows
- client selection by row button or row click
- truncated or summarized `redirect_uris`

The table should prioritize scanability:

- first line: `client_id`
- secondary line or smaller text: `name`
- small metadata columns for `enabled` and `dingtalk_app_id`
- `redirect_uris` shown as short summary instead of large multi-line blocks

The right panel should help the operator pick what to edit, not compete with the form for attention.

## Visual Direction

The page should look like a professional internal admin tool:

- lighter background, flatter surfaces
- less rounded card treatment than the current MVP
- tighter spacing and cleaner visual rhythm
- more restrained color use
- stronger typography hierarchy
- less decorative emphasis on buttons and badges

The target feeling is operational clarity, not dashboard gloss.

## Responsive Behavior

Desktop:

- top control bar spans full width
- left editor remains dominant
- right table remains secondary

Mobile or narrow width:

- top control bar stacks cleanly
- left editor appears first
- right table moves below the editor

The redesign should preserve usability without inventing a separate mobile workflow.

## Implementation Notes

The redesign should be implemented entirely inside the existing template and static assets:

- `app/templates/admin/oidc_clients.html`
- `app/static/admin/oidc_clients.css`
- `app/static/admin/oidc_clients.js`

No backend behavior changes should be required beyond minimal markup adjustments.

## Acceptance Criteria

- the page clearly reads as a form-first admin console
- the API key and global actions are promoted to a top control bar
- the editor becomes the dominant visual region
- the client table becomes a compact secondary panel
- the page remains functionally equivalent to the current implementation
