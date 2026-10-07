# Solar-Quote on the existing Supabase project

These functions are prepared locally. They have not been deployed, and no
Google credentials, signing key or active mobile backend URL are included.
The existing Supabase project can host them alongside its DeyeTrack/Studio
functions. These files do not modify those projects, their tables or their
authentication configuration.

The planned public verification endpoint is:

`https://mkskyictzxcfmqybocgv.supabase.co/functions/v1/solarquote-play-verify`

The authenticated notification endpoint is:

`https://mkskyictzxcfmqybocgv.supabase.co/functions/v1/solarquote-play-rtdn`

`solarquote-play-verify` accepts `POST application/json` with only
`purchase_token` and `nonce`. It exchanges a server-held Google service-account
JWT for an Android Publisher OAuth access token, calls `subscriptionsv2.get`
for the fixed package `org.solarclientfinder.solarclientfinder`, and checks only
`solarquote_pro_monthly` and `solarquote_pro_yearly`. Active, grace-period and
canceled subscriptions keep access only while an allowed line item has a future
expiry. Pending, paused, on-hold and expired subscriptions return signed inactive
entitlements. A purchased active subscription is acknowledged before an active
entitlement is returned. Notification event types never grant access on their own;
the latest Google response determines the state. This follows Google's
[subscription state definitions](https://developers.google.com/android-publisher/api-ref/rest/v3/purchases.subscriptionsv2)
and [acknowledgement API](https://developers.google.com/android-publisher/api-ref/rest/v3/purchases.subscriptions/acknowledge).

The returned JSON contains `entitlement`, in the existing Python app's two-part
`base64url(payload).base64url(signature)` format. The signature is RSA PKCS#1 v1.5
with SHA-256. Its payload binds the fixed package, lowercase SHA-256 digest of
the exact purchase token, exact request nonce and integer issue/expiry times.
Access expires at the subscription expiry or seven days after issue, whichever
is earlier; signed inactive responses last one minute. This is an entitlement
assertion to the token holder, without an in-app user identity or login. No
project, contact, report or location data is accepted. Subscription details and
purchase tokens are not stored; only Google OAuth access tokens and public
OIDC keys are cached within an isolate.

## Required server configuration

Store these values in Supabase secrets, never in this repository or the APK:

| Secret | Value |
| --- | --- |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | The complete Google service-account JSON, with its PKCS#8 `private_key`, `client_email` and optional `private_key_id`. |
| `ENTITLEMENT_PRIVATE_KEY_PEM` | A separate RSA private signing key, PKCS#8 `BEGIN PRIVATE KEY`, at least 2048 bits, exponent 65537. Actual newlines or escaped `\n` are supported. |
| `RTDN_AUDIENCE` | Exact notification endpoint URL/audience configured in the Pub/Sub push subscription. |
| `RTDN_SERVICE_ACCOUNT_EMAIL` | Exact service-account email authorized to send authenticated Pub/Sub push notifications. |

Enable the Android Publisher API in the Google Cloud project and grant the
Google service account the necessary subscription/order permissions for this
app in Play Console. A Supabase API key is not a Google Play credential. The
Firebase push settings in the neighboring Studio project do not supply these
Play permissions. The OAuth token URL and Publisher hosts are fixed in code;
credential JSON cannot redirect requests to an arbitrary host. See Google's
[service-account OAuth guide](https://developers.google.com/identity/protocols/oauth2/service-account)
and [Play API setup](https://developers.google.com/android-publisher/getting_started).

Use the existing Python helper to create the entitlement signing key locally:

```bash
python -m backend.generate_key /private/solarquote-entitlement-signing.pem
```

It prints the public modulus/exponent constants for `billing_config.py`. Keep
the private key outside the workspace, and pin only that public key in the app.
A changed public key requires an app update and a deliberate key migration.
Do not enable `BACKEND_URL` until the function is deployed and a real Play test
purchase produces a response the app verifies with the pinned public key.

## Local checks

From `backend/supabase`, with Deno installed:

```bash
deno task check
deno task lint
deno task test
```

There are no npm/JSR dependencies. Tests create ephemeral RSA keys and mocked
Google requests; they require no network, environment or filesystem permissions.
The tests were run using Deno 2.9.6. For the optional Python interoperability
fixture, run `deno run --allow-write=/private/dummy-contract.json
tests/contract_fixture.ts /private/dummy-contract.json`, then verify that file's
dummy entitlement using `billing_entitlements.verify_entitlement`. Delete it
afterward. Its private test key is never written or printed.

To serve the functions through the Supabase CLI locally, from the repository
root, use an absolute private secrets-file path:

```bash
supabase --workdir backend functions serve --no-verify-jwt --env-file /private/solarquote.env
```

This requires the CLI's local Docker runtime. Keep the secrets file outside the
repository. Use JSON escaped newlines for a one-line service-account JSON; use
escaped `\n` in the signing PEM if the environment-file format cannot represent
multiline values.

## Deployment steps for the existing project

The following commands are instructions for a later authorized deployment;
they have not been run. From the repository root:

```bash
supabase --workdir backend link --project-ref mkskyictzxcfmqybocgv
supabase --workdir backend secrets set --env-file /private/solarquote.env
supabase --workdir backend functions deploy solarquote-play-verify --project-ref mkskyictzxcfmqybocgv --no-verify-jwt
supabase --workdir backend functions deploy solarquote-play-rtdn --project-ref mkskyictzxcfmqybocgv --no-verify-jwt
```

Deploy only these named functions. No database migration or replacement of any
existing function is required. Because Edge secrets are shared within a project,
deploy only code trusted to access those secrets. Confirm compatibility with the
hosted Supabase Edge Runtime through local CLI serving before deploying.

Both functions use `verify_jwt = false` in `config.toml`. The mobile app does
not have a Supabase user JWT: its verification endpoint relies on the fixed
Google Play purchase-token verification gate before signing any entitlement.
The notification endpoint rejects requests unless their Google-signed OIDC JWT
has a valid RS256 signature, allowed Google issuer, future expiry, configured
audience, exact configured service-account email and `email_verified = true`.
It uses Google's fixed public JWKS endpoint with bounded key caching and rotation
refresh. It does not accept a Supabase anon key as notification authentication.
This matches the [Supabase function configuration](https://supabase.com/docs/guides/functions/function-configuration),
[Google OIDC validation](https://developers.google.com/identity/openid-connect/openid-connect)
and [authenticated Pub/Sub push requirements](https://cloud.google.com/pubsub/docs/authenticate-push-subscriptions).

Configure Play's RTDN Pub/Sub topic and an authenticated push subscription with
the notification endpoint, the exact audience above and the chosen push service
account. Ensure the Pub/Sub service agent can mint OIDC tokens for that account
and the principal creating the subscription can act as it, following Google's
linked guide. Authenticated Play test notifications return 200. Subscription
and subscription-void notifications requery Google and acknowledge eligible
pending purchases. Network, permission and transient Google errors return 503,
so Pub/Sub can retry; permanently invalid/old 400/404/410 tokens are acknowledged
without granting access. This avoids endlessly retrying unusable tokens.

## Production limits and verification

The public endpoint accepts at most 16 KiB per request, purchase tokens of
8–4096 characters and nonces of 20–128 URL-safe characters. Request bodies and
upstream responses have size/deadline limits; upstream calls time out after
eight seconds and cannot follow redirects. It never logs request bodies,
purchase-token URLs, credentials, exception text or signed entitlements.
Responses use `Cache-Control: no-store` and generic error codes.

The isolate-local guard limits a token digest to 30 requests per minute and an
isolate to 200 per minute; its memory is bounded. This is a useful safeguard,
and it cannot provide a global quota across concurrent Supabase isolates. Before
public rollout, add a distributed rate limit through a trusted gateway or
atomic shared KV/database counters, with separate endpoint-wide and per-token
quotas and trusted ingress IP/account limits. Set Google API quotas and billing
alerts. Do not use client-supplied forwarding headers as an authenticated
identity. Add Play Integrity or authenticated app/user binding if the production
threat model requires restricting who can present a valid purchase token.

Test a licensed Play installation through real purchase, trial eligibility,
acknowledgement, cancellation before expiry, expiry, grace, account hold and
restore. Test an authenticated Pub/Sub setup message and ensure forged or wrong
audience/email notifications fail. Network-failure tests should preserve an
existing app cache without extending its lifetime; a verified inactive response
should revoke access. These local tests do not replace Play/Supabase integration
testing with real credentials.

RTDN currently revalidates without a persistent entitlement store or device
delivery channel, matching the Python service. It does not instantly invalidate
a device's previously issued offline entitlement. The app reconciles on
foreground/restore, and offline access ends at the signed expiry. If immediate
cross-device revocation is required, add a token-digest state store and a device
reconciliation/delivery mechanism before promising that behavior.
