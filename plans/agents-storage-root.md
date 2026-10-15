---
status: done
---

# Store Surf files under `~/.agents`

## Goal

Surf keeps its files at the same paths on Linux and macOS:

- `~/.agents/config/surf-agent/` — user-edited settings (`config.json`).
- `~/.agents/state/surf-agent/` — everything Surf writes and keeps: the Chrome profile (`profiles/chrome`), lifecycle and search locks, cookie-import bookkeeping, captcha markers, and session sockets when `XDG_RUNTIME_DIR` is unset.

`SURF_AGENT_HOME` still overrides both roots, and `SURF_AGENT_PROFILE_DIR` the profile. Existing installs migrate through an explicit one-time command; the runtime never moves files on its own.

## Intention

One convention every agent skill can follow, independent of OS:

| Kind | Writer | Deletable | Location |
|---|---|---|---|
| config | user | no | `~/.agents/config/<app>` |
| state | app | no, may hold logins; apps document their reset targets | `~/.agents/state/<app>` |
| cache | app | always | OS cache dir (platformdirs `user_cache_dir`) |

platformdirs splits config/state/data on Linux but collapses all three into `~/Library/Application Support/<app>` on macOS, so the old layout was neither uniform nor meaningfully separated. Surf has no cache of its own today, so it uses only config and state.

## Scope & Constraints

In scope:
- `packages/surf-agent/src/surf_agent/runtime.py`: new roots; `surf_agent_state_dir()` and `surf_agent_data_dir()` merge into the state root; drop `APP_DIRS`.
- `packages/surf-agent/src/surf_agent/backends/patchright/bridge.py:778-779`: drop its private platformdirs copy of the profile default; use `runtime.default_patchright_profile_dir()`.
- A temporary, separate module `surf_agent/legacy_storage.py` holding the legacy-path guard and the migration command. It is the only remaining platformdirs user.
- Docs: ADR, `README.md`, `skills/browser/docs/patchright-backend.md`, `skills/browser/docs/launcher.md`, any other path mentions.
- The convention in `~/.agents/AGENTS.md` "Storage Locations" and dotman ignore entries for `config/` and `state/`, both edited in the dotfiles repo (`packages/agents/`).
- Runtime pin per project AGENTS.md.

Out of scope (follow-up issues):
- Chrome disk cache to `user_cache_dir` via `--disk-cache-dir`.
- Disabling Chrome's on-device model download (`OptGuideOnDeviceModel`, ~4 GB).
- Removing `legacy_storage.py` and the platformdirs dependency after one release.

Constraints:
- No automatic file moves in runtime code paths.
- Live Google checks: at most one search, per project AGENTS.md.
- Do not touch the user's real profile until the runtime change is reviewed; stop old sessions and the bridge before migrating.

## Work Plan

1. Runtime paths: `AGENTS_ROOT = Path.home() / ".agents"`; `surf_agent_config_dir()` → `AGENTS_ROOT/config/surf-agent`; `surf_agent_state_dir()` → `AGENTS_ROOT/state/surf-agent`; profile under the state dir. Remove `surf_agent_data_dir()`; repoint callers. Fix the bridge's duplicate default.
2. Guard: when `SURF_AGENT_HOME` is unset, `SurfAgent()` fails fast if a legacy item exists and its new counterpart does not. Items, per platform:
   - Linux: `~/.config/surf-agent/config.json`, `~/.local/share/surf-agent/profiles`, `~/.local/state/surf-agent/cookie-import.json`.
   - macOS: the same three names under `~/Library/Application Support/surf-agent/`.
   The check is per item, not per root, because session sockets can create the new state dir before `SurfAgent` runs, and a stale old-pin process can recreate empty legacy roots. Profile item is skipped when `SURF_AGENT_PROFILE_DIR` is set. The error names the migration command.
3. Migration command `migrate_legacy_storage()`, run through the launcher:
   ```
   python3 "$BROWSER_SKILL/scripts/run.py" - <<'PY'
   from surf_agent.legacy_storage import migrate_legacy_storage
   migrate_legacy_storage()
   PY
   ```
   - Refuses while Chrome runs on the legacy profile (`find_active_chrome_roots`).
   - Per item, `os.rename` only when the target is absent (idempotent, never nests); creates target parents.
   - Cross-filesystem rename (`EXDEV`) stops with a message to move manually; no 7 GB copy.
   - Leaves everything else (locks, path-hashed captcha markers, legacy `threads/`) and prints the leftover legacy roots for the user to trash.
4. Docs and ADR `docs/adr/0009-store-files-under-agents-root.md`.
5. Independent test agent (blind to this plan) writes tests from the user's goal and public interface; existing `test_runtime.py` cases that encode the platformdirs contract are replaced, not kept.
6. Independent review agent on the final diff.
7. Commit runtime change, then pin commit (`git log -1 --format=%H -- packages`).
8. Dotfiles: add `config/` and `state/` to `d_agents` ignore; add the convention to AGENTS.md "Storage Locations".
9. Rollout on this machine: kill sessions and `stop_bridge()` on the old pin; run the migration; one live browser check (no Google burst); trash leftovers after confirming logins survive.
10. Push branch, PR, merge.

## Validation

- Scoped pytest for `packages/surf-agent` and `packages/surf-google-search`; full suite once at the end.
- Migration exercised in tests on fake Linux and macOS legacy layouts (`HOME` redirected), including re-run after partial migration and an existing non-empty target.
- Live: after migrating, open the browser on the moved profile and confirm a logged-in site still shows the session.

## Progress

- [x] Decisions agreed with user (2026-10-14).
- [x] Steps 1–3 implemented.
- [x] Docs and ADR.
- [x] Independent tests (25, then 3 regression tests that fail on 3d62689).
- [x] Independent review; findings fixed in f2ed651.
- [x] Runtime + pin commits (final runtime f2ed651, pin a0e5fed).
- [x] Dotfiles convention and ignores (dotfiles branch `feat/agents-storage-convention`, 4b1b0c3f; bullet applied to live `~/.agents/AGENTS.md` by hand because the repo holds other unpushed changes).
- [x] Local migration and live check: three items moved, 7.0 GB profile kept its inode, GitHub logged in as the user through the launcher; legacy folders trashed.
- [x] PR merged.

## Surprises & Discoveries

- Independent tests found two silent fresh-profile paths: a profile at both locations was skipped and its folder offered for trashing, and a hand-started bridge without `--profile-dir` ignored legacy files. The guard now refuses while any legacy item exists.
- Review found the google-search CLI masked the guard as `internal_error`; it now reports `browser_unavailable` with the migration command on stderr. The leftover list ignored overrides and could offer the folder still holding the profile.
- From the repo workspace environment, `Thread.open` sometimes stayed on `about:blank`; the same code through the launcher worked (#38).

- Tests read the real home: `SurfAgent()` without `SURF_AGENT_HOME` hit the user's legacy files. `tests/conftest.py` now redirects `HOME` and unsets `XDG_{CONFIG,STATE,DATA}_HOME` for every test.
- An old-pin bridge blocks both migration and `stop_bridge()` (guard). The migration stops a bridge bound to the legacy profile itself, since its identity check proves it is the old one.

- macOS session sockets under the old layout land in `~/Library/Application Support/surf-agent/surf-agent/`; the new root shortens the socket dir path, which helps the 103-byte limit (`session.py:64`).
- The profile is 7.0 GB but ~95% regenerable (4 GB on-device model, ~2 GB caches); cookies are ~1 MB.

## Decisions

- **Root `~/.agents/<kind>/<app>`** over platformdirs (non-uniform across OS), XDG on macOS too (close second, 3.90 vs 4.00; loses only if no other skill ever stores files), one folder per app (mixes kinds, needs per-app ignores/grants), honoring `XDG_*` when set (user's shell sets them, so Linux would diverge from macOS again).
- **Merge state and data** (4.25 vs 3.65): the split's benefits (whole-kind wipes, skip-state backups) are negligible for Surf, while the state-vs-data choice is a recurring ambiguity for every skill author. Mitigation for "wipe state logs you out": the convention says state is never wiped wholesale.
- **Cache stays OS-specific**: macOS excludes `~/Library/Caches` from Time Machine and may purge it; nobody needs to find a cache, so uniform paths buy nothing.
- **Explicit migration command** (4.25) over automatic startup migration (3.50: moves logins without consent, multi-step moves can half-fail, mixes migration into runtime) and manual shell commands in the error (3.75: per-OS commands, `mv` nesting pitfall).
- **Dotfile sync** is handled by dotman ignore entries, not by avoiding `~/.agents`.

## Outcomes & Retrospective

Surf keeps `config.json` in `~/.agents/config/surf-agent/` and everything else in `~/.agents/state/surf-agent/` on Linux and macOS; the convention is in ADR 0009 and the user's global AGENTS.md. This machine migrated with the explicit command and kept its logins.

Follow-ups: #36 (Chrome caches and on-device model out of the profile), #37 (remove `legacy_storage` and platformdirs after one release), #38 (dev-environment navigation).

Retrospective: an independent tester blind to the plan caught the two data-loss paths the design review had not; per-item checks (not per-root) were the right unit throughout.
