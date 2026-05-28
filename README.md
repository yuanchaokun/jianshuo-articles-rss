# jianshuo-articles-rss

Hourly scrape of [@jianshuo](https://x.com/jianshuo) **X Articles** (long-form posts) into an RSS feed.

- Runs on GitHub Actions (free)
- Hosted via Cloudflare Pages (free)
- Subscribe in any RSS reader (e.g. DEVONthink)

## Feed

`https://<your-pages-domain>/feed.xml`

## Architecture

```
GitHub Actions (hourly cron)
  → Playwright + Chromium
  → scrape https://x.com/jianshuo/articles
  → write docs/feed.xml
  → git push
Cloudflare Pages auto-deploys docs/ → CDN
```

## Why this exists

RSSHub does not currently expose X's Articles feature (only regular tweets via `/twitter/user/<id>`).
This repo scrapes the public Articles tab directly.

## Cookie

The auth cookie sits in GitHub Actions secret `TWITTER_AUTH_TOKEN` (the value of `auth_token` cookie
of a logged-in X account). Update it when it expires:

```bash
gh secret set TWITTER_AUTH_TOKEN --repo <user>/jianshuo-articles-rss
```
