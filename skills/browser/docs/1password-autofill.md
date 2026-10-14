# 1Password autofill

Use this when logging in with the configured 1Password extension. For initial configuration, read [1Password setup](1password-setup.md).

1Password draws two **panels** inside the page: the inline menu under a focused sign-in field and the "Sign in with a passkey" popup at the top right. Both list saved entries by title and email. Snapshots show only the inline menu's status, `1Password menu is available. Press down arrow to select.`; screenshots show both panels, so pick entries with `click_at`.

Work on the task's existing thread from the [browser skill workflow](../SKILL.md). Keep passwords, cookies, and other secrets out of printed output.

## Login loop

Click the sign-in field (if the click is `intercepted` by the field's own label, click the label). Then repeat until the page shows the signed-in account: its name, a sign-out control, or the page the login was for.

1. **Settle**: a click starts fills, submits and panels that finish later, and reading early invites a second submit. `thread.wait(url=...)` when you know where the login lands, else `thread.sleep(1500)` after a field click and `thread.sleep(3000)` after any other.
2. Emit a snapshot. Signed in: done. A captcha, one-time code or error: fallback.
3. Capture the viewport, view it, and click:
   - a panel entry for the task's account, preferring the passkey popup, with `click_at` at its center;
   - else a control that advances the login (a new sign-in field, Next, the site's "Sign in with passkey"), by ref;
   - else: fallback.

```python
thread.click("@e7")  # sign-in field from the snapshot
thread.sleep(1500)
thread.emit(thread.snapshot())
thread.screenshot("/tmp/surf-login.png")
# view the image, then:
thread.click_at(1158, 449)  # entry center
thread.sleep(3000)
thread.emit(thread.snapshot())
```

- Several entries could match and the task doesn't say which: ask the user.
- Same panel still showing after two clicks on it: fallback.
- Coordinates are in the image file's pixels, which equal the viewport (`thread.evaluate("[innerWidth, innerHeight]")`); if your view of the image is smaller, scale the point up.

## Without image viewing

Use this only when any saved login suits the task: the status never names the entry. After the field click, once the status shows, `thread.press("ArrowDown")` then `thread.press("Enter")` fills the first entry; continue the loop from snapshots. Keys never reach the passkey popup: when the login needs it, fall back.

## Fallback

Follow [Login and human unblock](../SKILL.md#login-and-human-unblock). When 1Password is locked, ask the user to unlock the desktop app, then restart the loop.
