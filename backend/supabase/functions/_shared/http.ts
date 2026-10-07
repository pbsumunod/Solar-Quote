/** Public token verification and authenticated RTDN handlers. */
import {
  BillingService,
  Clock,
  digest,
  InvalidRequest,
  object,
  PACKAGE,
  readJson,
  Unauthorized,
  UpstreamError,
  validateToken,
  validateVerify,
} from "./play.ts";

const HEADERS = { "content-type": "application/json", "cache-control": "no-store" };

function response(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), { status, headers: HEADERS });
}

function failure(error: unknown, notification = false): Response {
  if (error instanceof Unauthorized) return response({ error: "unauthorized" }, 401);
  if (
    error instanceof InvalidRequest ||
    (!notification && error instanceof UpstreamError && [400, 404, 410].includes(error.status))
  ) {
    return response({ error: "invalid_request" }, 400);
  }
  // No exception text, Google response body, URL or bearer token reaches a log/response.
  return response({ error: "verification_unavailable" }, 503);
}

/** A bounded isolate safeguard only. Production needs a distributed gateway/KV limit too. */
export class IsolateLimiter {
  private entries = new Map<string, { start: number; count: number }>();
  private globalStart = 0;
  private globalCount = 0;
  constructor(private readonly clock: Clock = () => Math.floor(Date.now() / 1000)) {}

  allow(key: string): boolean {
    const now = this.clock();
    if (now - this.globalStart >= 60) {
      this.globalStart = now;
      this.globalCount = 0;
      for (const [id, value] of this.entries) {
        if (now - value.start >= 60) this.entries.delete(id);
      }
    }
    if (this.globalCount >= 200) return false;
    this.globalCount++;
    let entry = this.entries.get(key);
    if (!entry || now - entry.start >= 60) {
      if (this.entries.size >= 1000) return false;
      entry = { start: now, count: 0 };
      this.entries.set(key, entry);
    }
    if (entry.count >= 30) return false;
    entry.count++;
    return true;
  }
}

export function createVerifyHandler(
  service: Pick<BillingService, "verify">,
  limiter = new IsolateLimiter(),
): (request: Request) => Promise<Response> {
  return async (request) => {
    if (request.method !== "POST") return response({ error: "method_not_allowed" }, 405);
    if (!request.headers.get("content-type")?.toLowerCase().startsWith("application/json")) {
      return response({ error: "invalid_request" }, 400);
    }
    try {
      const data = validateVerify(await readJson(request));
      // No attacker-controlled forwarding headers are used as an identity.
      if (!limiter.allow(await digest(data.purchase_token))) {
        return response({ error: "rate_limited" }, 429);
      }
      return response({ entitlement: await service.verify(data.purchase_token, data.nonce) });
    } catch (error) {
      return failure(error);
    }
  };
}

export function createRtdnHandler(
  service: Pick<BillingService, "verify">,
  identity: { verify(bearer: string): Promise<void> },
): (request: Request) => Promise<Response> {
  return async (request) => {
    if (request.method !== "POST") return response({ error: "method_not_allowed" }, 405);
    try {
      const authorization = request.headers.get("authorization") ?? "";
      if (!authorization.startsWith("Bearer ") || authorization.length > 16391) {
        throw new Unauthorized();
      }
      // Verify Google signature, audience and exact verified push-account email before parsing data.
      await identity.verify(authorization.slice(7));
      const envelope = object(await readJson(request));
      const message = object(envelope.message);
      if (
        typeof message.data !== "string" || message.data.length > 12000 ||
        !/^[A-Za-z0-9+/]*={0,2}$/.test(message.data) || message.data.length % 4 !== 0
      ) {
        throw new InvalidRequest();
      }
      let payload;
      try {
        const bytes = Uint8Array.from(atob(message.data), (c) => c.charCodeAt(0));
        payload = object(JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)));
      } catch {
        throw new InvalidRequest();
      }
      if (payload.packageName !== PACKAGE) throw new InvalidRequest();
      const notification = payload.subscriptionNotification ?? payload.voidedPurchaseNotification;
      if (notification === undefined) {
        // Play's authenticated setup/test messages and irrelevant one-time products are acknowledged.
        if (
          payload.testNotification === undefined && payload.oneTimeProductNotification === undefined
        ) {
          throw new InvalidRequest();
        }
        return response({ accepted: true });
      }
      const details = object(notification);
      if (payload.voidedPurchaseNotification !== undefined && details.productType !== 1) {
        return response({ accepted: true });
      }
      const token = validateToken(details.purchaseToken);
      try {
        // Notification types never grant/revoke access themselves: subscriptionsv2 is authoritative.
        // No entitlement cache/store or device push exists in this token-only adapter.
        await service.verify(token, "notification-verification");
      } catch (error) {
        // Permanently unavailable/old tokens cannot be retried successfully; do not retry them forever.
        if (!(error instanceof UpstreamError && [400, 404, 410].includes(error.status))) {
          throw error;
        }
      }
      return response({ accepted: true });
    } catch (error) {
      return failure(error, true);
    }
  };
}
