# Session cookie security

Covers the `wms_session` cookie issued by `POST /chat`, the web-widget endpoint. Does not apply
to the WhatsApp webhook, which uses Twilio's authenticated `From` phone number as the session
identifier directly and never sets a cookie.

## Format

`wms_session` value is `{session_id}.{signature}`:
- `session_id` — `secrets.token_urlsafe(32)`, 256 bits of randomness.
- `signature` — `hmac_sha256(SESSION_SIGNING_KEY, session_id)`, hex-encoded.

Implemented in `app/security/sessions.py` (`issue_session_id`, `verify_session_id`), stdlib
`hmac`/`hashlib`/`secrets` only — no third-party signing library. The signature stops a client
from forging or guessing another session's id and reading/poisoning their conversation history
in Redis (`app/store/redis_store.py` keys everything off this id). It is not encryption — the
session id itself carries no sensitive data, so there's nothing to hide, only to authenticate.

## Cookie attributes

- `HttpOnly` — not readable by page JavaScript.
- `Secure` — only sent over HTTPS. (Browsers treat `localhost` as a secure context, so this
  still works for local development without a real TLS cert.)
- `SameSite=Lax` — sent on same-site requests, including from the iframe embed once it's served
  from its own subdomain.
- No explicit `domain=` — defaults to the host that served the response.
- No explicit `path=` — defaults to `/`.
- `Max-Age=86400` (24h) — intentionally matched to `CONV_TTL_SECONDS` in `redis_store.py`, so
  the cookie never outlives the Redis conversation state it points to. A cookie surviving past
  its Redis data would just resume as an empty conversation under the same session id — harmless,
  but keeping them in lockstep avoids the question entirely.

## Rotation strategy

None. A fresh session is minted whenever the client presents no cookie, an expired one, or one
that fails signature verification. There's no active rotation of `SESSION_SIGNING_KEY` itself —
rotating it today would invalidate every outstanding session at once (single-key verification).

This is an intentional simplification: the data behind a session (ephemeral school-info chat
history, no PII beyond the conversation text, no authentication of a real identity) isn't
sensitive enough to justify the operational complexity of multi-key verification during a
rotation window. Revisit once Secret Manager (issue #10) lands and `SESSION_SIGNING_KEY` moves
out of a plain env var — that's the natural point to add rotation support.

## Failure handling

A cookie that fails verification (tampered, malformed, signed with an old/wrong key) causes
`POST /chat` to return `401`, not a silent new session. This surfaces forgery attempts and
signing-key mismatches as errors instead of masking them.
