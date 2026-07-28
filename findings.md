# Findings

- Repository starts with documentation only; there is no existing runtime convention to preserve.
- The approved first implementation batch has no dependency on Figma network access or the missing mapping file.
- The implementation plan intentionally keeps the conversion core offline and read-only with respect to source FGUI fixtures.
- Third-party packages `lxml` and `PyYAML` do not ship mypy types; narrow import overrides keep project code strict without adding stub-only dependencies.
- Generated resource IDs track both indexed and newly planned IDs, so the package cannot receive duplicate IDs within one plan.
- On this Windows machine, editable package metadata mis-encodes the Chinese workspace segment; pytest and documented development commands use the repository `src` path directly. This does not affect wheel contents.
- Pillow is not needed until the later asset-rendering subsystem, so the baseline does not carry it as an unused dependency.

## Deep User Audit

- UX designers should upload a familiar project ZIP; snapshot, SHA-256, XML, internal ID, and changeset language belongs only in advanced details.
- The Web Console layout is fixed as a three-column review workspace: understandable changes, visual before/after, and checks plus whole-update approval.
- The Agent still needs one local folder binding for automatic application, but exact internal project matching should avoid repeated selection.

- The next slice can prove the highest-risk boundary without live Figma or production infrastructure: API approval plus safe local apply and rollback.
- A Python CLI Agent is the minimum protocol-validation vehicle; the approved production target remains a .NET 8 Windows tray application.
- Immediate usability issue fixed: one-shot polling now prints applied/failed status and changed relative paths.
- Remaining deep-user pain: users still create and approve jobs through Swagger/PowerShell, the server uses fixture snapshots rather than an Agent-uploaded real project snapshot, and FairyGUI reload remains manual.
- Observable next acceptance: a Web Console shows preview/approval; Agent snapshot upload supplies pre-write hashes; a supported FairyGUI refresh mechanism removes the manual reload step.

- Real job: deterministically prove conversion rules offline before connecting them to Figma, a server, or a local writer.
- Immediate friction fixed: Windows setup and the read-only source boundary are explicit in `README.md`.
- Remaining product gap: users cannot yet fetch live Figma nodes, render image assets, update `package.xml`, or apply changes to a local FairyGUI project.
- Acceptance for the next phase: a service task accepts a Figma URL/node ID, returns the same versioned core diagnostics, and produces a downloadable preview without weakening source immutability.
- Larger follow-on work remains the approved API/Web service, Windows Agent, Figma Plugin, and Codex Plugin phases.
