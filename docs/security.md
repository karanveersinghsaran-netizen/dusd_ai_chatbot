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
- `Max-Age=432000` (5d) — intentionally matched to `CONV_TTL_SECONDS` in `redis_store.py`, so
  the cookie never outlives the Redis conversation state it points to. A cookie surviving past
  its Redis data would just resume as an empty conversation under the same session id — harmless,
  but keeping them in lockstep avoids the question entirely. Reissued (re-signed, same
  `session_id`, expiry pushed out again) on every `/chat`, `/feedback/thanks`, and
  `/feedback/report` request — see `app/security/identity.py` — so an active user's cookie
  effectively never expires; only 5 days of total inactivity clears it (#51). Deliberately
  shorter than the issue's original 30d proposal — chosen to bound both the Redis storage/memory
  footprint and how long a shared/public device (a school library computer, a family tablet)
  stays signed in on someone else's behalf, at the cost of losing history a bit sooner for
  genuinely inactive users.

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

**Exception — generic tokens.** `issue_chatbox_token(generic=True)` mints a token with the
reserved `GENERIC_USER_MARKER` sentinel in place of a real `user_id`. It still gates `/chatbox`
and `/manifest.webmanifest` exactly like any other token, but `resolve_user_id()` (below)
recognizes the marker and refuses to treat it as identity, falling back to the requester's own
`wms_session` cookie instead. This is for the opposite distribution shape from a personal link:
one link handed to *many* people at once — e.g. every parent at a school, so each can install it
as their own PWA — where a personal token would incorrectly merge everyone into one shared
identity, one shared daily-cap counter (#71), and one shared conversation. The tradeoff: a
generic link loses the Safari-tab/installed-PWA continuity a personal token provides, since
there's no single identity for it to carry across cookie jars — acceptable here, since mass
distribution and per-person continuity are fundamentally in tension. Minted via
`scripts/generate_chatbox_token.py --generic`.

## Rotation strategy

Unlike the session cookie, this token is *meant* to be rotated routinely — minting a fresh
7-day link is the normal way to (re)grant or extend access, and it's a pure local computation
(`scripts/generate_chatbox_token.py`) against the already-deployed signing key. No redeploy
needed for that path; see the infra repo's `docs/deploy.md` § 6b.

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
1. If a `token` query param is present, decodes to a non-expired, correctly-signed payload
   (`decode_chatbox_token`), *and* its `user_id` isn't the reserved generic marker (see "generic
   tokens" above), that `user_id` claim wins.
2. Otherwise — no token, an invalid/expired one, or a valid *generic* one — fall back to the
   `wms_session` cookie: reused if validly signed, minted fresh if absent. A cookie that's present
   but fails verification still returns `401` — *unless* a valid, non-generic token already
   resolved identity in step 1, in which case the bad cookie is silently replaced instead of
   blocking the request, since the token is already sufficient proof of identity. A generic token
   doesn't get this exception: it proves nothing about *who* this is, only that they're allowed
   in, so a tampered cookie still `401`s exactly as if no token were present.

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
