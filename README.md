# South Indian Cinema News Bot

Automated Facebook + Instagram page covering Telugu, Tamil, Kannada, and
Malayalam film news. Runs 3x/day via GitHub Actions (free tier), zero
recurring cost.

## How it works

1. Pulls news from RSS feeds (TOI, The Hindu, plus Google News topic feeds
   for each language — see `config.py`)
2. Filters for relevance, removes stories already posted or that duplicate
   another source's coverage of the same story
3. Rewrites the headline into a short caption via Gemini (free tier)
4. Generates a branded text-card graphic locally (Pillow) — **no
   copyrighted press photos are ever used or reposted**
5. Either sends the draft to your Telegram for a thumbs-up (default) or
   posts directly to FB + IG, depending on `TELEGRAM_REVIEW`
6. Logs what's been posted so it's never repeated

## One-time setup

### 1. Create the Facebook Page and link Instagram

- Create a Facebook Page (if you don't have one for this yet)
- Convert your Instagram account to a **Business** account, and in
  Settings → Linked Accounts, connect it to the Facebook Page
- Both must be linked for the Graph API's IG endpoints to work

### 2. Create a Meta App and get tokens

This is the fiddliest part — Meta gates programmatic posting behind app
review for anything beyond your own assets, but posting to your **own**
Page/IG account works immediately in Development mode:

1. Go to [developers.facebook.com](https://developers.facebook.com) →
   My Apps → Create App → type "Business"
2. Add the **Facebook Login** and **Instagram Graph API** products
3. Go to Tools → Graph API Explorer, select your app, and generate a
   User Access Token with these permissions:
   `pages_show_list, pages_read_engagement, pages_manage_posts, instagram_basic, instagram_content_publish`
4. Use that token to fetch your Page's ID and a **Page Access Token**:
   `GET /me/accounts` — copy the `id` (this is `FB_PAGE_ID`) and
   `access_token` (this is `FB_PAGE_ACCESS_TOKEN`) for your page
5. Get your Instagram Business Account ID:
   `GET /{FB_PAGE_ID}?fields=instagram_business_account` — the returned
   id is `IG_BUSINESS_ACCOUNT_ID`
6. **Important**: Page Access Tokens from this flow expire in ~60 days
   unless you exchange for a long-lived token
   (`GET /oauth/access_token?grant_type=fb_exchange_token...`) — do that
   exchange and use the long-lived token as your secret. You'll still
   need to refresh it periodically; there's no way around Meta's token
   expiry for a page-level bot without going through full Business
   Verification for a permanent system-user token, which is worth doing
   once this is running smoothly.

### 3. Get a Gemini API key (free tier)

[aistudio.google.com/apikey](https://aistudio.google.com/apikey) — same
provider you're already using for your Telegram analysis bot.

### 4. Set up Telegram review bot (recommended to start)

Same pattern as your other bots: message @BotFather, create a bot, get
the token. Get your chat ID by messaging the bot once and hitting
`https://api.telegram.org/bot<TOKEN>/getUpdates`.

### 5. Push this repo to GitHub and add secrets

Repo → Settings → Secrets and variables → Actions → add:
- `GEMINI_API_KEY`
- `FB_PAGE_ID`
- `FB_PAGE_ACCESS_TOKEN`
- `IG_BUSINESS_ACCOUNT_ID`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

And under **Variables** (not secrets, since these aren't sensitive):
- `TELEGRAM_REVIEW` = `1` (review mode) or `0` (fully automated)
- `MAX_POSTS_PER_RUN` = `3` (or whatever pace you want)

## Local testing before going live

```bash
pip install -r requirements.txt
python fetch_news.py          # confirms feeds are reachable and returning items
python main.py --dry-run      # runs the full pipeline, prints captions/images, posts nothing
```

Open the images in `generated_graphics/` to sanity-check how they look
before connecting real posting.

## Recommended rollout

1. Run with `TELEGRAM_REVIEW=1` for the first 1-2 weeks — you approve
   every post manually via reviewing the Telegram draft, catches any bad
   captions or irrelevant stories before they go live publicly
2. Once you trust the caption quality and relevance filtering, flip
   `TELEGRAM_REVIEW=0` in the repo Variables for full automation
3. Periodically skim `STAR_NAMES`, `HOT_TERMS`, `MIN_SCORE` and `GOOGLE_NEWS_TOPICS` in
   `config.py` — tighten or loosen as you see what gets through

## Known limitations / things to watch

- **Token expiry**: Page Access Tokens need periodic refresh (see setup
  step 2) unless you complete Meta Business Verification for a
  permanent token
- **Caption accuracy**: The LLM step can occasionally misstate a detail;
  spot-check periodically even in full-auto mode
- **Image hosting**: images are committed to the repo and served via
  `raw.githubusercontent.com` — free, but means your repo's graphics
  history grows over time; consider periodically clearing old images
  from `graphics/` (they've already been posted, so they don't need to
  stay)
- **Feed reliability**: individual regional trade sites often don't
  maintain stable RSS feeds, which is why this leans on Google News
  topic feeds + national outlets rather than scraping smaller sites
  directly. Run `python fetch_news.py` occasionally to catch a feed
  going stale

## Approve-by-tap flow (default, TELEGRAM_REVIEW=1)

1. `post.yml` runs 3x/day, picks the top trending South Indian film stories,
   writes captions, makes JPEG cards, and sends each one to your Telegram bot
   with **Approve** and **Reject** buttons. Nothing is posted yet.
2. `approvals.yml` runs about every 15 minutes, reads your button taps, and
   publishes approved stories to the Facebook Page and Instagram. You can also
   run it by hand from the Actions tab right after tapping.
3. If one platform fails, you get a Telegram message with the reason; tap
   Approve again to retry only the part that failed.

Use a Telegram bot token that no other script polls with `getUpdates`.
Set `TELEGRAM_REVIEW` to `0` for fully automatic posting once you trust it.

## Card design

`graphic_gen.py` draws every card in code (no photos or posters). All cards share
one brand frame, rotate through six layouts (spotlight, filmstrip, diagonal,
viewfinder, ticket, big-number box-office), and take their accent color from the
industry (Telugu orange, Tamil red, Kannada gold, Malayalam green).
To use your own logo, add a transparent PNG at `assets/logo.png`.

## Variety and freshness

Each run picks stories with `classify.py`: never two stories on the same film or
star, spread across Telugu/Tamil/Kannada/Malayalam and across story types (box
office, trailer, OTT...). A film or star you covered recently is skipped for 48 hours
(12 hours if the new story is a different type). Stories older than 30 hours are
ignored. All tunables are in `config.py` (MAX_AGE_HOURS, TOPIC_COOLDOWN_HOURS, ...).

## Instant approvals (Cloudflare Worker)

`cloudflare/worker.js` receives Telegram's webhook the moment you tap Approve/Reject,
queues the tap and starts the "Approve and Publish" workflow immediately (about 30-60 s
end to end instead of waiting for a schedule). Setup steps are in the chat where this
was delivered; settings used: GitHub variable `WORKER_URL`, GitHub secret `WORKER_SECRET`.
Without the worker the bot still works the old way (polling every 30 minutes).

## Send your own story tips

Message the Telegram bot a link, a headline, rough notes, or a photo with a caption (forwarded
channel posts work too). The bot researches it with Gemini + Google Search, writes the headline and
description, picks the picture (your photo, else the link's image, else a headline card) and sends a
draft with Approve / Reject. Start the message with `!` to post something it couldn't verify.
Needs the updated `worker.js` deployed and the `GEMINI_API_KEY` secret (already used by the bot).

### Reposting an official poster (release date, collection, OTT posters)
Instagram blocks automatic downloads, so save the poster from the actor's post yourself and send it to the
bot as a PHOTO with a caption: the news in a few words + the page's @handle (or its profile link).
The bot keeps the poster exactly as it is, writes the update, and adds "📸 Poster: @handle".
Each post also gets a randomly chosen writing voice so captions stop sounding the same.

## /news command
Send `/news` to the bot to fetch fresh news and get drafts right away (`/news 5` = up to 5 drafts).
It uses the same variety and no-repeat rules as the scheduled runs; if nothing new qualifies, the bot says why.

### Photo posts (your description, word for word)
Send a photo with your description as the caption. The bot posts your description exactly as written and
only adds a short headline on the picture (photo fills the card, logo on top, headline at the bottom).
Start the caption with `poster:` to keep the picture completely untouched (official posters).
Links and text-only tips are researched and written by Gemini.

## Reels
Every draft has a **🎬 Make Reel** button (it stays after you approve the picture post). Tap it and the bot
renders a 9:16 video (1080x1920, H.264 + AAC, `REEL_SECONDS` long, default 9): your picture with a slow zoom,
logo on top, the headline at 1s, one line of the post text at 3s, "FOLLOW @handle" (`REEL_HANDLE`).
A preview arrives in Telegram with **Post Reel / Discard**. Post Reel publishes to Instagram Reels + a Facebook Reel.
- Music: put licensed tracks in `assets/music/`; otherwise a generated ambient pad is used.
- Hosting: Meta fetches the video from `<WORKER_URL>/v/<id>.mp4` (the Cloudflare Worker serves the file from `reels/` in
  the repo). Without a Worker it falls back to raw.githubusercontent.com.
- Videos are deleted from the repo once posted or discarded.

### Reel from your own pictures and text
Send 1-6 photos as one album with a caption starting `reel:` (or only text starting `reel:`). The bot posts your text
word for word, creates a headline for the video, makes a slideshow Reel (about 3 seconds per picture, cross-fades,
slow zoom) and sends a preview with Post Reel / Discard. Landscape pictures are shown whole on a blurred background.

## Accuracy checks on automatic news posts
Before a draft reaches Telegram the bot now: opens the real article (Google News links are decoded to the publisher page),
skips it if the article itself is older than `ARTICLE_MAX_AGE_HOURS` (48h) or the feed gave no date, drops Hindi-film-only
headlines, has Gemini write ONLY from the article text, and then checks that every name, number and year in the post
appears in the article. A failed check gets one rewrite, then the story is held (listed in the run summary).
Drafts say "✅ Fact-checked against the article" or "⚠️ Article could not be opened - check names and dates yourself".

## Claude as editor (optional, about $6-10 a month)

With the `ANTHROPIC_API_KEY` secret set, Claude (not Gemini) does the editing work:

1. **Ranks the stories** each run: real news first, spread across Telugu/Tamil/Kannada/Malayalam and story types, no repeats of recent topics, drops listicles/Hindi-only/old items.
2. **Writes each post from the article text** and replies SKIP/UNVERIFIED instead of guessing. The free fact-check still runs afterwards.
3. **Looks at the candidate pictures** on the article page and picks the real poster/still (or says none, and the text card is used).
4. Also writes the picture headline for your photo posts, and handles the tips you send in Telegram (with web search).

If the key is missing, the monthly cap is reached, or Claude is down, everything falls back to Gemini automatically.

Setup: console.anthropic.com -> add credit and a spend limit -> create an API key -> GitHub repo -> Settings -> Secrets and variables -> Actions -> New repository secret `ANTHROPIC_API_KEY`.

Variables (Settings -> Variables, all optional): `CLAUDE_MONTHLY_CAP_USD` (default 12), `USE_CLAUDE` (0 turns it off), `CLAUDE_MODEL` (default claude-sonnet-5-5), `CLAUDE_FAST_MODEL` (default claude-haiku-5-5). Spend is tracked in `claude_usage.json` and shown in the run summary.
