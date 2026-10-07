export function assert(value: unknown, message = "Assertion failed"): asserts value {
  if (!value) throw new Error(message);
}

export function equal(actual: unknown, expected: unknown): void {
  assert(JSON.stringify(actual) === JSON.stringify(expected), "Values differ");
}

export async function rejects(action: () => Promise<unknown>): Promise<void> {
  let failed = false;
  try {
    await action();
  } catch {
    failed = true;
  }
  assert(failed, "Expected rejection");
}

export const rsa = await crypto.subtle.generateKey(
  {
    name: "RSASSA-PKCS1-v1_5",
    modulusLength: 2048,
    publicExponent: new Uint8Array([1, 0, 1]),
    hash: "SHA-256",
  },
  true,
  ["sign", "verify"],
) as CryptoKeyPair;
const binary = String.fromCharCode(
  ...new Uint8Array(await crypto.subtle.exportKey("pkcs8", rsa.privateKey)),
);
export const pem = `-----BEGIN PRIVATE KEY-----\n${btoa(binary)}\n-----END PRIVATE KEY-----`;
export const now = 1800000000;
export const nonce = "test-nonce-unpredictable-response-1234";
export const token = "example-purchase-token-not-a-live-token";
export const env = (name: string): string | undefined =>
  ({
    ENTITLEMENT_PRIVATE_KEY_PEM: pem,
    GOOGLE_SERVICE_ACCOUNT_JSON: JSON.stringify({
      type: "service_account",
      client_email: "play-test@example.iam.gserviceaccount.com",
      private_key: pem,
      private_key_id: "test-key",
      token_uri: "https://oauth2.googleapis.com/token",
    }),
    RTDN_AUDIENCE: "https://example.supabase.co/functions/v1/solarquote-play-rtdn",
    RTDN_SERVICE_ACCOUNT_EMAIL: "push-test@example.iam.gserviceaccount.com",
  } as Record<string, string>)[name];

export function subscription(state = "SUBSCRIPTION_STATE_ACTIVE", seconds = 1000000) {
  return {
    subscriptionState: state,
    acknowledgementState: "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED",
    lineItems: [{
      productId: "solarquote_pro_monthly",
      expiryTime: new Date((now + seconds) * 1000).toISOString(),
    }],
  };
}

export function jsonRequest(data: unknown, authorization?: string): Request {
  return new Request("https://example.supabase.co/functions/v1/test", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      ...(authorization ? { authorization } : {}),
    },
    body: JSON.stringify(data),
  });
}
