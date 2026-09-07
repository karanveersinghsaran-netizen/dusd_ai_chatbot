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
- `Max-Age=2592000` (30d) — intentionally matched to `CONV_TTL_SECONDS` in `redis_store.py`, so
  the cookie never outlives the Redis conversation state it points to. A cookie surviving past
  its Redis data would just resume as an empty conversation under the same session id — harmless,
  but keeping them in lockstep avoids the question entirely. Reissued (re-signed, same
  `session_id`, expiry pushed out again) on every `/chat`, `/feedback/thanks`, and
  `/feedback/report` request — see `app/security/identity.py` — so an active user's cookie
  effectively never expires; only 30 days of total inactivity clears it (#51).

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
Since #51, this same token also carries a stable `user_id` claim and is forwarded by
`chatbox.html` into `/chat`, `/feedback/thanks`, and `/feedback/report`, so it doubles as a
portable identity — see "Identity resolution (#51)" below.

## Format

`token` is `{expires_at_unix}.{user_id}.{signature}`:
- `expires_at_unix` — plaintext unix timestamp the token stops being valid at. Not sensitive:
  knowing when a link expires reveals nothing exploitable.
- `user_id` — `secrets.token_urlsafe(16)` by default (auto-generated at mint time, unless the
  caller passes an explicit one to reissue a link for an existing identity), never contains `.`.
- `signature` — `hmac_sha256(CHATBOX_TOKEN_SIGNING_KEY, f"{expires_at_unix}.{user_id}")`, hex-encoded.

Implemented in `app/security/chatbox_token.py` (`issue_chatbox_token`, `verify_chatbox_token`,
`decode_chatbox_token`), same stdlib-only approach as the session cookie above. Deliberately keyed
by a **separate** signing key from `SESSION_SIGNING_KEY`, so rotating chatbox-demo access doesn't
invalidate live chat sessions and vice versa.

Unlike before #51, the token now **is** an identity: whoever holds the link shares whatever
Redis history that `user_id` accumulates. Acceptable during the preview-link phase, since each
admin gets their own link (`scripts/generate_chatbox_token.py`); proper auth is out of scope until
distribution widens.

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

# Identity resolution (#51)

`POST /chat`, `/feedback/thanks`, and `/feedback/report` all key their Redis state (conversation
history, feedback flags) off a single identifier resolved by `resolve_user_id()` in
`app/security/identity.py` — the one place this decision is made, so future endpoints (#72 "clear
conversation", #73 "restore chat history") stay consistent with it instead of re-deriving it.

Resolution order, per request:
1. If a `token` query param is present and decodes to a non-expired, correctly-signed payload
   (`decode_chatbox_token`), its `user_id` claim wins.
2. Otherwise, fall back to the `wms_session` cookie: reused if validly signed, minted fresh if
   absent. A cookie that's present but fails verification still returns `401` — *unless* a valid
   token already resolved identity in step 1, in which case the bad cookie is silently replaced
   instead of blocking the request, since the token is already sufficient proof of identity.

Why: a `wms_session` cookie is scoped to a single cookie jar. iOS Safari's ITP can clear it, and
installing the chatbox as a home-screen PWA gives the standalone WebView its own cookie jar,
isolated from the Safari tab it was installed from — so the same person ends up with two different
`session_id`s (two "different" conversations) for what is, to them, the same chat. The chatbox
token doesn't have this problem: it's baked into the `/chatbox` URL itself and forwarded into the
installed PWA's manifest `start_url` (see `main.py`'s `/manifest.webmanifest`), so a Safari tab and
an installed PWA opened from the *same* link carry the *same* token and resolve to the *same*
`user_id`, regardless of cookie-jar isolation.

The plain iframe embed (`embed/wms-chatbot.js`, `docs/embed.md`) never carries a token, so it's
unaffected by any of this — it keeps resolving identity from the cookie alone, exactly as before.
