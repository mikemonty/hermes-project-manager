# Project Manager (experimental)

This is an early local-first project content manager for Hermes. It provides native agent tools for initializing an explicitly chosen existing folder, organizing sections and units, reading project history, and appending version-checked source, draft, review, and notes events. The project folder is the shared store; it is not a media player.

## Current scope

- Requires an existing absolute folder selected by the caller; the plugin does not infer a path or register a Hermes project.
- Initialization creates `.hermespm-project.json` exclusively. Existing metadata is not overwritten.
- Event history is append-only; stale versions conflict instead of overwriting.
- `desktop/plugin.js` provides a blank-first-run, local-only project/section/unit workspace with an editable multiline unit text field. Saving stores the exact text in the Desktop profile's `localStorage`; closing and reopening the editor restores it. This is browser-profile persistence, not a backup, sync, or connection to the Python tools. A local-file reference media library is not included.
- Video/audio playback, thumbnail generation, and typed media blocks are not implemented. Media references in the source prototype do not imply playback support.
- This is experimental software, not a security sandbox, backup, or durability guarantee. Use only test content until independently reviewed.

## First run

Use a disposable existing empty directory and synthetic content. Call `project_initialize` with that explicit absolute directory and an ID. Then create a section and unit using `project_organize`, inspect with `project_list` / `project_read`, and append edits with the current expected version and a unique event ID. Initialization writes metadata only.

## Development

Run `python3 -m unittest discover -s tests -v`; validate with `hermes plugins validate . --install-deps` and `hermes plugins doctor . --ci`.

This is an initial rough version. Development is ongoing; improvements are planned as the plugin is tested and reviewed. Catalog updates require review, so no fixed release schedule is promised.
