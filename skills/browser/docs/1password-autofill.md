# 1Password autofill

Use this when logging in with the configured 1Password extension. For initial configuration, read [1Password setup](1password-setup.md).

1Password draws two **panels** inside the page: the inline menu under a focused sign-in field, and the "Sign in with a passkey" popup at the top right of the viewport. Both list saved entries by title and email. Snapshots show only a status line for the inline menu, `1Password menu is available. Press down arrow to select.`, never the entries, and refs can't reach either panel; screenshots show both, so pick entries by position with `click_at`. A panel can appear at any point: on page load, when a field gets focus, or after a click, such as a selected entry leading to a passkey popup on the next page.

Work on the task's existing thread and interpreter mode from the [browser skill workflow](../SKILL.md); these steps assume `thread` already shows the login page with an emitted snapshot (in a fresh script, rebuild it as `Thread(<task thread name>)`). Keep passwords, cookies, and other secrets out of printed output.

## Login loop

Done when page state shows the signed-in account: its name, a sign-out control, or the page the login was for.

1. Click the observed sign-in field, then emit a snapshot, capture the viewport and view the image. If the click fails with `intercepted` by the field's own label, click that label instead: it focuses the field.

   ```python
   thread.click("@e7")  # sign-in field ref from the observed snapshot
   thread.emit(thread.snapshot())
   thread.screenshot("/tmp/surf-login.png")
   ```

2. Find the task's account in a panel by title and email, preferring the passkey popup when both show. If several entries could match and the task doesn't say which, ask the user, then restart at step 1. Click the entry's center in the image file's pixels: the file is the viewport's size (`thread.evaluate("[innerWidth, innerHeight]")`), so if your view of it is smaller, scale the point up by the ratio. One click can fill and submit the form, or finish a passkey sign-in.

   ```python
   thread.click_at(1158, 449)  # entry center from the screenshot
   thread.emit(thread.snapshot())
   thread.screenshot("/tmp/surf-login.png")
   ```

3. Decide from the page; if it is still loading, `wait()` for the next page or capture again before deciding:
   - Signed in: done.
   - A panel shows: step 2. The same panel still showing after two clicks on it: fallback.
   - A new sign-in field, such as the password step: step 1.
   - A control the login needs, such as Next or the site's own "Sign in with passkey" button: click it by ref, capture the viewport, and repeat step 3.
   - No panel and no `1Password menu is available` status after step 1, no entry for the task's account, an unlock prompt, a captcha, a one-time code, or an error: fallback.

## Without image viewing

Without image viewing you can't see either panel, so you can't tell how many entries exist or which one comes first; take this path only when any saved login suits the task. Do step 1, and once its snapshot shows the `1Password menu is available` status, `thread.press("ArrowDown")` then `thread.press("Enter")` fills the first entry. Continue at step 3, reading snapshots instead of screenshots, and confirm which account signed in. Keys never reach the passkey popup: when the login needs it, follow the fallback and ask the user to pick the entry.

## Fallback (locked or no match)

Follow [Login and human unblock](../SKILL.md#login-and-human-unblock). When 1Password is locked, ask the user to unlock the desktop app, then restart the loop.
