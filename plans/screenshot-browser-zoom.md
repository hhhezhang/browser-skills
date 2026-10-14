---
status: done
---

# Screenshots under saved browser zoom (#31)

## Goal

`thread.screenshot()` shows what the window shows, or fails loudly. It never returns a cropped or blank image.

## Intention

The Surf profile is a real Chrome profile, so zoom set by hand (for example during a login handoff or `open_profile()`) persists per site and as a default. Under any zoom other than 100%, Patchright's `scale="css"` viewport screenshot captures only the top-left `1/zoom` of the viewport, and after scrolling it is blank at both scales. Agents read pages and pick `click_at` points from these images, so they silently see the wrong thing.

## Evidence (2026-10-13, Chrome stable, temp profiles, `/tmp/zoom31/`)

- 150%, headless: viewport 520×329 CSS px, css image 347×219 (top-left only); scrolled to y=800 the image is white at both scales, missing `position:fixed` boxes that are on screen.
- Same on a headed window under Xvfb (413×211 viewport, 275×141 image, blank when scrolled).
- Saved zoom comes from `Default/Preferences`: `partition.default_zoom_level.<partition key>` (key `x` for the default partition) and `partition.per_host_zoom_levels.<partition key>.<host>`. Writing `default_zoom_level` there before launch reproduces the bug.
- CDP `Page.getLayoutMetrics().cssVisualViewport.zoom` is the browser zoom, independent of display scale: 1 / 1.5 / 0.9 at zoom 100 / 150 / 90, both at `--force-device-scale-factor` 1 and 2. JS `visualViewport.scale` is pinch zoom only (stays 1).

## Decisions

- **Reset saved zoom before every bridge launch.** Remove `partition.default_zoom_level` and `partition.per_host_zoom_levels` from the profile's `Default/Preferences` while Chrome is not running for it. Write only when something changed, atomically. Missing file or keys: nothing to do.
- **Guard screenshots.** Before capturing, read the page zoom via `Page.getLayoutMetrics`; if it is not 1, raise a new stable code `page_zoomed` naming the zoom. Covers zoom applied mid-session (it lives in Chrome's memory until restart) and any future change to Chrome's pref layout. Checking zoom directly also covers full-page shots, where comparing image size to the viewport does not apply.
- `click_at` gets no check: points read from a CSS-scale screenshot still hit under zoom, and the screenshot guard removes the zoomed screenshot they would come from.

Rejected (weighted scores, criteria: correct screenshots 35, no silent failure 25, simplicity 20, no human needed 20):

- Reset only (3.50): fails silently on mid-session zoom or a Chrome pref change.
- Detect and error only (2.95): every saved-zoom site needs a human to press Ctrl+0.
- Own CDP screenshot path (3.20): reimplements Playwright capture, unclear for full-page.
- Reset zoom in-session: CDP has no browser-zoom command; synthetic Ctrl+0 never reaches browser accelerators; an extension (`chrome.tabs.setZoom`) cannot load in branded Chrome 137+ (`--load-extension` removed).

## Work Plan

1. Runtime: reset in the Patchright bridge's launch path; zoom guard in the `screenshot` tool; `ErrorCode.PAGE_ZOOMED`.
2. Docs: `skills/browser/docs/python-api.md` (screenshot + error list), `skills/browser/docs/patchright-backend.md` (reset at launch).
3. Independent agent writes tests from the public interface (live Patchright, temp profile with saved zoom).
4. Commit runtime, pin `skills/browser/runtime-revision`, independent review, PR.

## Validation

- Live (`SURF_TEST_LIVE_PATCHRIGHT=1`), temp profile, no Google: saved default and per-host zoom are gone after launch and screenshots match the viewport; zoom applied after launch makes `screenshot` raise `page_zoomed`.
- Scoped unit suite for surf-agent.

## Progress

- [x] Reproduced and chose the signal (evidence above)
- [x] Steps 1–2 (`64de425`): reset in `PatchrightRuntime._start_async` via `saved_zoom.clear_saved_zoom`, guard `_require_unzoomed` before `screenshot`, docs. Unit suite 238 passed; live Patchright 69 passed (Xvfb); ad-hoc live: 150% saved profile → prefs cleared, scrolled screenshot 780×493 with fixed boxes visible.
- [x] Step 3: independent tests `5174cd4` (7 live: saved default/per-site zoom reset, other prefs kept, mid-session zoom in/out × viewport/full-page raises `page_zoomed`), `b32742d` (frozen page). Each failed on the code before its fix.
- [x] Step 4: independent review; fixes in `f088c9c`; pins `471429f`, `398205c`. Unit 238 passed, live Patchright 77 passed (Xvfb).

## Surprises & Discoveries

- Detaching a CDP session whose query a frozen renderer never answers hangs too, so `asyncio.wait_for` around query plus detach still blocks the bridge. Detach only after an answer.
- Ctrl+0 resets to Chrome's default zoom, so it cannot undo a changed default (Settings > Appearance > Page zoom).
- Chrome sets an unreadable `Preferences` aside as `Preferences.bad` and starts from defaults, so the reset skips such a file instead of failing launch.
- Tests zoom mid-session through `chrome://settings/appearance` (`#zoomLevel`) with the bridge's own `fill`: the only scriptable zoom change found.
- The scrolled-blank case is not "scrolled out of view": the page is 3000px tall and fixed elements stay on screen, yet the image is white.

## Outcomes & Retrospective

Saved zoom no longer reaches screenshots: the bridge clears it before each launch, and a page zoomed mid-session raises `page_zoomed` instead of returning a cropped or blank image. Rationale lives in `skills/browser/docs/patchright-backend.md` and the error contract in `skills/browser/docs/python-api.md`.

The review caught a regression the plan missed: any new renderer round-trip on the screenshot path needs a bound, and its cleanup must not wait on the same renderer.
