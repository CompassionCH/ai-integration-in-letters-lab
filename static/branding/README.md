# Branding assets

Drop the Compassion brand image assets in this directory. They are served at
`/static/branding/<file>` and referenced from the templates.

Expected files:

| File              | Use                                                          |
|-------------------|--------------------------------------------------------------|
| `logo.png`        | Primary horizontal full-color logo (header).                 |
| `logo_white.png`  | White logo for use on the brand-blue (`#005eb8`) surfaces.   |
| `logo_simple.png` | Square mark — app icon / compact contexts.                   |
| `favicon.png`     | Browser-tab icon (`<link rel="icon" type="image/png">`).     |

The templates fall back to plain text when an asset is absent, so the app runs
without these files present. None of these files are committed.
