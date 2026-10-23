// Run with: node --test whatsapp-bot/worker.test.mjs
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { test } from "node:test";

import worker, { ownerTexts, validSignature } from "./worker.js";

const env = {
  VERIFY_TOKEN: "pw", APP_SECRET: "s3cret", OWNER_PHONE: "+44 7700 900123",
  WA_TOKEN: "wa", WA_PHONE_NUMBER_ID: "111", GITHUB_TOKEN: "gh", GITHUB_REPO: "me/fx",
};

const update = (from, body) => ({
  entry: [{ changes: [{ value: { messages: [{ from, type: "text", text: { body } }] } }] }],
});

const sign = (body, secret = env.APP_SECRET) => "sha256=" + createHmac("sha256", secret).update(body).digest("hex");

function post(body, signature = sign(body)) {
  return new Request("https://w.example/webhook", {
    method: "POST", body, headers: { "x-hub-signature-256": signature },
  });
}

function capture() {
  const calls = [];
  const pending = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), body: JSON.parse(init.body) });
    return url.includes("github") ? new Response(null, { status: 204 }) : new Response("{}");
  };
  return { calls, ctx: { waitUntil: (p) => pending.push(p) }, done: () => Promise.all(pending) };
}

test("webhook verification", async () => {
  const ok = await worker.fetch(new Request("https://w.example/?hub.mode=subscribe&hub.verify_token=pw&hub.challenge=42"), env);
  assert.equal(await ok.text(), "42");
  const bad = await worker.fetch(new Request("https://w.example/?hub.mode=subscribe&hub.verify_token=no&hub.challenge=42"), env);
  assert.equal(bad.status, 403);
});

test("signature check", async () => {
  assert.ok(await validSignature("abc", sign("abc"), "s3cret"));
  assert.ok(!(await validSignature("abc", sign("abc", "other"), "s3cret")));
  assert.ok(!(await validSignature("abc", null, "s3cret")));
});

test("only the owner's text messages are used", () => {
  assert.deepEqual(ownerTexts(update("447700900123", " /list "), env.OWNER_PHONE), ["/list"]);
  assert.deepEqual(ownerTexts(update("15550001111", "/list"), env.OWNER_PHONE), []);
  assert.deepEqual(ownerTexts({ entry: [{ changes: [{ value: { statuses: [{}] } }] }] }, env.OWNER_PHONE), []);
});

test("owner command starts the workflow and acknowledges", async () => {
  const { calls, ctx, done } = capture();
  const body = JSON.stringify(update("447700900123", "/target GBP/HKD 10.05"));
  const res = await worker.fetch(post(body), env, ctx);
  assert.equal(res.status, 200);
  await done();
  assert.equal(calls[0].url, "https://api.github.com/repos/me/fx/actions/workflows/fxwatch.yml/dispatches");
  assert.deepEqual(calls[0].body, {
    ref: "main", inputs: { mode: "check", command: "/target GBP/HKD 10.05", source: "whatsapp" },
  });
  assert.equal(calls[1].url, "https://graph.facebook.com/v23.0/111/messages");
  assert.equal(calls[1].body.to, "447700900123");
});

test("forged requests are rejected", async () => {
  const { calls, ctx, done } = capture();
  const body = JSON.stringify(update("447700900123", "/list"));
  const res = await worker.fetch(post(body, sign(body, "wrong")), env, ctx);
  assert.equal(res.status, 401);
  await done();
  assert.equal(calls.length, 0);
});
