# DHEquipmentPortal — Claude Code Instructions

## Context
Porting PA1 (PurpleAssetOne) equipment management frontend into Deep Harbor.
The reference file is at `reference/pa1-index.html` (6,687 lines).
The target file is `templates/index.html` which extends `base.html`.

## Key adaptations when porting from PA1
- IDs are integers, not UUIDs
- Member names come from `member.identity` JSONB, not `users.full_name`
- Permission checks use `canView('equipment.items')` / `canChange('equipment.tickets')` — already defined in the script block
- `MEMBER_ID` and `USER_PERMISSIONS` are Jinja2-injected — already in the script block
- The `api()` helper and CSRF handling are already wired up
- `/api/*` Flask proxy routes match PA1's paths exactly — don't change API URLs
- Use Bootstrap Icons (`bi bi-*`) matching PA1, not Font Awesome for section content
- CSS should use `var(--primary-color)` etc. from the theme system in `static/styles.css`
- Strip anything related to PA1's login, user management, branding settings, or auth config

## Work order
1. Shared JS infrastructure (toast, modal helpers, escHtml, calendar engine)
2. Equipment section (list, detail, add/edit modal)
3. Areas section
4. Tickets section (list, create, detail, work log)
5. Groups section
6. Scheduling section (calendar + booking)
7. Authorizations section
8. Maintenance section
9. Settings section (notifications, export)