// FX Watch WhatsApp relay (Cloudflare Worker).
//
// WhatsApp Cloud API -> this Worker -> GitHub "Run workflow" with your command.
// The workflow applies the command, runs a check, and replies on WhatsApp.
//
// Secrets / variables (see docs/whatsapp-bot.md):
//   VERIFY_TOKEN        any password you choose; also typed into Meta's webhook settings
//   APP_SECRET          Meta app secret, used to check messages really come from Meta
//   OWNER_PHONE         your WhatsApp number, digits only with country code (447700900123)
//   WA_TOKEN            permanent WhatsApp access token (to send the "working on it" reply)
//   WA_PHONE_NUMBER_ID  the bot number's Phone number ID from Meta
//   GITHUB_TOKEN        fine-grained token with "Actions: read and write" on the repo
//   GITHUB_REPO         e.g. hong111o/fxdashboard
//   GITHUB_REF          branch to run on (default "main")
//   GRAPH_VERSION       Meta Graph API version (default "v23.0")

const WORKFLOW = "fxwatch.yml";

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (request.method === "GET") return verifySubscription(url, env);
    if (request.method !== "POST") return new Response("method not allowed", { status: 405 });

    const body = await request.text();
    if (!(await validSignature(body, request.headers.get("x-hub-signature-256"), env.APP_SECRET))) {
      return new Response("bad signature", { status: 401 });
    }
    // Answer Meta straight away (it retries slow webhooks) and do the work in the background.
    ctx.waitUntil(handleUpdate(JSON.parse(body), env).catch((err) => console.error(err)));
    return new Response("ok");
  },
};

function verifySubscription(url, env) {
  const p = url.searchParams;
  if (p.get("hub.mode") === "subscribe" && env.VERIFY_TOKEN && p.get("hub.verify_token") === env.VERIFY_TOKEN) {
    return new Response(p.get("hub.challenge") || "");
  }
  return new Response("forbidden", { status: 403 });
}

export async function validSignature(body, header, secret) {
  if (!header || !secret || !header.startsWith("sha256=")) return false;
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const mac = new Uint8Array(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(body)));
  const expected = [...mac].map((b) => b.toString(16).padStart(2, "0")).join("");
  const given = header.slice(7).toLowerCase();
  if (given.length !== expected.length) return false;
  let diff = 0;
  for (let i = 0; i < expected.length; i++) diff |= given.charCodeAt(i) ^ expected.charCodeAt(i);
  return diff === 0;
}

export function ownerTexts(update, ownerPhone) {
  const owner = String(ownerPhone || "").replace(/\D/g, "");
  const texts = [];
  for (const entry of update.entry || []) {
    for (const change of entry.changes || []) {
      for (const msg of change.value?.messages || []) {
        if (msg.type === "text" && owner && msg.from === owner && msg.text?.body?.trim()) {
          texts.push(msg.text.body.trim());
        }
      }
    }
  }
  return texts;
}

export async function handleUpdate(update, env) {
  for (const text of ownerTexts(update, env.OWNER_PHONE)) {
    const res = await fetch(
      `https://api.github.com/repos/${env.GITHUB_REPO}/actions/workflows/${WORKFLOW}/dispatches`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${env.GITHUB_TOKEN}`,
          Accept: "application/vnd.github+json",
          "User-Agent": "fxwatch-whatsapp-relay",
        },
        body: JSON.stringify({
          ref: env.GITHUB_REF || "main",
          inputs: { mode: "check", command: text, source: "whatsapp" },
        }),
      });
    const reply = res.ok
      ? "⏳ Got it - working on it (about a minute)..."
      : `⚠️ Couldn't start FX Watch (GitHub said ${res.status}). Check the Worker's GITHUB_TOKEN.`;
    await sendWhatsApp(env, reply);
  }
}

export async function sendWhatsApp(env, text) {
  const version = env.GRAPH_VERSION || "v23.0";
  return fetch(`https://graph.facebook.com/${version}/${env.WA_PHONE_NUMBER_ID}/messages`, {
    method: "POST",
    headers: { Authorization: `Bearer ${env.WA_TOKEN}`, "Content-Type": "application/json" },
    body: JSON.stringify({
      messaging_product: "whatsapp",
      to: String(env.OWNER_PHONE).replace(/\D/g, ""),
      type: "text",
      text: { body: text },
    }),
  });
}
