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
      if ((request.method === "GET" || request.method === "HEAD") && url.pathname.startsWith("/v/")) return await video(request, env, url);
      if ((request.method === "GET" || request.method === "HEAD") && url.pathname.startsWith("/i/")) return await picture(request, env, url);
    } catch (e) {
      console.log("error", String(e));
      return new Response("error", { status: 200 }); // 200 so Telegram does not keep retrying
    }
    return new Response("Cinema Woods approvals worker is running.");
  },

  // Cron Trigger: starts the news run on time (GitHub's own scheduler is often late or skips runs).
  // Add the trigger in Worker -> Settings -> Triggers -> Cron:  30 1,5,8,11,14 * * *   (UTC = 7, 11, 14, 17, 20 IST)
  async scheduled(event, env, ctx) {
    const resp = await dispatch(env, "post.yml", { scheduled: "1" });
    if (resp.status !== 204) {
      await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chat_id: env.ALLOWED_CHAT_ID,
          text: `⚠️ The scheduled news run could not start (GitHub said ${resp.status}). Check the GitHub token in the Worker settings (it may have expired).` }),
      });
    }
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
  if (cb && /^a:/.test(cb.data || "")) {
    // Approve tapped: show "Posting..." right away so there is no urge to tap again
    ctx.waitUntil(fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/editMessageReplyMarkup`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: chatId, message_id: cb.message.message_id,
        reply_markup: { inline_keyboard: [[{ text: "⏳ Approved - posting...", callback_data: "noop" }]] } }),
    }));
  }
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
    const reelPrefix = /^\s*(\/reel(@\w+)?\b|reel\s*[:\-])\s*/i;
    const isReelReq = reelPrefix.test(text) && text.replace(reelPrefix, "").trim().length > 0;
    if (isReelReq) ack = "🎬 Got it - making your Reel. The preview arrives in about a minute.";
    else if (isReply && hasMedia) ack = "🖼 Got the picture - building your post...";
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
// Serves Reel videos to Instagram/Facebook: the file lives in the (public) repo under reels/, and this route
// hands it out with the correct video headers and Range support, which raw.githubusercontent.com does not.
async function video(request, env, url) {
  const name = url.pathname.slice(3);
  if (!/^[A-Za-z0-9_-]{4,60}\.mp4$/.test(name)) return new Response("not found", { status: 404 });
  const src = `https://raw.githubusercontent.com/${env.GITHUB_REPO}/${env.GITHUB_BRANCH || "main"}/reels/${name}`;
  const headers = {};
  const range = request.headers.get("Range");
  if (range) headers["Range"] = range;
  const r = await fetch(src, { method: request.method, headers, cf: { cacheTtl: 0 } });
  if (r.status !== 200 && r.status !== 206) return new Response("not found", { status: 404 });
  const out = new Headers();
  out.set("Content-Type", "video/mp4");
  out.set("Accept-Ranges", "bytes");
  out.set("Cache-Control", "no-store");
  for (const h of ["Content-Length", "Content-Range"]) if (r.headers.get(h)) out.set(h, r.headers.get(h));
  return new Response(request.method === "HEAD" ? null : r.body, { status: r.status, headers: out });
}

// Serves the post card (graphics/<name>.jpg) to Instagram/Facebook with proper image headers. Instagram often
// fails to fetch pictures straight from raw.githubusercontent.com; this route is much more reliable.
async function picture(request, env, url) {
  const name = url.pathname.slice(3);
  if (!/^[A-Za-z0-9_-]{4,60}\.jpg$/.test(name)) return new Response("not found", { status: 404 });
  const src = `https://raw.githubusercontent.com/${env.GITHUB_REPO}/${env.GITHUB_BRANCH || "main"}/graphics/${name}`;
  const r = await fetch(src, { method: request.method, cf: { cacheTtl: 0 } });
  if (r.status !== 200) return new Response("not found", { status: 404 });
  const out = new Headers();
  out.set("Content-Type", "image/jpeg");
  out.set("Cache-Control", "public, max-age=300");
  if (r.headers.get("Content-Length")) out.set("Content-Length", r.headers.get("Content-Length"));
  return new Response(request.method === "HEAD" ? null : r.body, { status: 200, headers: out });
}

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
