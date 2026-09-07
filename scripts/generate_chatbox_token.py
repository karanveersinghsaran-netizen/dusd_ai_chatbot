#!/usr/bin/env python3
"""Mint a signed, self-expiring /chatbox access token and print the full
shareable URL. Run locally with CHATBOX_TOKEN_SIGNING_KEY set to the SAME
value stored in Secret Manager for the target environment:

    export CHATBOX_TOKEN_SIGNING_KEY=$(gcloud secrets versions access latest \
        --secret=CHATBOX_TOKEN_SIGNING_KEY --project="$PROJECT_ID")

Usage:
    python -m scripts.generate_chatbox_token \
        --base-url https://wms-chatbot-staging-xxxxx.run.app \
        --days 7

Re-issuing a link for someone whose old token expired: pass --user-id with
the value printed alongside their original link so the new link resolves to
the SAME Redis identity (#51) instead of starting them over with a fresh,
empty conversation.

Minting ONE link to distribute to many people at once (e.g. every parent at
a school, so they can each install it as their own PWA): pass --generic
instead. It still gates access like any other token, but deliberately
carries no personal identity, so each person who opens it gets their own
private conversation from their own device's session cookie rather than
being merged into one shared identity. Mutually exclusive with --user-id.
"""
import argparse

from app.security.chatbox_token import DEFAULT_VALID_DAYS, issue_chatbox_token


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        required=True,
        help="Scheme + host of the target deployment, e.g. https://wms-chatbot-staging-xxxxx.run.app",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_VALID_DAYS,
        help=f"Token validity window in days (default: {DEFAULT_VALID_DAYS}).",
    )
    parser.add_argument(
        "--user-id",
        default=None,
        help=(
            "Reuse this stable user_id instead of generating a new random one "
            "(#51) — pass the user_id printed by a previous run to re-issue a "
            "link for the same person without losing their Redis history."
        ),
    )
    parser.add_argument(
        "--generic",
        action="store_true",
        help=(
            "Mint an access-only link with no personal identity, meant for "
            "mass distribution (e.g. one link for every parent at a school). "
            "Mutually exclusive with --user-id."
        ),
    )
    args = parser.parse_args()

    if args.generic and args.user_id:
        parser.error("--generic and --user-id are mutually exclusive")

    token = issue_chatbox_token(days_valid=args.days, user_id=args.user_id, generic=args.generic)
    url = f"{args.base_url.rstrip('/')}/chatbox?token={token}"
    print(url)
    if args.generic:
        print("generic link — no personal identity embedded; each visitor gets their own from their own cookie")
    else:
        user_id = token.split(".", 2)[1]
        print(f"user_id: {user_id}  (save this to re-issue a link for the same identity later)")


if __name__ == "__main__":
    main()
