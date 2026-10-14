# 1Password autofill

Use this when logging in with the configured 1Password extension. For initial configuration, read [1Password setup](1password-setup.md).

Pre-condition: 1Password desktop app unlocked.

1Password draws two **panels** inside the page: the inline menu under a focused sign-in field, and the "Sign in with a passkey" popup at the top right of the viewport. Both list saved entries by title and email. Snapshots show neither and refs can't reach them, but screenshots show both, so pick entries by position with `click_at`. A panel can appear at any point: on page load, when a field gets focus, or after a click, such as a selected entry leading to a passkey popup on the next page.

Work on the task's existing thread and interpreter mode from the [browser skill workflow](../SKILL.md); these steps assume `thread` already shows the login page with an emitted snapshot (in a fresh script, rebuild it as `Thread(<task thread name>)`). Keep passwords, cookies, and other secrets out of printed output.

## Login loop

Done when page state confirms the login, not merely when the form is gone.

1. Click the observed sign-in field. If the click fails with `intercepted` by the field's own label, click that label instead: it focuses the field.

   ```python
   thread.click("@e7")  # sign-in field ref from the observed snapshot
   ```

2. Capture the viewport and view the image:

   ```python
   thread.screenshot("/tmp/surf-login.png")
   ```

3. If a panel shows, find the entry for the task's account by title and email; if several could match and the task doesn't say which, ask the user. Click the entry's center in the image file's own pixels; if your image view is downscaled, scale the point back to the file's size first. One click can fill and submit the form, or finish a passkey sign-in.

   ```python
   thread.click_at(1158, 449)  # entry center from the screenshot
   thread.emit(thread.snapshot())
   ```

4. Read the resulting page and screenshot it again. Logged in: done. A new panel: back to step 3. A control the login still needs, such as Next or the site's own "Sign in with passkey" button: click it by ref, then screenshot again.

When no panel ever shows, and the snapshot never reads `1Password menu is available. Press down arrow to select.`, follow the [fallback](#fallback-locked-or-no-match).

## Without screenshots

When you cannot view images, use the keyboard on the inline menu: once the snapshot shows the `1Password menu is available` status, `thread.press("ArrowDown")` then `thread.press("Enter")` fills the first entry. The status never names the highlighted entry, so take this path only when the first saved login is acceptable for the task. Enter may fill only the username, and keys never reach the passkey popup; when the login needs it, follow the fallback.

## Fallback (locked or no match)

Follow [Login and human unblock](../SKILL.md#login-and-human-unblock).
