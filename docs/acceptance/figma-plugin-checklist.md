# Internal live Figma workflow acceptance checklist

Use a clean release candidate and production internal HTTPS origin. Run desktop and browser Figma separately. Record only pass/fail and operational metadata: never record pairing codes, credentials, headers, raw selection data, or secrets.

## Release record

| Field | Value |
|---|---|
| Date (local time) | |
| Tester | |
| Server commit/build | |
| Web build | |
| Plugin ID/build | |
| Internal HTTPS origin | |
| Windows Agent version/host | |
| Test FairyGUI project copy | |

## Figma desktop

| Check | Pass/Fail | Safe notes |
|---|---|---|
| Private organization plugin is available and has one restricted internal HTTPS domain | | |
| Fresh pairing completes | | |
| Select frame/component; preflight shows counts, resource estimate, warnings | | |
| Send completes and opens task, or open-task/copy-link recovery opens it | | |
| Console shows selection name and thumbnails | | |
| Current FairyGUI ZIP/package reaches review and whole-update approval | | |
| Bound Agent applies once and creates job backup | | |
| Revoke paired device; its later upload is rejected | | |

## Figma browser

| Check | Pass/Fail | Safe notes |
|---|---|---|
| Private organization plugin starts in browser Figma | | |
| Fresh pairing completes | | |
| Frame/component preflight and send complete | | |
| Automatic or retained recovery opens task | | |
| Selection summary/thumbnails, ZIP/package/review, and approval work | | |
| Agent applies and backup exists | | |
| Revoke paired device; retry is rejected | | |

## Safety and recovery

| Check | Pass/Fail | Safe notes |
|---|---|---|
| Server HTTPS origin matches the sole plugin manifest domain; fixture jobs are unavailable | | |
| Relevant local edit returns `local_project_changed` with no new backup | | |
| Restore a test job from `<project>\.figma-to-fgui\backups\<job-id>` and manually reload FairyGUI | | |
| No credentials/codes were saved in this checklist or release notes | | |

Both Figma modes and safety checks must pass before rollout. On failure, stop rollout, preserve only safe logs/build IDs, revoke affected devices if necessary, and follow the deployment rollback procedure.
