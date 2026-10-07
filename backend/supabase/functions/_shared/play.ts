/** Fixed Google Play scope and Python-compatible signed entitlement protocol. */
export const PACKAGE = "org.solarclientfinder.solarclientfinder";
export const PRODUCTS = new Set(["solarquote_pro_monthly", "solarquote_pro_yearly"]);
export const MAX_LIFETIME = 604800;
export const GOOGLE_OAUTH_URL = "https://oauth2.googleapis.com/token";
export const GOOGLE_SCOPE = "https://www.googleapis.com/auth/androidpublisher";
const GOOGLE_PLAY_BASE =
  `https://androidpublisher.googleapis.com/androidpublisher/v3/applications/${PACKAGE}`;
const ACTIVE_STATES = new Set([
  "SUBSCRIPTION_STATE_ACTIVE",
  "SUBSCRIPTION_STATE_IN_GRACE_PERIOD",
  "SUBSCRIPTION_STATE_CANCELED",
]);
const KNOWN_STATES = new Set([
  ...ACTIVE_STATES,
  "SUBSCRIPTION_STATE_UNSPECIFIED",
  "SUBSCRIPTION_STATE_PENDING",
  "SUBSCRIPTION_STATE_PAUSED",
  "SUBSCRIPTION_STATE_ON_HOLD",
  "SUBSCRIPTION_STATE_EXPIRED",
  "SUBSCRIPTION_STATE_PENDING_PURCHASE_CANCELED",
]);
const RSA = { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" };
const utf8 = new TextEncoder();
const utf8Decoder = new TextDecoder("utf-8", { fatal: true });

export type JsonObject = Record<string, unknown>;
export type Fetcher = (url: string | URL | Request, init?: RequestInit) => Promise<Response>;
export type Clock = () => number;
export type Environment = (name: string) => string | undefined;
export class InvalidRequest extends Error {}
export class Unauthorized extends Error {}
export class Unavailable extends Error {}
export class UpstreamError extends Unavailable {
  constructor(public readonly status: number) {
    // Never retain upstream URLs, tokens, or response bodies in an exception.
    super("upstream_unavailable");
  }
}

export function object(value: unknown): JsonObject {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new InvalidRequest();
  return value as JsonObject;
}

export function encode(data: Uint8Array): string {
  return btoa(String.fromCharCode(...data)).replaceAll("+", "-").replaceAll("/", "_")
    .replace(/=+$/, "");
}

export function decode(value: string): Uint8Array {
  if (!/^[A-Za-z0-9_-]+$/.test(value) || value.length % 4 === 1) throw new InvalidRequest();
  const binary = atob(
    value.replaceAll("-", "+").replaceAll("_", "/") +
      "=".repeat((4 - value.length % 4) % 4),
  );
  return Uint8Array.from(binary, (c) => c.charCodeAt(0));
}

export function decodeJson(value: string): JsonObject {
  try {
    return object(JSON.parse(utf8Decoder.decode(decode(value))));
  } catch {
    throw new InvalidRequest();
  }
}

export async function digest(value: string): Promise<string> {
  const bytes = new Uint8Array(await crypto.subtle.digest("SHA-256", utf8.encode(value)));
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

export function validateToken(value: unknown): string {
  if (
    typeof value !== "string" || value.length < 8 || value.length > 4096 ||
    /\s/.test(value) || [...value].some((c) => c.charCodeAt(0) < 32 || c.charCodeAt(0) === 127)
  ) {
    throw new InvalidRequest();
  }
  return value;
}

export function validateVerify(value: unknown): { purchase_token: string; nonce: string } {
  const data = object(value);
  if (
    typeof data.nonce !== "string" || !/^[A-Za-z0-9_-]{20,128}$/.test(data.nonce) ||
    Object.keys(data).some((key) => key !== "purchase_token" && key !== "nonce")
  ) {
    throw new InvalidRequest();
  }
  return { purchase_token: validateToken(data.purchase_token), nonce: data.nonce };
}

/** Bounded even when Content-Length is absent or false. The caller owns the deadline. */
export async function readJson(response: Request | Response, maxBytes = 16384): Promise<unknown> {
  const length = response.headers.get("content-length");
  if (length !== null && (!/^\d+$/.test(length) || Number(length) > maxBytes)) {
    await response.body?.cancel();
    throw new InvalidRequest();
  }
  if (!response.body) throw new InvalidRequest();
  const reader = response.body.getReader();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    void reader.cancel().catch(() => {});
  }, 5000);
  let size = 0;
  const chunks: Uint8Array[] = [];
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (timedOut) throw new InvalidRequest();
      if (done) break;
      size += value.byteLength;
      if (size > maxBytes) {
        await reader.cancel();
        throw new InvalidRequest();
      }
      chunks.push(value);
    }
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) {
      bytes.set(chunk, offset);
      offset += chunk.length;
    }
    return JSON.parse(utf8Decoder.decode(bytes));
  } catch {
    throw new InvalidRequest();
  } finally {
    clearTimeout(timer);
    reader.releaseLock();
  }
}

/** Google-only callers supply fixed URLs; no request-supplied host is accepted. */
export async function fetchJson(
  fetcher: Fetcher,
  url: string,
  init: RequestInit = {},
  maxBytes = 131072,
): Promise<{ data: unknown; headers: Headers }> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 8000);
  try {
    const response = await fetcher(url, { ...init, signal: controller.signal, redirect: "error" });
    if (!response.ok) {
      await response.body?.cancel();
      throw new UpstreamError(response.status);
    }
    const data = await readJson(response, maxBytes);
    return { data, headers: response.headers };
  } catch (error) {
    if (error instanceof UpstreamError) throw error;
    throw new Unavailable("upstream_unavailable");
  } finally {
    clearTimeout(timer);
  }
}

export async function importPrivateKey(pem: string): Promise<CryptoKey> {
  try {
    const normal = pem.replaceAll("\\n", "\n").trim();
    if (
      normal.length > 16384 || !normal.startsWith("-----BEGIN PRIVATE KEY-----") ||
      !normal.endsWith("-----END PRIVATE KEY-----")
    ) throw new Unavailable();
    const binary = atob(
      normal.replace("-----BEGIN PRIVATE KEY-----", "")
        .replace("-----END PRIVATE KEY-----", "").replace(/\s/g, ""),
    );
    const key = await crypto.subtle.importKey(
      "pkcs8",
      Uint8Array.from(binary, (c) => c.charCodeAt(0)),
      RSA,
      false,
      ["sign"],
    );
    const algorithm = key.algorithm as RsaHashedKeyAlgorithm;
    if (algorithm.modulusLength < 2048 || algorithm.publicExponent.join(",") !== "1,0,1") {
      throw new Unavailable();
    }
    return key;
  } catch {
    throw new Unavailable("invalid_server_key");
  }
}

export async function signJwt(key: CryptoKey, claims: JsonObject, kid?: string): Promise<string> {
  const header: JsonObject = { alg: "RS256", typ: "JWT" };
  if (kid) header.kid = kid;
  const payload = `${encode(utf8.encode(JSON.stringify(header)))}.${
    encode(utf8.encode(JSON.stringify(claims)))
  }`;
  return `${payload}.${
    encode(new Uint8Array(await crypto.subtle.sign(RSA, key, utf8.encode(payload))))
  }`;
}

export interface EntitlementClaims {
  aud: string;
  iat: number;
  exp: number;
  active: boolean;
  nonce: string;
  purchase_token_hash: string;
}

export function subscriptionStatus(subscription: unknown, now: number): {
  active: boolean;
  expiry: number;
  product: string | undefined;
  acknowledgementPending: boolean;
} {
  const data = object(subscription);
  if (!KNOWN_STATES.has(String(data.subscriptionState)) || !Array.isArray(data.lineItems)) {
    throw new Unavailable("invalid_subscription_response");
  }
  if (
    ![
      "ACKNOWLEDGEMENT_STATE_UNSPECIFIED",
      "ACKNOWLEDGEMENT_STATE_PENDING",
      "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED",
    ].includes(String(data.acknowledgementState))
  ) {
    throw new Unavailable("invalid_acknowledgement_response");
  }
  const items = Array.isArray(data.lineItems) ? data.lineItems.slice(0, 100) : [];
  let expiry = 0;
  let product: string | undefined;
  for (const item of items) {
    if (!item || typeof item !== "object" || Array.isArray(item)) continue;
    const row = item as JsonObject;
    if (
      typeof row.productId !== "string" || !PRODUCTS.has(row.productId) ||
      typeof row.expiryTime !== "string" ||
      !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})$/.test(
        row.expiryTime,
      )
    ) continue;
    const seconds = Math.floor(Date.parse(row.expiryTime) / 1000);
    if (Number.isFinite(seconds) && seconds > expiry) {
      expiry = seconds;
      product = row.productId;
    }
  }
  const active = ACTIVE_STATES.has(String(data.subscriptionState)) && expiry > now;
  if (active && data.acknowledgementState === "ACKNOWLEDGEMENT_STATE_UNSPECIFIED") {
    throw new Unavailable("invalid_acknowledgement_response");
  }
  return {
    active,
    expiry,
    product,
    acknowledgementPending: data.acknowledgementState === "ACKNOWLEDGEMENT_STATE_PENDING",
  };
}

export async function signEntitlement(
  key: CryptoKey,
  subscription: unknown,
  purchaseToken: string,
  nonce: string,
  now: number,
): Promise<string> {
  const status = subscriptionStatus(subscription, now);
  // Ordered exactly like json.dumps(sort_keys=True, separators=(',', ':')) in Python.
  const claims = {
    active: status.active,
    aud: PACKAGE,
    exp: status.active ? Math.min(status.expiry, now + MAX_LIFETIME) : now + 60,
    iat: now,
    nonce,
    purchase_token_hash: await digest(purchaseToken),
  };
  const payload = utf8.encode(JSON.stringify(claims));
  const signature = new Uint8Array(await crypto.subtle.sign(RSA, key, payload));
  return `${encode(payload)}.${encode(signature)}`;
}

/** Access tokens and immutable imported keys are isolate-local; purchase data is never cached. */
export class GooglePlay {
  private oauth?: { value: string; expires: number };
  private oauthFlight?: Promise<string>;
  private credentials?: Promise<{ email: string; kid?: string; key: CryptoKey }>;
  constructor(
    private readonly env: Environment,
    private readonly fetcher: Fetcher = fetch,
    private readonly clock: Clock = () => Math.floor(Date.now() / 1000),
  ) {}

  private serviceAccount(): Promise<{ email: string; kid?: string; key: CryptoKey }> {
    if (!this.credentials) {
      this.credentials = (async () => {
        const raw = this.env("GOOGLE_SERVICE_ACCOUNT_JSON");
        if (!raw || raw.length > 32768) throw new Unavailable("missing_google_credentials");
        let data: JsonObject;
        try {
          data = object(JSON.parse(raw));
        } catch {
          throw new Unavailable("invalid_google_credentials");
        }
        if (
          data.type !== "service_account" || typeof data.client_email !== "string" ||
          !/^[A-Za-z0-9._-]+@[A-Za-z0-9.-]+\.gserviceaccount\.com$/.test(data.client_email) ||
          typeof data.private_key !== "string" ||
          (data.token_uri !== undefined && data.token_uri !== GOOGLE_OAUTH_URL)
        ) {
          throw new Unavailable("invalid_google_credentials");
        }
        const kid = typeof data.private_key_id === "string" &&
            /^[A-Za-z0-9_-]{1,128}$/.test(data.private_key_id)
          ? data.private_key_id
          : undefined;
        return { email: data.client_email, kid, key: await importPrivateKey(data.private_key) };
      })();
    }
    return this.credentials;
  }

  private async accessToken(): Promise<string> {
    if (this.oauth && this.oauth.expires > this.clock() + 60) return this.oauth.value;
    if (!this.oauthFlight) {
      this.oauthFlight = (async () => {
        const account = await this.serviceAccount();
        const now = this.clock();
        const assertion = await signJwt(account.key, {
          iss: account.email,
          scope: GOOGLE_SCOPE,
          aud: GOOGLE_OAUTH_URL,
          iat: now,
          exp: now + 3600,
        }, account.kid);
        const { data } = await fetchJson(this.fetcher, GOOGLE_OAUTH_URL, {
          method: "POST",
          headers: { "content-type": "application/x-www-form-urlencoded" },
          body: new URLSearchParams({
            grant_type: "urn:ietf:params:oauth:grant-type:jwt-bearer",
            assertion,
          }),
        }, 16384);
        const result = object(data);
        if (
          typeof result.access_token !== "string" || result.access_token.length > 4096 ||
          result.token_type !== "Bearer" || typeof result.expires_in !== "number" ||
          !Number.isFinite(result.expires_in) || result.expires_in < 60
        ) {
          throw new Unavailable("invalid_oauth_response");
        }
        this.oauth = {
          value: result.access_token,
          expires: this.clock() + Math.min(3600, Math.floor(result.expires_in)),
        };
        return result.access_token;
      })();
    }
    try {
      return await this.oauthFlight;
    } finally {
      this.oauthFlight = undefined;
    }
  }

  async fetchSubscription(token: string): Promise<unknown> {
    const bearer = await this.accessToken();
    try {
      const { data } = await fetchJson(
        this.fetcher,
        `${GOOGLE_PLAY_BASE}/purchases/subscriptionsv2/tokens/${encodeURIComponent(token)}`,
        { headers: { authorization: `Bearer ${bearer}` } },
      );
      try {
        return object(data);
      } catch {
        throw new Unavailable("invalid_subscription_response");
      }
    } catch (error) {
      if (error instanceof UpstreamError && error.status === 401) this.oauth = undefined;
      throw error;
    }
  }

  async acknowledge(product: string, token: string): Promise<void> {
    if (!PRODUCTS.has(product)) throw new InvalidRequest();
    const bearer = await this.accessToken();
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 8000);
    try {
      const response = await this.fetcher(
        `${GOOGLE_PLAY_BASE}/purchases/subscriptions/${encodeURIComponent(product)}/tokens/${
          encodeURIComponent(token)
        }:acknowledge`,
        {
          method: "POST",
          body: "{}",
          headers: {
            authorization: `Bearer ${bearer}`,
            "content-type": "application/json",
          },
          signal: controller.signal,
          redirect: "error",
        },
      );
      await response.body?.cancel();
      if (!response.ok) throw new UpstreamError(response.status);
    } catch (error) {
      if (error instanceof UpstreamError) throw error;
      throw new Unavailable("acknowledgement_unavailable");
    } finally {
      clearTimeout(timer);
    }
  }
}

export class BillingService {
  private key?: Promise<CryptoKey>;
  constructor(
    private readonly env: Environment,
    private readonly play: Pick<GooglePlay, "fetchSubscription" | "acknowledge">,
    private readonly clock: Clock = () => Math.floor(Date.now() / 1000),
  ) {}

  private signingKey(): Promise<CryptoKey> {
    if (!this.key) {
      const pem = this.env("ENTITLEMENT_PRIVATE_KEY_PEM");
      if (!pem) throw new Unavailable("missing_signing_key");
      this.key = importPrivateKey(pem);
    }
    return this.key;
  }

  async verify(token: string, nonce: string): Promise<string> {
    const key = await this.signingKey();
    let subscription = await this.play.fetchSubscription(token);
    const status = subscriptionStatus(subscription, this.clock());
    if (status.active && status.acknowledgementPending && status.product) {
      try {
        await this.play.acknowledge(status.product, token);
      } catch (error) {
        // Another verifier/Play client can acknowledge the same purchase concurrently.
        if (!(error instanceof UpstreamError && error.status === 409)) throw error;
        subscription = await this.play.fetchSubscription(token);
        if (object(subscription).acknowledgementState !== "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED") {
          throw new Unavailable("acknowledgement_unavailable");
        }
      }
    }
    return signEntitlement(key, subscription, token, nonce, this.clock());
  }
}
