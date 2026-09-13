# Publication boundary

`public-files.txt` lists every file intended for publication. It excludes raw
research records, copied provider content in audits/views, and editorial history.
`result-columns.json` lists the reviewed columns in the released CSVs.

Run `python3 scripts/check_public_release.py` before preparing a release. Export
only these files with `python3 scripts/export_public_release.py /path/to/new-directory`.
The destination must not exist. The exporter does not copy `.git`, ignored local
records, credentials, caches, or any file outside the allowlist.

The exporter creates a clean file tree; it does not sanitize an existing remote's
history or stored LFS objects. Do not publish old repository history as part of
this release. Remote publication is a separate operation.
