import asyncio
import csv
import os
import re
import time
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor
from playwright.async_api import async_playwright
from playwright_stealth import stealth_sync

# =============================================
# CONFIGURATION
# =============================================

BLOCK_PATTERNS = ["doubleclick", "adservice", "googlesyndication", "ads", "adserver", "cookie", "consent"]
MAX_INTERNAL_LINKS = 5
MAX_THREADS = 10
PAGE_TIMEOUT = 60000  # dinaikkan jadi 60 detik
WAIT_FOR_LOAD_TIMEOUT = 10000  # waktu tunggu ekstra 10 detik setelah load
CLOUDFLARE_CHECK_KEYWORDS = ["Checking your browser", "Just a moment", "Cloudflare"]

# =============================================
# HELPER FUNCTIONS
# =============================================

def ensure_http(url):
    if not url.startswith(('http://', 'https://')):
        return 'http://' + url
    return url

def sanitize_filename(url):
    return re.sub(r'[^\w\-_\. ]', '_', url)

async def block_ads_and_cookies(page):
    async def route_intercept(route):
        if any(resource in route.request.url.lower() for resource in BLOCK_PATTERNS):
            await route.abort()
        else:
            await route.continue_()
    await page.route("**/*", route_intercept)

async def wait_for_page_stable(page):
    try:
        await page.wait_for_load_state('networkidle', timeout=PAGE_TIMEOUT)
        await asyncio.sleep(WAIT_FOR_LOAD_TIMEOUT / 1000)  # tunggu ekstra
    except Exception as e:
        print(f"⚠️  Halaman tidak stabil sepenuhnya: {e}")

async def detect_and_bypass_cloudflare(page):
    try:
        content = await page.content()
        if any(keyword.lower() in content.lower() for keyword in CLOUDFLARE_CHECK_KEYWORDS):
            print("⚡ Deteksi Cloudflare challenge, menunggu 5 detik...")
            await asyncio.sleep(5)
            await page.reload()
            await wait_for_page_stable(page)
    except Exception as e:
        print(f"⚠️  Gagal bypass Cloudflare: {e}")

async def process_domain(domain, output_folder):
    url = ensure_http(domain)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(locale='id-ID', user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/113.0.0.0 Safari/537.36"
        ))
        # Apply stealth mode here
        stealth_sync(context)
        page = await context.new_page()

        try:
            await block_ads_and_cookies(page)

            await page.goto(url, timeout=PAGE_TIMEOUT)
            await wait_for_page_stable(page)
            await detect_and_bypass_cloudflare(page)

            sanitized_name = sanitize_filename(domain)
            os.makedirs(output_folder, exist_ok=True)
            await page.screenshot(path=os.path.join(output_folder, f"{sanitized_name}_home.png"))
            print(f"✅ Screenshot homepage {url}")

            domain_name = urlparse(url).netloc
            links = await page.locator('a').evaluate_all(
                '(elements) => elements.map(e => e.href)'
            )
            internal_links = [link for link in links if urlparse(link).netloc == domain_name]
            internal_links = list(set(internal_links))[:MAX_INTERNAL_LINKS]

            for idx, link in enumerate(internal_links):
                try:
                    await page.goto(link, timeout=PAGE_TIMEOUT)
                    await wait_for_page_stable(page)
                    await detect_and_bypass_cloudflare(page)

                    await page.screenshot(path=os.path.join(output_folder, f"{sanitized_name}_page{idx+1}.png"))
                    print(f"✅ Screenshot {link}")
                except Exception as e:
                    print(f"⚠️  Error visiting {link}: {e}")

        except Exception as e:
            print(f"❌ Error processing {domain}: {e}")
        finally:
            await browser.close()

def run_in_thread(domain, output_folder):
    asyncio.run(process_domain(domain, output_folder))

def read_domains_from_csv(csv_file):
    domains = []
    with open(csv_file, newline='') as csvfile:
        reader = csv.reader(csvfile)
        for row in reader:
            domains.append(row[0])
    return domains

def crawl_from_csv(csv_file, output_folder):
    domains = read_domains_from_csv(csv_file)
    if not domains:
        print("⚠️  Tidak ada domain ditemukan di CSV.")
        return
    
    max_threads = min(MAX_THREADS, len(domains))
    with ThreadPoolExecutor(max_threads) as executor:
        executor.map(lambda domain: run_in_thread(domain, output_folder), domains)

# =============================================
# MAIN ENTRY
# =============================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Crawl dan screenshot dari daftar domain di CSV.")
    parser.add_argument('--csv', required=True, help='Path ke file CSV')
    parser.add_argument('--output', required=True, help='Folder output untuk screenshot')

    args = parser.parse_args()

    try:
        crawl_from_csv(args.csv, args.output)
    except KeyboardInterrupt:
        print("\n🛑 Program dihentikan oleh user (CTRL+C)")

# contoh penggunaan
# crawling_screenshot.py --csv judi.csv --output judi 