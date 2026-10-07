/** Optional local interoperability fixture: dummy token and ephemeral test key only. */
import { signEntitlement } from "../functions/_shared/play.ts";
import { nonce, now, rsa, subscription, token } from "./helpers.ts";

if (import.meta.main) {
  const path = Deno.args[0];
  if (!path) throw new Error("Supply a local fixture output path");
  const publicKey = await crypto.subtle.exportKey("jwk", rsa.publicKey);
  const binary = atob(publicKey.n!.replaceAll("-", "+").replaceAll("_", "/"));
  const modulusHex = Array.from(binary, (c) => c.charCodeAt(0).toString(16).padStart(2, "0")).join(
    "",
  );
  const fixture = {
    modulus_hex: modulusHex,
    exponent: 65537,
    purchase_token: token,
    nonce,
    now,
    entitlement: await signEntitlement(rsa.privateKey, subscription(), token, nonce, now),
  };
  await Deno.writeTextFile(path, JSON.stringify(fixture));
}
