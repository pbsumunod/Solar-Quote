import { createRtdnHandler } from "../functions/_shared/http.ts";
import { GOOGLE_JWKS_URL, GooglePushIdentity } from "../functions/_shared/oidc.ts";
import {
  decode,
  PACKAGE,
  signJwt,
  Unauthorized,
  UpstreamError,
} from "../functions/_shared/play.ts";
import { assert, env, equal, jsonRequest, now, rejects, rsa, token } from "./helpers.ts";

function claims() {
  return {
    iss: "https://accounts.google.com",
    aud: env("RTDN_AUDIENCE"),
    email: env("RTDN_SERVICE_ACCOUNT_EMAIL"),
    email_verified: true,
    sub: "1234567890123",
    iat: now,
    exp: now + 3600,
  };
}
const jwk = {
  ...await crypto.subtle.exportKey("jwk", rsa.publicKey),
  alg: "RS256",
  use: "sig",
  kid: "google-test-key",
};

Deno.test("Google push validates RSA/JWKS signature and caches rotation keys", async () => {
  let fetches = 0;
  const identity = new GooglePushIdentity(env, (url) => {
    equal(String(url), GOOGLE_JWKS_URL);
    fetches++;
    return Promise.resolve(
      Response.json({ keys: [jwk] }, { headers: { "cache-control": "public, max-age=3600" } }),
    );
  }, () => now);
  const jwt = await signJwt(rsa.privateKey, claims(), "google-test-key");
  await identity.verify(jwt);
  await identity.verify(jwt);
  equal(fetches, 1);
  const parts = jwt.split(".");
  const signature = decode(parts[2]);
  signature[0] ^= 1;
  const broken = btoa(String.fromCharCode(...signature)).replaceAll("+", "-").replaceAll("/", "_")
    .replace(/=+$/, "");
  await rejects(() => identity.verify(`${parts[0]}.${parts[1]}.${broken}`));
});

Deno.test("Google push rejects wrong audience/email/issuer/expiry and unverified email before network", async () => {
  let fetches = 0;
  const identity = new GooglePushIdentity(env, () => {
    fetches++;
    return Promise.reject(new Error());
  }, () => now);
  for (
    const override of [
      { aud: "https://other.example" },
      { email: "intruder@example.com" },
      { iss: "https://attacker.example" },
      { email_verified: false },
      { exp: now },
      { iat: now + 301 },
      { sub: "" },
      { exp: "9999999999" },
    ]
  ) {
    await rejects(async () =>
      identity.verify(
        await signJwt(rsa.privateKey, { ...claims(), ...override }, "google-test-key"),
      )
    );
  }
  equal(fetches, 0);
});

Deno.test("JWKS key rotation refreshes safely after cooldown and transient failure stays retryable", async () => {
  let current = now;
  let fetches = 0;
  const identity = new GooglePushIdentity(env, () => {
    fetches++;
    return Promise.resolve(
      Response.json({ keys: [{ ...jwk, kid: fetches === 1 ? "old-key" : "new-key" }] }, {
        headers: { "cache-control": "max-age=3600" },
      }),
    );
  }, () => current);
  await identity.verify(await signJwt(rsa.privateKey, claims(), "old-key"));
  await rejects(async () => identity.verify(await signJwt(rsa.privateKey, claims(), "new-key")));
  equal(fetches, 1);
  current += 31;
  await identity.verify(await signJwt(rsa.privateKey, claims(), "new-key"));
  equal(fetches, 2);
  const unavailable = new GooglePushIdentity(
    env,
    () => Promise.resolve(new Response(null, { status: 503 })),
    () => now,
  );
  const handler = createRtdnHandler({ verify: () => Promise.resolve("ignored") }, unavailable);
  equal(
    (await handler(
      jsonRequest(
        envelope({ testNotification: {} }),
        `Bearer ${await signJwt(rsa.privateKey, claims(), "google-test-key")}`,
      ),
    )).status,
    503,
  );
});

function envelope(extra: Record<string, unknown>, packageName = PACKAGE) {
  return {
    message: { data: btoa(JSON.stringify({ packageName, ...extra })), messageId: "test-id" },
  };
}

Deno.test("RTDN authenticates before reading tokens, acknowledges tests, and reverifies actual state", async () => {
  let called = 0;
  const service = {
    verify: (received: string, nonce: string) => {
      equal(received, token);
      equal(nonce, "notification-verification");
      called++;
      return Promise.resolve("discarded");
    },
  };
  const deny = createRtdnHandler(service, { verify: () => Promise.reject(new Unauthorized()) });
  equal(
    (await deny(
      jsonRequest(envelope({ subscriptionNotification: { purchaseToken: token } }), "Bearer fake"),
    )).status,
    401,
  );
  equal(called, 0);
  const handler = createRtdnHandler(service, { verify: () => Promise.resolve() });
  equal(
    (await handler(jsonRequest(envelope({ testNotification: {} }), "Bearer valid-test"))).status,
    200,
  );
  equal(called, 0);
  const result = await handler(
    jsonRequest(
      envelope({ subscriptionNotification: { purchaseToken: token, notificationType: 13 } }),
      "Bearer valid-test",
    ),
  );
  equal(await result.json(), { accepted: true });
  equal(called, 1);
  equal(
    (await handler(
      jsonRequest(envelope({ testNotification: {} }, "other.package"), "Bearer valid-test"),
    )).status,
    400,
  );
  equal(
    (await handler(jsonRequest({ message: { data: "not-base64!" } }, "Bearer valid-test"))).status,
    400,
  );
});

Deno.test("RTDN retries Play outages, acknowledges permanently unavailable tokens and subscription voids", async () => {
  for (const [upstream, expected] of [[404, 200], [410, 200], [403, 503], [429, 503], [500, 503]]) {
    const handler = createRtdnHandler(
      { verify: () => Promise.reject(new UpstreamError(upstream)) },
      { verify: () => Promise.resolve() },
    );
    equal(
      (await handler(
        jsonRequest(
          envelope({ subscriptionNotification: { purchaseToken: token } }),
          "Bearer valid-test",
        ),
      )).status,
      expected,
    );
  }
  let calls = 0;
  const handler = createRtdnHandler({
    verify: () => {
      calls++;
      return Promise.resolve("ignored");
    },
  }, { verify: () => Promise.resolve() });
  equal(
    (await handler(
      jsonRequest(
        envelope({ voidedPurchaseNotification: { purchaseToken: token, productType: 1 } }),
        "Bearer valid-test",
      ),
    )).status,
    200,
  );
  equal(calls, 1);
  equal(
    (await handler(
      jsonRequest(
        envelope({ voidedPurchaseNotification: { purchaseToken: token, productType: 2 } }),
        "Bearer valid-test",
      ),
    )).status,
    200,
  );
  equal(calls, 1);
  assert(true);
});
