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
3. Periodically skim `KEYWORD_FILTER` and `GOOGLE_NEWS_TOPICS` in
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
