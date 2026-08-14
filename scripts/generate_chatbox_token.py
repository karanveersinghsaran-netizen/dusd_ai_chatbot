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
    args = parser.parse_args()

    token = issue_chatbox_token(days_valid=args.days)
    url = f"{args.base_url.rstrip('/')}/chatbox?token={token}"
    print(url)


if __name__ == "__main__":
    main()
