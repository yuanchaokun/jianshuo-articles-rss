"""Scrape X Articles by @jianshuo and emit RSS XML."""
import asyncio
import os
import sys
from datetime import datetime, timezone
from playwright.async_api import async_playwright
from feedgen.feed import FeedGenerator

AUTH_TOKEN = os.environ["TWITTER_AUTH_TOKEN"]
USERNAME = os.environ.get("X_USERNAME", "jianshuo")
MAX_ARTICLES = int(os.environ.get("MAX_ARTICLES", "20"))
OUT_PATH = os.environ.get("OUT_PATH", "docs/feed.xml")


async def scrape():
    debug_dir = "docs/debug"
    os.makedirs(debug_dir, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        ctx = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            locale="en-US",
            timezone_id="Asia/Shanghai",
        )
        # Anti-bot detection
        await ctx.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        """)
        await ctx.add_cookies([{
            "name": "auth_token",
            "value": AUTH_TOKEN,
            "domain": ".x.com",
            "path": "/",
            "secure": True,
            "httpOnly": True,
        }])
        page = await ctx.new_page()

        # 1. Articles list
        print(f"[1/3] Loading articles list for @{USERNAME}", flush=True)
        await page.goto(
            f"https://x.com/{USERNAME}/articles",
            wait_until="domcontentloaded",
            timeout=45000,
        )
        # Wait for either the tab content or a login wall to render
        try:
            await page.wait_for_selector('a[href*="/status/"], [data-testid="loginButton"]', timeout=20000)
        except Exception:
            pass
        await page.wait_for_timeout(3000)

        # Always dump a screenshot+html on the list page for diagnosis
        try:
            await page.screenshot(path=f"{debug_dir}/articles-list.png", full_page=False)
            html = await page.content()
            with open(f"{debug_dir}/articles-list.html", "w") as f:
                f.write(html[:200000])
            print(f"  saved debug to {debug_dir}/ (html {len(html)} chars)", flush=True)
        except Exception as e:
            print(f"  debug capture failed: {e}", flush=True)

        # Detect logged-out state
        is_logged_out = await page.evaluate(
            '!!document.querySelector(\'[data-testid="loginButton"]\') '
            '|| document.body.innerText.includes("Sign in to X")'
        )
        if is_logged_out:
            print("ERROR: page shows login wall — cookie rejected by X", flush=True)

        status_urls = await page.evaluate("""
            () => Array.from(new Set(
                Array.from(document.querySelectorAll('a[href*="/status/"]'))
                    .map(a => a.href.split('?')[0].replace(/\\/analytics$/, ''))
                    .filter(h => /\\/status\\/\\d+$/.test(h))
            ))
        """)
        status_urls = status_urls[:MAX_ARTICLES]
        print(f"  found {len(status_urls)} article(s)", flush=True)

        if not status_urls:
            print("WARN: zero articles found — check docs/debug/articles-list.png", flush=True)

        # 2. Each article detail (trust the /articles tab as the filter)
        articles = []
        for i, url in enumerate(status_urls, 1):
            print(f"[2/3] ({i}/{len(status_urls)}) {url}", flush=True)
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                # Wait until the article body or a fallback element appears
                try:
                    await page.wait_for_selector('article, h1', timeout=15000)
                except Exception:
                    pass
                await page.wait_for_timeout(3000)

                # Dump first article's debug snapshot for diagnostics
                if i == 1:
                    try:
                        await page.screenshot(path=f"{debug_dir}/article-1.png", full_page=True)
                        html = await page.content()
                        with open(f"{debug_dir}/article-1.html", "w") as f:
                            f.write(html[:200000])
                    except Exception:
                        pass

                data = await page.evaluate("""
                    () => {
                        const titleEl = document.querySelector('h1');
                        const articleEl = document.querySelector('article');
                        const dateEl = document.querySelector('time');
                        const text = articleEl?.innerText || '';
                        const cleaned = text
                            .split('\\n')
                            .filter(l => {
                                const t = l.trim();
                                if (!t) return false;
                                if (['Article','Follow','Reply','Repost','Share'].includes(t)) return false;
                                return true;
                            })
                            .join('\\n');
                        return {
                            title: titleEl?.innerText?.trim() || '',
                            content: cleaned,
                            contentLen: cleaned.length,
                            date: dateEl?.getAttribute('datetime') || ''
                        };
                    }
                """)
                print(f"  title={data['title'][:60]!r} content_len={data['contentLen']}", flush=True)

                if not data["title"] or data["contentLen"] < 100:
                    print(f"  skipped (title/content too short)", flush=True)
                    continue

                articles.append({"url": url, **data})
            except Exception as e:
                print(f"  error: {e}", flush=True)

        await browser.close()

        # 3. Build RSS
        print(f"[3/3] Writing feed with {len(articles)} article(s) to {OUT_PATH}", flush=True)
        fg = FeedGenerator()
        fg.id(f"https://x.com/{USERNAME}/articles")
        fg.title(f"X Articles — @{USERNAME}")
        fg.link(href=f"https://x.com/{USERNAME}/articles", rel="alternate")
        fg.description(f"X 长文章（Articles）by @{USERNAME}")
        fg.language("zh-cn")
        fg.author({"name": USERNAME})

        for art in articles:
            fe = fg.add_entry()
            fe.id(art["url"])
            fe.title(art["title"])
            fe.link(href=art["url"])
            fe.content(art["content"].replace("\n", "<br>\n"), type="html")
            if art["date"]:
                try:
                    dt = datetime.fromisoformat(art["date"].replace("Z", "+00:00"))
                    fe.pubDate(dt)
                except Exception:
                    pass

        os.makedirs(os.path.dirname(OUT_PATH) or ".", exist_ok=True)
        fg.rss_file(OUT_PATH, pretty=True)

        # Stamp last-update sidecar for debugging
        with open(os.path.join(os.path.dirname(OUT_PATH) or ".", "last-update.txt"), "w") as f:
            f.write(f"{datetime.now(timezone.utc).isoformat()}\n{len(articles)} articles\n")

        return len(articles)


if __name__ == "__main__":
    n = asyncio.run(scrape())
    # Don't exit 1 even on 0 — let workflow commit debug artifacts
    print(f"DONE: wrote {n} article(s)")
