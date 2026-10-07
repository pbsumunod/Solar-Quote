/** Google's fixed JWKS and verified Pub/Sub push identity; no third-party JWT dependency. */
import {
  Clock,
  decode,
  decodeJson,
  Environment,
  Fetcher,
  fetchJson,
  JsonObject,
  object,
  Unauthorized,
  Unavailable,
} from "./play.ts";

export const GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs";
const utf8 = new TextEncoder();
const RSA = { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" };

export function validatePushClaims(
  claims: JsonObject,
  audience: string,
  email: string,
  now: number,
): void {
  if (
    (claims.iss !== "accounts.google.com" && claims.iss !== "https://accounts.google.com") ||
    claims.aud !== audience || claims.email !== email || claims.email_verified !== true ||
    typeof claims.sub !== "string" || !/^\d{1,64}$/.test(claims.sub) ||
    typeof claims.exp !== "number" || !Number.isSafeInteger(claims.exp) || claims.exp <= now ||
    typeof claims.iat !== "number" || !Number.isSafeInteger(claims.iat) ||
    claims.iat < 0 || claims.iat > now + 300 || claims.exp <= claims.iat ||
    (claims.nbf !== undefined && (typeof claims.nbf !== "number" ||
      !Number.isSafeInteger(claims.nbf) || claims.nbf > now))
  ) {
    throw new Unauthorized();
  }
}

export class GooglePushIdentity {
  private cache = new Map<string, CryptoKey>();
  private expires = 0;
  private lastRefresh = -Infinity;
  private flight?: Promise<void>;
  constructor(
    private readonly env: Environment,
    private readonly fetcher: Fetcher = fetch,
    private readonly clock: Clock = () => Math.floor(Date.now() / 1000),
  ) {}

  private async refresh(): Promise<void> {
    if (!this.flight) {
      this.flight = (async () => {
        const { data, headers } = await fetchJson(this.fetcher, GOOGLE_JWKS_URL);
        const keys = object(data).keys;
        if (!Array.isArray(keys) || keys.length < 1 || keys.length > 20) throw new Unavailable();
        const fresh = new Map<string, CryptoKey>();
        for (const item of keys) {
          const jwk = object(item);
          if (
            jwk.kty !== "RSA" || jwk.alg !== "RS256" || jwk.use !== "sig" ||
            typeof jwk.kid !== "string" || !/^[A-Za-z0-9_-]{1,128}$/.test(jwk.kid) ||
            typeof jwk.n !== "string" || jwk.n.length > 2048 || jwk.e !== "AQAB" ||
            decode(jwk.n).byteLength < 256
          ) continue;
          const key = await crypto.subtle.importKey("jwk", jwk as JsonWebKey, RSA, false, [
            "verify",
          ]);
          fresh.set(jwk.kid, key);
        }
        if (!fresh.size) throw new Unavailable();
        const maxAge = headers.get("cache-control")?.match(/(?:^|[,\s])max-age=(\d+)/)?.[1];
        this.cache = fresh;
        this.lastRefresh = this.clock();
        // Never retain Google's rotation keys beyond their advertised lifetime.
        this.expires = this.clock() + Math.min(3600, maxAge ? Number(maxAge) : 300);
      })();
    }
    try {
      await this.flight;
    } catch {
      throw new Unavailable("google_identity_unavailable");
    } finally {
      this.flight = undefined;
    }
  }

  async verify(bearer: string): Promise<void> {
    const audience = this.env("RTDN_AUDIENCE");
    const email = this.env("RTDN_SERVICE_ACCOUNT_EMAIL");
    if (
      !audience || !/^https:\/\//.test(audience) || !email ||
      !/^[A-Za-z0-9._-]+@[A-Za-z0-9.-]+\.gserviceaccount\.com$/.test(email)
    ) {
      throw new Unavailable("rtdn_not_configured");
    }
    if (bearer.length > 16384) throw new Unauthorized();
    let header: JsonObject;
    let claims: JsonObject;
    const parts = bearer.split(".");
    try {
      if (parts.length !== 3) throw new Unauthorized();
      header = decodeJson(parts[0]);
      claims = decodeJson(parts[1]);
      if (
        header.alg !== "RS256" || typeof header.kid !== "string" ||
        !/^[A-Za-z0-9_-]{1,128}$/.test(header.kid) ||
        (header.typ !== undefined && header.typ !== "JWT")
      ) throw new Unauthorized();
      // Reject unrelated identities before a network fetch; claims are still untrusted here.
      validatePushClaims(claims, audience, email, this.clock());
    } catch {
      throw new Unauthorized();
    }
    if (this.expires <= this.clock()) await this.refresh();
    if (!this.cache.has(String(header.kid)) && this.clock() - this.lastRefresh >= 30) {
      await this.refresh();
    }
    const key = this.cache.get(String(header.kid));
    if (!key) throw new Unauthorized();
    try {
      if (
        !await crypto.subtle.verify(
          RSA,
          key,
          new Uint8Array(decode(parts[2])),
          utf8.encode(`${parts[0]}.${parts[1]}`),
        )
      ) throw new Unauthorized();
      validatePushClaims(claims, audience, email, this.clock());
    } catch {
      throw new Unauthorized();
    }
  }
}
