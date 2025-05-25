import os
import re
import asyncio
import aiohttp
from pathlib import Path
from tqdm.asyncio import tqdm

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Referer": "https://boards.4chan.org/",
}

SUPPORTED_EXTS = ['.jpg', '.png', '.gif', '.webm']

def parse_4chan_thread_url(url):
    match = re.search(r'boards\.4chan(?:nel)?\.org/(\w+)/thread/(\d+)', url)
    if not match:
        raise ValueError("Invalid 4chan thread URL")
    return match.group(1), match.group(2)

async def fetch_4chan_thread_data(session, board, thread_id):
    api_url = f"https://a.4cdn.org/{board}/thread/{thread_id}.json"
    async with session.get(api_url) as resp:
        if resp.status != 200:
            raise Exception(f"Failed to fetch thread data ({resp.status})")
        return await resp.json()

def get_4chan_media_url(board, tim, ext):
    return f"https://i.4cdn.org/{board}/{tim}{ext}"

async def download_file(session, url, save_path, sem):
    async with sem:  # limit concurrent downloads
        for attempt in range(3):
            try:
                async with session.get(url) as resp:
                    if resp.status == 429:
                        retry_after = int(resp.headers.get("Retry-After", 2 ** attempt))
                        await asyncio.sleep(retry_after)
                        continue
                    elif resp.status != 200:
                        print(f"Failed ({resp.status}): {url}")
                        return False
                    data = await resp.read()
                    with open(save_path, "wb") as f:
                        f.write(data)
                    return True
            except Exception as e:
                print(f"Error downloading {url}: {e}")
                await asyncio.sleep(2 ** attempt)
        return False

async def download_4chan_thread(url, max_concurrent=5):
    board, thread_id = parse_4chan_thread_url(url)
    folder = Path("4chan") / board / thread_id
    folder.mkdir(parents=True, exist_ok=True)

    connector = aiohttp.TCPConnector(limit=10)
    timeout = aiohttp.ClientTimeout(total=None)
    sem = asyncio.Semaphore(max_concurrent)

    async with aiohttp.ClientSession(headers=HEADERS, connector=connector, timeout=timeout) as session:
        thread_data = await fetch_4chan_thread_data(session, board, thread_id)
        posts = thread_data.get("posts", [])
        downloads = []

        for post in posts:
            if "tim" in post and "ext" in post:
                ext = post["ext"].lower()
                if ext in SUPPORTED_EXTS:
                    url = get_4chan_media_url(board, post["tim"], ext)
                    save_path = folder / f"{post['tim']}{ext}"
                    downloads.append((url, save_path))

        print(f"Found {len(downloads)} files. Downloading...")

        tasks = [
            download_file(session, url, save_path, sem)
            for url, save_path in downloads
        ]

        for f in tqdm(asyncio.as_completed(tasks), total=len(tasks)):
            await f

        print(f"✅ Download complete: {folder}")

if __name__ == "__main__":
    try:
        url = input("Enter a 4chan thread URL: ").strip()
        if not url:
            raise ValueError("URL is required.")
        asyncio.run(download_4chan_thread(url))
    except Exception as e:
        print(f"❌ Error: {e}")




# Test Link
# https://boards.4chan.org/s/thread/22176523