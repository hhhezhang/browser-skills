---
status: rejected
---

# Store Surf files under `~/.agents`

Surf used platformdirs: `~/.config`, `~/.local/state` and `~/.local/share` on Linux, but one `~/Library/Application Support/surf-agent` folder for all three on macOS. Paths differed per OS, and the config/state/data split existed only on Linux. Agent skills want one layout that people and agents find the same way everywhere.

Surf now keeps `config.json` in `~/.agents/config/surf-agent/` and everything it writes, including the Chrome profile, in `~/.agents/state/surf-agent/`. `SURF_AGENT_HOME` still replaces both. The convention for any agent tool:

| Kind | Writer | Deletable | Location |
|---|---|---|---|
| config | user | no | `~/.agents/config/<app>` |
| state | app | no, may hold logins | `~/.agents/state/<app>` |
| cache | app | always | OS cache folder (platformdirs `user_cache_dir`) |

## Considered options

Scored on uniform paths across OS (30%), one convention for agent tools (20%), safety (20%), migration (10%), familiarity (10%) and simplicity (10%):

- **`~/.agents/<kind>/<app>`** (4.00). Chosen.
- **XDG paths on macOS too** (3.90). Nearly as good; it wins only if no other skill ever stores files.
- **Keep platformdirs** (2.70). Not uniform.
- **One folder per app, `~/.agents/<app>`** (3.70). Mixes logins with disposable files and needs a dotfile ignore and sandbox grant per tool.
- **Honor `XDG_*` when set** (2.80). The user's shell sets them, so Linux would diverge from macOS again.

**Separate `state` and `data`** (3.65 against 4.25 for merging). Rejected: wiping all of state at once and skipping small state in backups gain nothing for Surf, while every skill author would have to decide which kind each file is. In exchange, state is never wiped wholesale.

**Cache under `~/.agents`.** Rejected: macOS keeps `~/Library/Caches` out of Time Machine and may purge it, and nobody needs to find a cache.

**Automatic migration at startup** (3.50 against 4.25 for an explicit command). Rejected: it would move logins without consent, and the multi-step moves (macOS splits one folder, Linux merges two) can half-fail.

## Consequences

`~/.agents` is synced by dotman, so `config/` and `state/` are ignored there. Sandboxes that protect `~/.agents` must grant write access to `~/.agents/state` only, never to all of `~/.agents`. `surf_agent.legacy_storage` refuses to start while files remain at the old paths and provides the one-time `migrate_legacy_storage()`; it is removed, together with the platformdirs dependency, after installs migrate.

## Reverted

Surf went back to platformdirs a day after this shipped. Its paths are a standard other people already know, while `~/.agents/<kind>` was a private convention that put a multi-gigabyte Chrome profile inside a folder people often sync or version with their dotfiles. The cost of the revert is the split this ADR set out to remove: a macOS shell that sets `XDG_*` sends files to the XDG folders, while apps started outside it use `~/Library/Application Support`. That is intended; the fix belongs in the environment (give GUI apps the same `XDG_*`), not in Surf.
