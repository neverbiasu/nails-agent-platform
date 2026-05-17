"""
Instagram instaloader login → saves session to ~/.config/instaloader/session-USERNAME

Usage:
    uv run python scripts/ig_login.py --username YOUR_IG_USERNAME

After running, InstagramFetcher picks up the session automatically (no extra config).
Set INSTAGRAM_USERNAME=<username> in .env so signal_collector knows which file to load.
"""

from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", required=True, help="Instagram username")
    args = parser.parse_args()

    try:
        import instaloader
    except ImportError:
        print("ERROR: instaloader not installed. Run: pip install instaloader")
        raise SystemExit(1)

    L = instaloader.Instaloader()
    print(f"Logging in as {args.username} …")
    print("You will be prompted for your password.")
    try:
        L.interactive_login(args.username)
    except instaloader.exceptions.BadCredentialsException:
        print("ERROR: wrong username or password")
        raise SystemExit(1)
    except instaloader.exceptions.TwoFactorAuthRequiredException:
        code = input("Two-factor code: ").strip()
        L.two_factor_login(code)

    # Save session to standard instaloader path:
    # ~/.config/instaloader/session-USERNAME
    L.save_session_to_file()
    from instaloader.instaloader import get_default_session_filename
    path = get_default_session_filename(args.username)
    print(f"\nSession saved to: {path}")
    print(f"Add to .env:  INSTAGRAM_USERNAME={args.username}")
    print("Signal collector will auto-detect this session on next run.")


if __name__ == "__main__":
    main()
