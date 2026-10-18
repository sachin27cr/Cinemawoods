// Cinema Woods - instant approvals.
// Telegram calls this Worker the moment you tap Approve/Reject (or reply with a
// poster). The Worker (1) answers the tap right away, (2) keeps the update in a
// small queue (KV) so nothing is ever lost, and (3) starts the GitHub
// "Approve and Publish" workflow immediately instead of waiting for a schedule.
//
// Settings (Worker -> Settings -> Variables and Secrets):
//   WEBHOOK_SECRET      secret  any long random string (also used in setWebhook)
//   QUEUE_SECRET        secret  another long random string (also a GitHub secret)
//   TELEGRAM_BOT_TOKEN  secret  your bot token
//   GITHUB_TOKEN        secret  fine-grained token: this repo only, "Actions: Read and write"
//   GITHUB_REPO         text    sachin27cr/Cinemawoods
//   ALLOWED_CHAT_ID     text    your Telegram chat id
//   GITHUB_BRANCH       text    main   (optional)
// KV binding: name it QUEUE.

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    try {
      if (request.method === "POST" && url.pathname === "/webhook") return await webhook(request, env, ctx);
      if (request.method === "POST" && url.pathname === "/queue") return await drain(request, env);
    } catch (e) {
      console.log("error", String(e));
      return new Response("error", { status: 200 }); // 200 so Telegram does not keep retrying
    }
    return new Response("Cinema Woods approvals worker is running.");
  },
};

async function webhook(request, env, ctx) {
  if (request.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.WEBHOOK_SECRET) {
    return new Response("forbidden", { status: 403 });
  }
  const update = await request.json();
  const cb = update.callback_query;
  const msg = update.message;
  const chatId = String((cb && cb.message && cb.message.chat && cb.message.chat.id) ||
                        (msg && msg.chat && msg.chat.id) || "");
  if (chatId !== String(env.ALLOWED_CHAT_ID)) return new Response("ok"); // ignore strangers

  const isReply = !!(msg && msg.reply_to_message);
  const hasMedia = !!(msg && (msg.photo || msg.document));
  const text = (msg && (msg.text || msg.caption)) || "";
  // /news [n]  ->  start the news run right now (n = how many drafts, 1-8)
  const cmd = msg && !isReply ? text.trim().match(/^\/news(?:@\w+)?(?:\s+(\d{1,2}))?\s*$/i) : null;
  if (cmd) {
    const count = cmd[1] ? Math.min(Math.max(parseInt(cmd[1], 10), 1), 8) : 0;
    const resp = await dispatch(env, "post.yml", count ? { count: String(count) } : {});
    const reply = resp.status === 204
      ? `📰 On it - fetching fresh news${count ? ` (up to ${count} drafts)` : ""}. Drafts arrive in about 2-4 minutes.`
      : `⚠️ Could not start the news run (GitHub said ${resp.status}). Check the GitHub token in the Worker settings.`;
    ctx.waitUntil(fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: chatId, text: reply }),
    }));
    return new Response("ok");
  }

  // taps; images; and new text tips (a plain text reply to a draft is ignored)
  const relevant = cb || (msg && (hasMedia || (!isReply && text)));
  if (!relevant) return new Response("ok");

  // 1) durable queue (24h)
  const key = "u:" + String(update.update_id).padStart(14, "0");
  await env.QUEUE.put(key, JSON.stringify(update), { expirationTtl: 86400 });

  // 2) instant feedback on the button
  if (cb) {
    ctx.waitUntil(fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/answerCallbackQuery`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ callback_query_id: cb.id, text: "Got it - working on it..." }),
    }));
  }

  // instant acknowledgement for tips and posters
  if (msg) {
    let ack = null;
    if (isReply && hasMedia) ack = "🖼 Got the poster - rebuilding the draft...";
    else if (!isReply && text && !text.startsWith("/")) ack = "🔎 Got it - researching. Your draft will arrive in about a minute.";
    if (ack) {
      ctx.waitUntil(fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chat_id: chatId, text: ack }),
      }));
    }
  }

  // 3) start the workflow now (the update also travels with it)
  const resp = await dispatch(env, "approvals.yml", { update: JSON.stringify(update) });
  if (resp.status !== 204) console.log("dispatch failed", resp.status, (await resp.text()).slice(0, 200));
  return new Response("ok");
}

async function dispatch(env, workflowFile, inputs) {
  return fetch(
    `https://api.github.com/repos/${env.GITHUB_REPO}/actions/workflows/${workflowFile}/dispatches`, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${env.GITHUB_TOKEN}`,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "cinemawoods-approvals-worker",
      },
      body: JSON.stringify({ ref: env.GITHUB_BRANCH || "main", inputs }),
    });
}

// The workflow calls this to collect (and clear) any updates still waiting.
async function drain(request, env) {
  if (request.headers.get("X-Queue-Secret") !== env.QUEUE_SECRET) return new Response("forbidden", { status: 403 });
  const list = await env.QUEUE.list({ prefix: "u:" });
  const updates = [];
  for (const k of list.keys) {
    const v = await env.QUEUE.get(k.name);
    if (v) updates.push(JSON.parse(v));
    await env.QUEUE.delete(k.name);
  }
  updates.sort((a, b) => a.update_id - b.update_id);
  return new Response(JSON.stringify({ updates }), { headers: { "Content-Type": "application/json" } });
}
