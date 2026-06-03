# Seed Data Design Spec

Target shapes and distributions for Deep Harbor's synthetic dev/test seed data — for both the
static seed (`pg/sql/seed_data.sql.example`) and the generator (`pg/tools/generate_seed_data.py`).

The current seed data is unrealistically clean: it doesn't carry the dirty-data edge cases, skewed
distributions, and historical-format quirks that the real membership data has. Code and tests that
pass against clean seed data then break against messy real data. This spec defines a **realistic
shape** so local dev and testing exercise the same realities as the live system.

All numbers below are **ratios / percentages**. The generator takes a member count `N` and a seed;
it produces `N` rows at these ratios. No absolute population figures are part of the spec.

---

## Governing principle: structure = `dev`, statistics = realistic

These two axes are independent and must not be conflated:

- **Structure** (which columns/keys/tables exist, permission formats, value *types*) follows the
  **current `dev` schema** — `pg/sql/pgsql_schema.sql`. `dev` is ahead of production, so the seed
  targets the post-deployment shape, not whatever an older deployment happens to have.
- **Statistics** (how values are *distributed* — status skew, format jitter, dead fields, type
  drift) follow **realistic membership-data patterns** for a long-lived hackerspace CRM that
  migrated from a prior platform ("WA" / Wild Apricot) and accreted quirks over ~17 years.

Where the realistic pattern reflects an *older* structure than `dev` has, **structure wins**. The
explicit overrides are tabled below.

### Deliberate divergences from observed patterns (structure wins)

| Concept | Older/observed shape | What the seed must generate (`dev` structure) |
|---|---|---|
| Role permission tokens | bare suffixes (`identity`, `status`, …) | **namespaced** (`member.identity`, `space.access_logs`, `systems.*`) — see #279 |
| `oauth2_users` columns | minimal (`client_name` PK, secret, description, date) | **full** shape: `id`, `disabled`, `created_by_member_id`, `last_used_at`, `rotated_at` — see #290 |
| ID-check fields | free-form `forms.id_check_1` / `id_check_2` only | structured `forms.id_check_date` + `forms.id_check_by` **plus** legacy fields retained read-only ("WA Legacy") — see #265 |

---

## Dev structural baseline

Verified against `pg/sql/pgsql_schema.sql`.

- **`member`** has 8 JSONB columns: `identity` (NOT NULL), `connections`, `status`, `forms`,
  `access`, `authorizations`, `extras`, `notes`. Plus `id`, `date_added`, `date_modified`,
  `last_updated_by`.
- **JSONB key inventory (44 keys)** across the 8 columns — the complete top-level key set the seed
  may emit:

  | Column | Keys |
  |---|---|
  | identity | `active_directory_username`, `emails`, `first_name`, `last_name`, `nickname`, `birthday`, `aliases`, `pronouns`, `member_id`, `primary_email`, `nametag_subtitle`, `theme_song_duration`, `theme_song_url` |
  | connections | `discord_handle`, `phone`, `wildapricot_id`, `stripe_customer_id`, `stripe_id` |
  | status | `member_since`, `membership_level`, `membership_status`, `renewal_date`, `balance`, `donations`, `donor`, `stripe_product_id`, `stripe_subscription_id`, `waiver_signed` |
  | forms | `id_check_1`, `id_check_2`, `id_check_date`, `id_check_by`, `orientation_completed_date`, `terms_of_use_accepted`, `covid_vaccine_policy_acknowledged`, `essentials_form_completed_date`, `waiver_signed_date`, `essentials_forms_completed_date`, `is_21_or_older`, `waiver_signed_at` |
  | access | `rfid_tags` |
  | authorizations | `authorizations`, `computer_authorizations` |
  | extras | `storage_area`, `ip_addresses`, `server_rack_space` |
  | notes | *(JSONB array of objects, not an object — see Notes)* |

  (`forms.id_check_date` + `forms.id_check_by` are the structured replacements from #265; the older
  `id_check_1`/`id_check_2` stay as read-only WA Legacy fields.)

- **`roles`** holds 7 rows with **namespaced** permission tokens (#279). `v_member_info` exposes the
  `forms` ID-check fields and routes date casts through `safe_to_date` (#302). `oauth2_users` carries
  the full expanded shape (#290). The `log_member_changes()` trigger emits **one `member_changes`
  row per changed column** (#242) — relevant to any generated dispatch-chain data.
- A `membership_types_lookup` table exists (`id`/`name`/`description`), but `status.membership_level`
  is a **free-form string** in JSONB, not an FK to it — model levels as strings (below).

### NULL whole-column quirk

The insert path doesn't always default JSONB columns to `{}`. A **handful of rows (well under 1%)**
should carry a NULL whole column — most visibly `extras`, `authorizations`, `notes` — rather than an
empty object. Code that assumes every column is a non-null object should trip on these.

---

## Cohort model

Two **disjoint** signup cohorts, plus orthogonal opt-in features. **Never mix cohort A and cohort B
keys within a single member.**

- **Cohort A — "WA migration" (~95% of members):** carries `connections.wildapricot_id`,
  `status.balance` / `donations` / `donor`, `forms.essentials_form_completed_date` (**singular**),
  `forms.waiver_signed_date`, `forms.covid_vaccine_policy_acknowledged`, `extras.ip_addresses`,
  `extras.server_rack_space`.
- **Cohort B — "post-migration" (~5% of members):** carries `forms.essentials_forms_completed_date`
  (**plural**), `forms.waiver_signed_at`, `forms.is_21_or_older`, `status.waiver_signed`. Also
  persists `member_since` as a date-only string (see status).
- **Opt-in features (orthogonal, each ~5–6% of members):** `identity.member_id` + `primary_email`
  pair; the nametag/theme-song trio; `identity.pronouns`; an active Stripe subscription.

---

## Per-column member generation spec

Each entry notes the **target** distribution. "current →" notes where today's generator differs.

### identity

- **emails** — JSONB array with **exactly 1** element per member, unique case-insensitively. Length
  **48–89 chars** (avg ~61). *current → generator/static emit short `example.com` addresses (~24
  chars); lengthen them.* These represent ordinary long real-world addresses (custom domains,
  work/university), not a special format.
- **first_name / last_name** — always present, non-empty.
- **nickname** — real value on only **~14%**; **~78% JSON null**; remainder empty string.
- **active_directory_username** — present on **~98%**; **~1.6% null or empty** (legacy/import gaps).
  Don't assume it always exists.
- **birthday** — three coexisting states: **~94% naive datetime** (19-char, no TZ) / **~5% bare ISO
  date** (10-char) / **~1% JSON null**. (Migration to normalize these is tracked in #285; until it
  lands, the seed mirrors the mixed state.)
- **aliases** — dead field: always `[]` when present; omit the key entirely on **~8%** of members.
- **pronouns** — key present on **~6%**; of those ~50% populated / ~50% empty.
- **member_id + primary_email** (opt-in cohort, **~6%**) — `primary_email` is a string;
  `member_id` is **mostly a JSON number with ~1 string-typed outlier** in the cohort (type drift to
  preserve). `primary_email` length ~11–46.
- **nametag/theme-song** (opt-in cohort, **~5%**) — within it: `nametag_subtitle` populated on ~13%
  (string, ~1–41 chars); `theme_song_url` + `theme_song_duration` populated on ~6% and **coupled**
  (always set together). **`theme_song_duration` is a string, not a number** (e.g. `"180"`) — keep
  that type drift.

### connections

- **phone** — buckets: **~78% bare 10 digits** / **~11% empty** / **~8% dashed `XXX-XXX-XXXX`** /
  ~1% `+1` country-code / ~1% space-separated / ~0.5% dot-separated / ~0.4% paren `(XXX) XXX-XXXX` /
  ~0.2% broken 9-digit (preserve the dirty ones). No international numbers. *current → generator
  doesn't model `phone`; add it.*
- **discord_handle** — present on most members; mix of legacy `name#1234` and modern lowercase forms.
- **wildapricot_id** — **cohort A only**, stored as an **8-digit JSON number** (not string), unique.
  *current → absent; add for cohort A.*
- **stripe_id vs stripe_customer_id** — both store customer IDs (`cus_<14 alnum>`). Co-occurrence:
  **~63% neither / ~19% both / ~11% customer-only / ~7% id-only**. Of the "both" group, ~98% hold
  identical values, ~2% differ. Model as two independent fields with this overlap, not a clean rename.

### status

- **membership_status** — **~73% suspended / ~25% active / ~1% pending / <1% banned**; `inactive` is
  a valid status but effectively unused (0%). *current → 50/35/10/5; flip to suspended-heavy.* All
  lowercase.
- **membership_level** — free-form string from these families (% of all members, approximate):

  | Family | ~share | Examples |
  |---|---|---|
  | `zDEFUNCT -` prefixed | ~46% | `zDEFUNCT - Member`, `zDEFUNCT - Member w/ Storage` |
  | Stripe (price in name) | ~30% | `Stripe Member - $65`, `Stripe Member w/ Storage - $95` |
  | WA-era generic | ~14% | `Membership`, `New Member`, `Membership with Storage` |
  | PayPal | ~4.5% | `Member - PayPal`, `Member w/ Storage - PayPal` |
  | Role-based | ~3% | `Volunteer`, `Board Member / Officer`, `Area Host`, `Scholarship` |
  | Blank | ~1.7% | empty string (~9 parts) **or** JSON null (~1 part) |

  Include a long tail of one-off historical levels (e.g. `Member - Grandfathered Price`). *current →
  clean 8-value enum with no zDEFUNCT/Stripe-price/PayPal/blank; rebuild around these families.*

  **Coupling rules (hard):**
  - `zDEFUNCT -*` ⇒ **always `suspended`**.
  - `pending` ⇒ **always WA-era generic** (`New Member` / `Membership`), never Stripe-tier.
  - PayPal ⇒ only `active` or `suspended` (never pending/banned).
  - **~47% of Stripe-tier members are `suspended`** (cancelled subs whose level never changed) — do
    NOT assume Stripe-tier ⇒ active.
- **member_since** — **~87% TZ-aware datetime** (25-char) / **~5% date-only** (10-char, = cohort B) /
  **~6% JSON null** / **~2% empty string**. Year skew rises 2014→2024 with a 2020 dip; include ~1 in
  ~3000 corrupt year (e.g. `1992`) and a tiny pre-2014 founding tail.
- **renewal_date** — **naive datetime** (19-char, no TZ — note `member_since` carries TZ but this
  doesn't): **~46% populated / ~47% null / ~7% empty**. Stale by design — leave null/stale for most
  active members (Stripe-subscription members bypass it); populate mainly for the legacy annual cohort.
- **balance** — **~97% zero / ~2% small positive (≤ ~$50) / ~1% small negative** (credits). Encoded
  as **JSON number ~96% / JSON string ~4%** (same values, mixed encoding — preserve both).
- **donations** — **dead field: always `0`** (cohort A). Same number/string encoding split. Don't
  fabricate amounts.
- **donor** — boolean, cohort A.
- **stripe_subscription_id (`sub_<24>`) × stripe_product_id (`prod_<14>`)** — keys present on **~11%**
  of members; **perfectly coupled** across three states: ~67% both populated / ~32% both JSON null /
  ~1% both empty string. Never mixed.
- **"Paying but no Stripe IDs" gap** — of active Stripe-tier members, generate **~30–40% with NO
  Stripe IDs** in either `connections` or `status` (root cause tracked in #283). Lets tests catch
  code that assumes Stripe-tier ⇒ has Stripe IDs.
- **waiver_signed** — boolean, **cohort B only**.

### forms

- **terms_of_use_accepted** — boolean `true`, universal.
- **id_check_1 / id_check_2** (legacy, universal) — free-form, dirty. Buckets: a large `null/empty`
  share (esp. `id_check_2`), a `~16-char` majority (DL-prefix / "Driver's License [date]" style),
  long free-form notes (51–116 chars) on a minority, plus placeholders and a few US-slash/dash dates.
  No parseable real DL numbers. *current → generator's legacy-pair patterns already approximate this.*
- **id_check_date + id_check_by** (structured, #265) — ISO `YYYY-MM-DD` + an int member id resolving
  to an onboarder. *current → generator already models the 4-cell matrix (legacy-only / new-only /
  both / empty ≈ 60/17/17/6) with onboarder-biased `id_check_by`; keep it.*
- **orientation_completed_date** — cohort A, 19-char naive datetime on **~9%**, else null.
- **waiver_signed_date** — cohort A, 19-char naive datetime on **~53%**, else null.
- **essentials_form_completed_date** (singular, cohort A) — populated on **~2%**, else null.
- **covid_vaccine_policy_acknowledged** — cohort A, deprecated; string of rough shape on a minority,
  else null. Value is inert.
- **essentials_forms_completed_date** (plural) + **waiver_signed_at** + **is_21_or_older** — cohort B.
  The two date fields are **dead** (always empty string or null, never populated); `is_21_or_older`
  is a boolean (being phased out in favor of computing age from `birthday`).

### access

- **rfid_tags** — JSONB array of strings. Zero-inflated: per-member avg ~0.9, **~20% of key-holders
  have `[]`**, p95 = 2, long tail to ~10. Tags are **digit-only** (the access reader stores them as
  numbers and lpads to 10 digits on read — never hex), **~10 chars**, unique, with an occasional
  longer numeric tail (up to ~38 chars) and **~0.5% empty-string** entries (dirty — preserve).

### authorizations

- **authorizations** — array of strings from a fixed pool of **~37** tool-permission names (6–24
  chars). Heavily zero-inflated: **~70% empty**, p95 = 9, max ~36. *current → generator has a small
  pool; widen toward ~37 and match the zero-inflation.*
- **computer_authorizations** — array from a fixed pool of **~10** longer group identifiers (21–29
  chars, likely AD groups). **~73% empty**, p95 = 3, max ~8.

### extras

- **storage_area** — three states: **~37% JSON null / ~59% empty string / ~4% populated**. Populated
  values are **unique** short alphanumeric codes (3–7 chars) — one per occupant, don't reuse.
- **ip_addresses / server_rack_space** — dead: **~99.9% JSON null** (cohort A). Don't populate.

### notes

- JSONB **array** of objects, avg ~1.86 / median 1 / p95 5 / max ~11 per member. Each object is
  **`{timestamp, from, note}` ~98.5%** of the time, **`{timestamp}`-only ~1.5%** (stubs). *current →
  generator emits `{date, author, text}`-style objects; reshape to `{timestamp, from, note}`.*

---

## Roles & assignment shape

- **7 roles**, namespaced permissions (per #279, seeded in `pg/sql/pgsql_schema.sql`): Authorizer,
  Administrator, Board, ID Check, CTO, Treasurer, Area Host.
- **`member_to_role`:** only **~1% of members** hold any role; **exactly 1 role each** (never
  multi-role — that path has never been exercised). Skewed:

  | Role | ~share of role-holders |
  |---|---|
  | Authorizer | ~40% |
  | Board | ~23% |
  | Area Host | ~17% |
  | Administrator | ~10% |
  | ID Check | ~7% |
  | CTO | ~3% |
  | Treasurer | **0% (defined but unassigned)** |

- **~93% of role-holders are `active`.** Allow **one** suspended-with-narrow-role outlier (ID Check /
  Area Host / Authorizer only — never a suspended Administrator/CTO/Board). **Zero** banned-with-role,
  **zero** pending-with-role.

---

## Other tables (future generator extension)

The generator currently emits `member` rows plus dev `member_to_role` assignments only. The
following shapes are documented now so the gap is explicit and a later extension has a target. The
static seed may include a small representative set of each.

- **`oauth2_users`** — a small set (a handful, not hundreds), all created in a **tight window**, all
  with populated `client_description`. Generate against the **full** `dev` schema shape (#290).
- **`member_changes`** — row `data` shape `{member_id, change, <one of identity|status|access|
  authorizations>}`, where `change` is the **column-name string**. Type distribution ~29% status /
  ~28% authorizations / ~25% identity / ~17% access. The payload under the column key is the **full
  new column state**, not a delta. Only those 4 columns trigger changes (never connections / forms /
  extras / notes). ~100% `processed` at rest; seed a few unprocessed for dispatcher load-testing.
- **`member_changes_processing_log`** — ~3.9 attempts per change. One **chronically-failing lane**
  (`access` ~6% success, ~17 attempts/change — flakey-hardware retries, by design) alongside healthy
  lanes (~1.1 attempts, ~90% success). All failures are HTTP 500; zero 4xx.
- **`member_audit`** — a burst of ~8 versions/member at import time, then ~1 version/member/month.
  **~94% NULL `last_updated_by`** (system writes) / ~6% from a small admin pool. Versions increase
  monotonically per member, capped well under ~50 within a few months. Each row carries the full
  8-column JSONB snapshot.
- **`member_access_log`** — steady volume from a swiping subset (~26% of tag-holders; ~73% of active
  members swipe). **~95% granted / ~5% denied.** `access_point` stored as **integer strings**
  (`"1"`, `"2"`); door `"2"` ~2× the denial rate of `"1"`. **~4% NULL `member_id`** (post-deletion
  rows preserved). **Naive timestamps** (no TZ).
- **`waivers`** — `details` has exactly `{type, content, content_type}`; `content.data` is always a
  populated array; payloads ~1.2–2 KB. Steady low daily volume, no spikes.

---

## Notes for implementers

- The generator is deterministic (seed → `random` + `Faker`). Vary any per-row randomness by index
  so a fixed seed reproduces a fixed dataset.
- The static seed (`seed_data.sql.example`) is a small hand-curated fixture set; its first members
  are stable dev-login fixtures with fixed roles — preserve those identities and assignments while
  layering the quirks above onto the set as a whole.
- "Dead" / inert fields (donations, aliases, ip_addresses, server_rack_space, cohort-B date fields)
  matter for **schema fidelity**, not behavior — emit them in the right shape, don't invent meaning.
