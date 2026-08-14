# Session cookie & access-token security

Covers the `wms_session` cookie issued by `POST /chat`, and the `/chatbox` access token.

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

# `/chatbox` access token

Covers the `token` query-param gate on `GET /chatbox`, used to keep the staging demo from being
publicly loadable before a school is onboarded — e.g. sharing a preview link with a school CTO.

## Format

`token` is `{expires_at_unix}.{signature}`:
- `expires_at_unix` — plaintext unix timestamp the token stops being valid at. Not sensitive:
  knowing when a link expires reveals nothing exploitable.
- `signature` — `hmac_sha256(CHATBOX_TOKEN_SIGNING_KEY, expires_at_unix)`, hex-encoded.

Implemented in `app/security/chatbox_token.py` (`issue_chatbox_token`, `verify_chatbox_token`),
same stdlib-only approach as the session cookie above. Deliberately keyed by a **separate**
signing key from `SESSION_SIGNING_KEY`, so rotating chatbox-demo access doesn't invalidate live
chat sessions and vice versa. Unlike the session id, the token carries no identity — there's
nothing to hand back to the caller on success, only a valid/invalid verdict.

## Rotation strategy

Unlike the session cookie, this token is *meant* to be rotated routinely — minting a fresh
7-day link is the normal way to (re)grant or extend access, and it's a pure local computation
(`scripts/generate_chatbox_token.py`) against the already-deployed signing key. No redeploy
needed for that path; see `docs/deploy.md` § 6b.

Revoking every previously issued link at once (e.g. one leaked) means rotating
`CHATBOX_TOKEN_SIGNING_KEY` itself, which does need a new Cloud Run revision — every outstanding
token immediately fails signature verification. This is coarse, all-or-nothing revocation (no
per-token denylist, no server-side state at all), an acceptable tradeoff given what's gated is a
preview of a staging chatbot UI, not production data.

## Failure handling

Missing, malformed, tampered, or expired tokens all fail identically: `GET /chatbox` returns a
generic `404`, not `403` and not a body with a reason. A `403` would confirm to a prober that the
route exists and is deliberately gated, inviting further guessing; `404` gives no signal that the
route is meaningful at all.
