# Optional purchase-verification service

This service is prepared for local execution and deployment configuration. It
has not been deployed and does not include Google credentials or a signing key.
The Android app defaults to client-only Play verification until configured.
Only a Play purchase token and random response nonce reach this service; client
names, locations, contacts, projects and reports remain on the device.

For the existing Supabase platform, see the locally prepared
[Supabase Edge Functions adapter](supabase/README.md). It uses the same mobile
signed-entitlement contract and has not been deployed or activated.

Use Python 3.11+, install `pip install -r backend/requirements.txt`, then run:

```bash
python -m backend.generate_key /private/entitlement-signing.pem
export ENTITLEMENT_PRIVATE_KEY_PATH=/private/entitlement-signing.pem
export GOOGLE_APPLICATION_CREDENTIALS=/private/google-service-account.json
export PLAY_PACKAGE_NAME=org.solarclientfinder.solarclientfinder
python -m backend.server
```

Grant the service account the required subscription/order permissions in Play
Console and enable the Android Publisher API. Keep both private files outside
the repository and APK. The key command prints public constants to copy into
`billing_config.py`; configure its `BACKEND_URL` with the deployed HTTPS URL.
Changing the pinned public key requires an app update; retain the old service
key during a migration. Signed responses bind the package, purchase-token
digest and request nonce. Their lifetime ends at subscription expiry or seven
days, whichever comes first. An inactive response lasts one minute.

For deployment, use `gunicorn 'backend.server:create_app()'` behind HTTPS with
body-size limits, request timeouts and shared rate limiting. The included
in-process limit is a development safeguard, not a distributed rate limiter.
Never log request bodies or Google request URLs: purchase tokens are sensitive
bearer credentials. Token-only verification authenticates entitlement to the
holder of the token, not an in-app user identity. Add Play Integrity or app
authentication if the production threat model requires it.

Configure authenticated Pub/Sub push to `/notifications` with
`RTDN_AUDIENCE` equal to that endpoint's exact audience and
`RTDN_SERVICE_ACCOUNT_EMAIL` equal to the authorized push service account.
Google's JWT issuer, signature, expiry and audience are verified; the email
must match. Google credentials, private key and these environment settings are
required. Notification failures return 503 so Pub/Sub can redeliver. Successful
notifications reverify and acknowledge purchases. This token-only service does
not push entitlement changes to devices: the app reconciles on foreground/restore
and uses a bounded cached entitlement offline. If immediate cross-device
revocation is needed, add a token-digest entitlement store and delivery channel.

Client-only verification remains a weaker security mode and is explicitly
bounded to seven days after a successful Play query. Legacy purchased tiers
receive one persisted seven-day migration grace period, never refreshed by a
query failure. Device clock rollback is constrained by a persisted watermark
and elapsed-time anchors but cannot be made tamper-proof in an offline app on
a modified device. Play-managed trials are always purchased through Play;
desktop local trials are development-only.

References: [purchase verification](https://developer.android.com/google/play/billing/security),
[subscription lifecycle](https://developer.android.com/google/play/billing/lifecycle/subscriptions),
[authenticated Pub/Sub push](https://cloud.google.com/pubsub/docs/authenticate-push-subscriptions).
