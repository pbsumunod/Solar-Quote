import { createVerifyHandler, IsolateLimiter } from "../functions/_shared/http.ts";
import {
  BillingService,
  decode,
  decodeJson,
  digest,
  GOOGLE_OAUTH_URL,
  GOOGLE_SCOPE,
  GooglePlay,
  importPrivateKey,
  MAX_LIFETIME,
  PACKAGE,
  readJson,
  signEntitlement,
  subscriptionStatus,
  Unavailable,
  UpstreamError,
  validateVerify,
} from "../functions/_shared/play.ts";
import {
  assert,
  env,
  equal,
  jsonRequest,
  nonce,
  now,
  pem,
  rejects,
  rsa,
  subscription,
  token,
} from "./helpers.ts";

Deno.test("entitlements use the Python two-part RSA/token/nonce contract", async () => {
  const result = await signEntitlement(rsa.privateKey, subscription(), token, nonce, now);
  const [payload, signature] = result.split(".");
  equal(decodeJson(payload), {
    active: true,
    aud: PACKAGE,
    exp: now + MAX_LIFETIME,
    iat: now,
    nonce,
    purchase_token_hash: await digest(token),
  });
  assert(
    await crypto.subtle.verify(
      "RSASSA-PKCS1-v1_5",
      rsa.publicKey,
      new Uint8Array(decode(signature)),
      new Uint8Array(decode(payload)),
    ),
  );
  assert(
    !await crypto.subtle.verify(
      "RSASSA-PKCS1-v1_5",
      rsa.publicKey,
      new Uint8Array(decode(signature)),
      new TextEncoder().encode("tampered"),
    ),
  );
});

Deno.test("canceled and grace retain access only until expiry; suspended and pending do not", () => {
  for (const state of ["ACTIVE", "IN_GRACE_PERIOD", "CANCELED"]) {
    assert(subscriptionStatus(subscription(`SUBSCRIPTION_STATE_${state}`, 10), now).active);
    assert(!subscriptionStatus(subscription(`SUBSCRIPTION_STATE_${state}`, 0), now).active);
  }
  for (const state of ["PENDING", "PAUSED", "ON_HOLD", "EXPIRED", "PENDING_PURCHASE_CANCELED"]) {
    assert(!subscriptionStatus(subscription(`SUBSCRIPTION_STATE_${state}`, 1000), now).active);
  }
});

Deno.test("expiry cap and allowlist produce explicit one-minute inactive responses", async () => {
  const short = await signEntitlement(
    rsa.privateKey,
    subscription("SUBSCRIPTION_STATE_CANCELED", 17),
    token,
    nonce,
    now,
  );
  equal(decodeJson(short.split(".")[0]).exp, now + 17);
  const wrong = subscription();
  wrong.lineItems[0].productId = "other_app_subscription";
  const inactive = decodeJson(
    (await signEntitlement(rsa.privateKey, wrong, token, nonce, now)).split(".")[0],
  );
  equal(inactive.active, false);
  equal(inactive.exp, now + 60);
  wrong.lineItems[0].productId = "solarquote_pro_monthly";
  wrong.lineItems[0].expiryTime = "2027-01-01T00:00:00";
  assert(!subscriptionStatus(wrong, now).active, "Expiry must have an explicit UTC offset");
});

Deno.test("pending acknowledgement completes before granting; failures never sign active", async () => {
  const purchase = subscription();
  purchase.acknowledgementState = "ACKNOWLEDGEMENT_STATE_PENDING";
  const calls: string[] = [];
  const service = new BillingService(env, {
    fetchSubscription: () => {
      calls.push("get");
      return Promise.resolve(purchase);
    },
    acknowledge: (product, received) => {
      equal(product, "solarquote_pro_monthly");
      equal(received, token);
      calls.push("ack");
      return Promise.resolve();
    },
  }, () => now);
  assert(decodeJson((await service.verify(token, nonce)).split(".")[0]).active);
  equal(calls, ["get", "ack"]);
  const failing = new BillingService(env, {
    fetchSubscription: () => Promise.resolve(purchase),
    acknowledge: () => Promise.reject(new UpstreamError(503)),
  }, () => now);
  equal(
    (await createVerifyHandler(failing)(jsonRequest({ purchase_token: token, nonce }))).status,
    503,
  );
});

Deno.test("missing or unknown acknowledgement states cannot bypass acknowledgement", async () => {
  for (const acknowledgementState of [undefined, "unknown", "ACKNOWLEDGEMENT_STATE_UNSPECIFIED"]) {
    const purchase = { ...subscription(), acknowledgementState };
    const service = new BillingService(env, {
      fetchSubscription: () => Promise.resolve(purchase),
      acknowledge: () => {
        throw new Error("Malformed responses must not be acknowledged");
      },
    }, () => now);
    equal(
      (await createVerifyHandler(service)(jsonRequest({ purchase_token: token, nonce }))).status,
      503,
    );
  }
});

Deno.test("acknowledgement conflict is accepted only after authoritative acknowledged re-fetch", async () => {
  const pending = subscription();
  pending.acknowledgementState = "ACKNOWLEDGEMENT_STATE_PENDING";
  let reads = 0;
  const service = new BillingService(env, {
    fetchSubscription: () => Promise.resolve(++reads === 1 ? pending : subscription()),
    acknowledge: () => Promise.reject(new UpstreamError(409)),
  }, () => now);
  assert(decodeJson((await service.verify(token, nonce)).split(".")[0]).active);
  equal(reads, 2);
  const failed = new BillingService(env, {
    fetchSubscription: () => Promise.resolve(pending),
    acknowledge: () => Promise.reject(new UpstreamError(409)),
  }, () => now);
  await rejects(() => failed.verify(token, nonce));
});

Deno.test("Google OAuth JWT scope/key and encoded Play paths are fixed and cached", async () => {
  let exchanges = 0;
  let gets = 0;
  let acks = 0;
  const trickyToken = "test-token/slash?query#fragment";
  const play = new GooglePlay(env, async (url, init) => {
    const target = String(url);
    if (target === GOOGLE_OAUTH_URL) {
      exchanges++;
      const body = new URLSearchParams(String(init?.body));
      equal(body.get("grant_type"), "urn:ietf:params:oauth:grant-type:jwt-bearer");
      const parts = body.get("assertion")!.split(".");
      equal(decodeJson(parts[1]), {
        iss: "play-test@example.iam.gserviceaccount.com",
        scope: GOOGLE_SCOPE,
        aud: GOOGLE_OAUTH_URL,
        iat: now,
        exp: now + 3600,
      });
      assert(
        await crypto.subtle.verify(
          "RSASSA-PKCS1-v1_5",
          rsa.publicKey,
          new Uint8Array(decode(parts[2])),
          new TextEncoder().encode(`${parts[0]}.${parts[1]}`),
        ),
      );
      return Response.json({
        access_token: "test-access-token",
        expires_in: 3600,
        token_type: "Bearer",
      });
    }
    equal(new Headers(init?.headers).get("authorization"), "Bearer test-access-token");
    assert(
      target.startsWith(
        `https://androidpublisher.googleapis.com/androidpublisher/v3/applications/${PACKAGE}/`,
      ),
    );
    assert(target.includes(encodeURIComponent(trickyToken)));
    assert(init?.signal instanceof AbortSignal);
    equal(init?.redirect, "error");
    if (target.endsWith(":acknowledge")) {
      acks++;
      equal(init?.method, "POST");
      return new Response(null, { status: 204 });
    }
    gets++;
    return Response.json(subscription());
  }, () => now);
  await Promise.all([play.fetchSubscription(trickyToken), play.fetchSubscription(trickyToken)]);
  await play.acknowledge("solarquote_pro_monthly", trickyToken);
  equal([exchanges, gets, acks], [1, 2, 1]);
  await rejects(() => play.acknowledge("other_product", token));
});

Deno.test("malformed or redirecting credential configuration fails closed without network", async () => {
  let network = 0;
  for (
    const raw of [
      "[]",
      "{",
      JSON.stringify({
        type: "service_account",
        client_email: "play-test@example.iam.gserviceaccount.com",
        private_key: pem,
        token_uri: "https://attacker.example/token",
      }),
    ]
  ) {
    const play = new GooglePlay(
      (name) => name === "GOOGLE_SERVICE_ACCOUNT_JSON" ? raw : env(name),
      () => {
        network++;
        return Promise.reject(new Error());
      },
      () => now,
    );
    const service = new BillingService(env, play, () => now);
    equal(
      (await createVerifyHandler(service)(jsonRequest({ purchase_token: token, nonce }))).status,
      503,
    );
  }
  equal(network, 0);
  await rejects(() => importPrivateKey("not a PKCS8 key"));
});

Deno.test("verify rejects malformed requests, bounds chunked bodies and exposes no exception text", async () => {
  const service = { verify: () => Promise.reject(new Error(`private token ${token}`)) };
  const handler = createVerifyHandler(service);
  equal((await handler(jsonRequest({ purchase_token: token, nonce: "short" }))).status, 400);
  equal(
    (await handler(jsonRequest({ purchase_token: token, nonce, client_name: "PII" }))).status,
    400,
  );
  equal((await handler(new Request("https://example.test", { method: "GET" }))).status, 405);
  const failure = await handler(jsonRequest({ purchase_token: token, nonce }));
  equal(failure.status, 503);
  equal(await failure.json(), { error: "verification_unavailable" });
  const over = new Request("https://example.test", { method: "POST", body: " ".repeat(20000) });
  await rejects(() => readJson(over));
  await rejects(() => Promise.resolve(validateVerify({ purchase_token: "with space", nonce })));
});

Deno.test("rate limiter bounds per-token and isolate work and recovers next window", () => {
  let current = now;
  const limiter = new IsolateLimiter(() => current);
  for (let i = 0; i < 30; i++) assert(limiter.allow("token-digest"));
  assert(!limiter.allow("token-digest"));
  for (let i = 0; i < 169; i++) assert(limiter.allow(`different-${i}`));
  assert(!limiter.allow("one-too-many"));
  current += 61;
  assert(limiter.allow("token-digest"));
});

Deno.test("Google permanent purchase errors reject requests while outages stay unavailable", async () => {
  for (
    const [upstream, expected] of [[404, 400], [410, 400], [401, 503], [403, 503], [429, 503], [
      500,
      503,
    ]]
  ) {
    const handler = createVerifyHandler({
      verify: () => Promise.reject(new UpstreamError(upstream)),
    });
    equal((await handler(jsonRequest({ purchase_token: token, nonce }))).status, expected);
  }
  const handler = createVerifyHandler({ verify: () => Promise.reject(new Unavailable("secret")) });
  equal((await handler(jsonRequest({ purchase_token: token, nonce }))).status, 503);
});
