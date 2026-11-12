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

## News first, picture from you (default)

Each story now arrives in Telegram as TEXT (headline + post text). Reply to that message with the picture you want:
the bot puts the headline and the logo on it, adds the follow tag, and sends the finished post with the description
for Approve. Approve posts to Instagram and Facebook.

- Caption your reply `poster:` to keep the picture completely untouched.
- Buttons under each story: **Use article picture** (the poster Claude picked from the article) or **Text card**.
- Reply again to the finished post with another picture to swap it.
- Set the repository variable `NEWS_FIRST` to `0` to go back to automatic cards.

## Posting reliability

Instagram's servers fetch the card from a public address. The bot now serves cards through your Cloudflare Worker
(`/i/<name>.jpg`, redeploy `cloudflare/worker.js`), falls back to raw GitHub, retries, and uploads the file straight
to Facebook if the address fails. A failed post sends the exact reason to Telegram (for example an expired token) and
turns the buttons into **Retry posting**; only the platform that failed is retried.

## Threads (optional)

Add the repo secrets `THREADS_USER_ID` and `THREADS_ACCESS_TOKEN` and every approved draft is also posted to Threads,
with the same picture and a SHORT text (up to 500 characters, the Threads maximum, a shortened copy of the Instagram caption, same wording): a hook, the key facts, at most 2
hashtags. Gemini writes it from the approved description only (no new facts); if Gemini is down, a trimmed version
of the description is used. Threads tokens last 60 days; refresh before they expire.

## Instagram watchlist (v17)
The bot reads the latest posts of the Instagram pages you follow (actors, production companies, media outlets) and
uses them as its main news source: the caption is the source text and the post's picture is offered as the official
poster. Google News stays as a backup.

1. Put the handles in `watchlist.txt` (one per line; add `,media` after news outlets).
2. Run **Actions → Check Instagram watchlist**: Telegram lists which pages are readable. Only public Business or
   Creator accounts can be read; personal accounts show ❌.
3. Settings (GitHub → Variables): `IG_OFFICIAL_BONUS` (default 6), `IG_MEDIA_BONUS` (3), `IG_WATCH_ONLY=1` to ignore
   Google News completely, `IG_MAX_AGE_HOURS` (30), `IG_POSTS_PER_PAGE` (8).
It uses the existing `FB_PAGE_ACCESS_TOKEN` and `IG_BUSINESS_ACCOUNT_ID`; no new secret.

## Threads preview (v18)
When Threads is connected, every draft now shows the short Threads version under the Facebook/Instagram text
("🧵 THREADS POST (n characters)"). The text is saved with the draft and posted to Threads exactly as shown.

## Instagram access, tips and news queries (v19)
- If the Instagram watchlist reports error 10, the Meta app lacks permission to read other pages (needs Advanced
  Access via App Review). The bot stops after the first failure and carries on with Google News.
- Share an Instagram post link to the bot (Share -> Telegram): it tries to read the public caption and picture. If
  Instagram blocks it, send the link together with the caption text.
- Google News now also searches announcement-style stories (release dates, teasers, OTT dates, collections) and the
  producers and outlets you follow. Stories with a concrete date or festival slot get a small score bonus.

## Screenshots and text tips, picture afterwards (v20)
- Photo WITH a caption: unchanged (the photo is the poster, your caption is posted as written).
- Photo with NO caption (e.g. an Instagram screenshot): Gemini reads the text in it, the bot writes the post and
  sends it as text; reply to that message with the picture you want.
- Text or link only: same text-first flow (an article/post picture is offered as a button when one is found).

## Reliability and speed (v21)
- Runs now check out only the latest files (the repo history is large because of pictures/videos), which removes
  most of the start-up delay.
- Pictures and Reels of finished drafts are deleted after 2 days, stale drafts after 4, draft records after 14.
- Telegram sends are retried; when one still fails the message now says why.
- A failed run now sends the last lines of its log to Telegram, plus which step failed.

## Headline font (v22)
All card and Reel headlines now use Bebas Neue (assets/fonts/BebasNeue-Regular.ttf, SIL Open Font License; licence
file included). If the font file is missing the bot falls back to the old font automatically.

## Meme template (v23)
Send 1-4 photos (one album) with a caption:
    meme:
    Three *chart-topping albums* across different genres in just a *100-day span*
    ---
    That's the magic of **Devi Sri Prasad**
*words* = gold, **words** = green; the logo sits on the seam between the photos. Optional third part (another ---) is
your own post caption, otherwise the caption is your two texts plus hashtags. Styles: forest (default), logo, warm,
classic, brand, royal, studio - for example `meme: royal`. Send `meme:` alone to see the format.

## Merged build (v24)
Brings back features that an earlier upload had overwritten: template Reels (ott / news / poster / bo with generated
beats), the HD-download button, waiting for all photos of an album, the Cloudflare user-agent fix for the Worker queue,
and the Worker's template ack. Everything from v17-v23 (watchlist, screenshots, Threads preview, Bebas Neue headlines,
meme template, faster runs) is kept.

## Two-step screenshot flow (v27)
Send a screenshot with the caption `meme` or `post`. Gemini reads it and writes the text: for `meme` the top and bottom
lines (with highlights) and the post description; for `post` the headline and description. You get the text in Telegram.
Then send only the picture(s) with no caption (a meme takes 1-4 photos as one album) and the finished card arrives with
Approve / Reject. The open request lasts 6 hours. A photo with no caption and no open request still works as before
(read as a screenshot). Replying to a draft with a picture also still works.

## Carousel option for memes (v28)
`meme:` posts only the meme card (default). Add `+photo` to the first line - `meme+photo:`, `meme: +photo`, `meme royal +photo` -
and Instagram, Facebook and Threads get a carousel: the meme card first, then your original photo(s) (each on a
1080x1350 slide with a soft blurred background, nothing cropped). In the two-step flow add `+photo` to the screenshot
caption (`meme +photo`) or to the caption of the photos you send afterwards. The draft footer says "carousel: card + N
original photo(s)". If the Threads carousel fails, Threads gets the card alone.

## Theatre releases reel (v29)
`theatre:` (also `week:`) + your weekly list as an album of posters, in the same order as the films:
title line with the dates in brackets, optional intro line, industry headings (TELUGU / TAMIL / MALAYALAM / KANNADA),
then `Title – Genre – Date` with a description line under each film. Optional lines under a film: `Director: ...`,
`Cast: ...`, `Music: ...`. Missing credits are read from the description by Gemini (one call; nothing is guessed).
The Reel: a title slide ("In theatres THIS WEEK", the dates, film count), then one slide per film in your order
(poster, name, genre + date, director, cast, music director, short description), then the outro. The caption is your
own pasted text plus a closing question and 5 hashtags (or write your own after a --- line).

## Reel templates update (v30)
- **Theatre releases:** details (title, date chip, genre, director / cast / music, description) sit above the poster so
  Instagram's channel name and caption never cover them; logo + FOLLOW on the bottom strip; slide length follows the text.
- **News:** the picture is shown clean (no text on it) with the headline / points in a panel below; no numbering;
  one slide per line you write (no 4-slide cap, up to 10 pictures).
- **Weekly roundup (new):** `roundup:` (also `weekly:` / `recap:`). First line = date range, then one story per line,
  optional `| one-line detail`. Each slide shows an industry tag (TAMIL CINEMA ...), auto-detected or set with a
  `Tamil:` / `Telugu:` / `Kannada:` / `Malayalam:` prefix. Photos match stories in order.
- Pictures grow to fill the free height; wide photos are cropped taller.
- **Voice-over (off):** `voiceover.py` is included but only used if a request has a line saying `voice`.
  Not enabled for now; no extra install needed.

## Magazine picture cards (v31)
- Picture posts (the card made from a photo / screenshot you send) now use `card_styles.py`: serif mixed-case headline
  (DM Serif Display), a short description from the post text (DM Sans), no blank band at the bottom.
- Portrait picture -> full-bleed overlay style. Landscape / square picture -> framed style.
- Fonts added to assets/fonts: DMSerifDisplay-Regular.ttf, DMSans.ttf (SIL OFL).
- Set the variable `PHOTO_CARD_STYLE=classic` to bring back the old all-caps card. If the new card ever errors it falls
  back to the old one automatically.
- Text-only cards: `card_styles.make_story_card` (editorial / split / classic) is included but not switched on.

## Key points on picture cards (v32)
- The picture card no longer repeats the post text: it shows the headline plus 3 (up to 4) short key points.
  Gemini writes the points (<= 12 words, no handles / hashtags / questions); if Gemini fails they are cut from the post's
  own sentences (@handles become names, the all-caps first line and the "tell us in the comments" lines are skipped).
- The industry tag is also detected from the key points and the full post (e.g. Rajinikanth -> Tamil Cinema).
- The category label sits on a dark chip and the bottom fade is taller on bright pictures, so text stays readable.

## Post + photo carousel (v33)
- `post:` (or just `post` with a screenshot) = one card, as before.
- `post+photo` = card + your original photo(s) as swipe slides. Same flag as `meme+photo`.
  - Screenshot with caption `post+photo`: I write the post, then you send the picture(s) as ONE album - the first
    becomes the card, all of them follow as swipe slides.
  - Photo(s) with a caption `post+photo: your description` (or `+photo` on the first line, text below): card from the
    first photo, all photos follow as swipe slides.
- Carousel cards (post and meme) get a small SWIPE >>> hint at the bottom centre (graphic_gen.add_swipe_hint).
- Instagram / Facebook post it as a carousel; Threads gets the card only.

## Picture card tweaks (v34)
- Headline is smaller; at most 3 key points; a very short post still gets at least 1 point.
- The category chip (CINEMA NEWS / BOX OFFICE ...) moved to the bottom-left footer; the "SOUTH INDIAN CINEMA" tagline is gone.
  The SWIPE hint sits in the middle of the same row, the FOLLOW pill on the right.

## Badge swap (v35)
- Picture cards: the category badge (CINEMA NEWS / BOX OFFICE ...) is now top-right; the industry badge
  (TAMIL CINEMA / TELUGU CINEMA ...) is bottom-left.

## Portrait and landscape (v36)
- Portrait pictures use the full-bleed overlay layout, landscape / square pictures the framed layout. Both share the same
  badges (category top-right, industry bottom-left), smaller headline, up to 3 key points and the SWIPE hint on carousels.
