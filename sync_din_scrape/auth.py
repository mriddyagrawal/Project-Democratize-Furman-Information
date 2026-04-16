"""Authenticate to Furman Engage via Microsoft SSO using Playwright.

Automates email/password entry, then pauses for the user to complete
any extra steps (Duo MFA, "Stay signed in?" prompts, etc.).
Persists the browser session so subsequent runs skip login entirely.
"""

import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright, Page, BrowserContext

ENGAGE_HOME = "https://furman.campuslabs.com/engage"
LOGIN_TRIGGER = "https://furman.campuslabs.com/engage/account/logon"
HERE = Path(__file__).parent
SESSION_DIR = HERE / "auth_session"

# How long (ms) to wait for the user to finish MFA / Duo / extra prompts
MFA_TIMEOUT_MS = 120_000  # 2 minutes


def _load_credentials() -> tuple[str, str]:
    email = os.environ.get("FURMAN_EMAIL", "")
    password = os.environ.get("FURMAN_PASSWORD", "")
    if not email or not password:
        print("ERROR: Set FURMAN_EMAIL and FURMAN_PASSWORD in your .env file.")
        sys.exit(1)
    return email, password


def _wait_for_user(page: Page, description: str):
    """Pause and ask the user to complete a step in the browser."""
    print(f"\n>>> ACTION REQUIRED: {description}")
    print(">>>   Complete the step in the browser window, then press ENTER here...")
    input()


def _is_logged_in(page: Page) -> bool:
    """Check if we've landed on an authenticated Engage page."""
    # After login, the URL won't contain 'login.microsoftonline' or 'logon'
    url = page.url.lower()
    if "login.microsoftonline.com" in url:
        return False
    if "/account/logon" in url:
        return False
    # Check for a sign of authenticated state on the Engage page
    if "furman.campuslabs.com/engage" in url:
        return True
    return False


def _do_microsoft_login(page: Page, email: str, password: str):
    """Walk through the Microsoft SSO flow, pausing for MFA."""

    # --- Step 1: Enter email ---
    print("  Entering email...")
    email_input = page.wait_for_selector(
        'input[type="email"], input[name="loginfmt"]', timeout=15_000
    )
    email_input.fill(email)
    page.click('input[type="submit"], button[type="submit"]')

    # --- Step 2: Enter password ---
    print("  Waiting for password field...")
    try:
        password_input = page.wait_for_selector(
            'input[type="password"], input[name="passwd"]', timeout=15_000
        )
        password_input.fill(password)
        page.click('input[type="submit"], button[type="submit"]')
    except Exception:
        # Some orgs redirect to a different password page
        _wait_for_user(page, "Please enter your password in the browser.")

    # --- Step 3: Handle whatever comes next ---
    # Give the page a moment to transition
    page.wait_for_timeout(3000)

    # Loop until we're either logged in or stuck
    for _ in range(10):
        if _is_logged_in(page):
            print("  Login successful!")
            return

        url = page.url.lower()
        content = page.content().lower()

        # Duo MFA iframe or prompt
        if "duo" in content or "duosecurity" in url or "duo_iframe" in content:
            _wait_for_user(
                page, "Duo MFA detected — please approve the push or enter the code."
            )
        # Microsoft MFA (Authenticator app)
        elif "enterproof" in content or "verificationcode" in content or "approve" in content:
            _wait_for_user(
                page, "Microsoft MFA detected — approve on your Authenticator app or enter the code."
            )
        # "Stay signed in?" prompt
        elif "stay signed in" in content or "kmsi" in content:
            print("  Clicking 'Yes' on 'Stay signed in?'...")
            try:
                page.click('input[type="submit"]#idSIButton9', timeout=5000)
            except Exception:
                try:
                    page.click('button:has-text("Yes")', timeout=3000)
                except Exception:
                    _wait_for_user(page, "'Stay signed in?' prompt — please click Yes.")
        # "Additional security verification" or other unknown page
        else:
            _wait_for_user(
                page,
                f"Unexpected page — please complete whatever is shown in the browser.\n"
                f"    Current URL: {page.url}",
            )

        page.wait_for_timeout(2000)

    if not _is_logged_in(page):
        _wait_for_user(page, "Login doesn't seem complete. Please finish logging in.")


def login(headless: bool = False) -> BrowserContext:
    """Log in to Furman Engage and return an authenticated browser context.

    The session is saved to disk so future calls reuse the cookies.
    Set headless=False (default) so you can see the browser and interact
    with MFA prompts.
    """
    email, password = _load_credentials()

    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=headless)

    # Try to reuse an existing session
    if SESSION_DIR.exists():
        print("Reusing saved session...")
        context = browser.new_context(storage_state=str(SESSION_DIR / "state.json"))
        page = context.new_page()
        page.goto(ENGAGE_HOME, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_timeout(3000)

        if _is_logged_in(page):
            print("Session still valid!")
            return context
        else:
            print("Saved session expired, logging in fresh...")
            context.close()

    # Fresh login
    context = browser.new_context()
    page = context.new_page()

    print(f"Navigating to login: {LOGIN_TRIGGER}")
    page.goto(LOGIN_TRIGGER, wait_until="domcontentloaded", timeout=30_000)
    page.wait_for_timeout(2000)

    # If we got redirected to Microsoft login, do the flow
    if "login.microsoftonline.com" in page.url:
        _do_microsoft_login(page, email, password)
    elif not _is_logged_in(page):
        _wait_for_user(page, "Please complete the login in the browser.")

    # Wait until we're back on Engage
    page.wait_for_url("**/engage/**", timeout=MFA_TIMEOUT_MS)
    print("Authenticated successfully!")

    # Save session for next time
    SESSION_DIR.mkdir(exist_ok=True)
    context.storage_state(path=str(SESSION_DIR / "state.json"))
    print(f"Session saved to {SESSION_DIR}/")

    return context


def get_authenticated_cookies() -> dict[str, str]:
    """Convenience: log in and return cookies as a dict for use with httpx."""
    context = login()
    cookies = context.cookies()
    cookie_dict = {c["name"]: c["value"] for c in cookies}
    context.close()
    return cookie_dict


if __name__ == "__main__":
    # Quick test: log in and print cookies
    from dotenv import load_dotenv
    load_dotenv()

    cookies = get_authenticated_cookies()
    print(f"\nGot {len(cookies)} cookies:")
    for name in sorted(cookies):
        print(f"  {name}")
