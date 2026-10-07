import { createRtdnHandler } from "../_shared/http.ts";
import { GooglePushIdentity } from "../_shared/oidc.ts";
import { BillingService, GooglePlay } from "../_shared/play.ts";

const env = (name: string) => Deno.env.get(name);
const service = new BillingService(env, new GooglePlay(env));
Deno.serve(createRtdnHandler(service, new GooglePushIdentity(env)));
