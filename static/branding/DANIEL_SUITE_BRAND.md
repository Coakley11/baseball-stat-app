# Official Daniel AI Suite parent branding

The PNG is an exact copy of the approved `Daniel_AI_Suite_Logo.png` (SHA256
`b4761538cca65b91dbd6bccccc48b710f7e99d318c91e09a073030cc84a3807f`).
Keep the white surface and original proportions. Individual application logos
are separate and must remain intact.

`daniel_ai_suite_icon.svg` is a small viewport derivative referencing the same
PNG: it crops the wordmark below the D, tiles, AI badge and star. It does not
redraw or recompress the approved artwork and avoids a second large bitmap.
The rendering helper embeds the local PNG for Streamlit; it makes no requests
to external image hosts. Main login/hub locations use the full wordmark;
sidebars use the compact icon with an accessible suite label.

Changes are presentation only. Authentication, database configuration, workspace
state, navigation callbacks and individual app artwork are unchanged.
Rendered desktop/mobile and authenticated acceptance remain required before
integration. No push, merge or deployment is authorized.
