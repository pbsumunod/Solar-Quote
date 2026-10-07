import { createVerifyHandler } from "../_shared/http.ts";
import { BillingService, GooglePlay } from "../_shared/play.ts";

const env = (name: string) => Deno.env.get(name);
const service = new BillingService(env, new GooglePlay(env));
Deno.serve(createVerifyHandler(service));
