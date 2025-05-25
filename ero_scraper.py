import os
import requests
from bs4 import BeautifulSoup
from tqdm import tqdm
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor

# Global headers and session
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/122.0.0.0 Safari/537.36"
}
session = requests.Session()
session.headers.update(HEADERS)

def sanitize_filename(url):
    path = urlparse(url).path
    return os.path.basename(path)

def download_file(url, folder, referer=None):
    filename = sanitize_filename(url)
    path = os.path.join(folder, filename)

    headers = HEADERS.copy()
    if referer:
        headers["Referer"] = referer

    try:
        with session.get(url, stream=True, headers=headers, timeout=30) as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length", 0))

            with open(path, "wb") as f, tqdm(
                total=total,
                unit="B",
                unit_scale=True,
                unit_divisor=1024,
                desc=filename,
                initial=0
            ) as bar:
                for chunk in response.iter_content(chunk_size=1024 * 1024):  # 1MB chunks
                    if chunk:
                        f.write(chunk)
                        bar.update(len(chunk))
        return True
    except requests.exceptions.RequestException as e:
        print(f"❌ Failed to download {url}: {e}")
        return False

def download_all(media_urls, folder, referer):
    image_urls = [url for url in media_urls if not url.lower().endswith(".mp4")]
    video_urls = [url for url in media_urls if url.lower().endswith(".mp4")]

    # Download images in parallel
    with ThreadPoolExecutor(max_workers=12) as executor:
        executor.map(lambda u: download_file(u, folder, referer), image_urls)

    # Download videos sequentially
    for url in video_urls:
        download_file(url, folder, referer)


def download_erome_gallery(url):
    print(f"Scraping gallery: {url}")
    response = session.get(url)
    if response.status_code != 200:
        print(f"❌ Failed to access gallery ({response.status_code})")
        return

    soup = BeautifulSoup(response.text, "html.parser")
    gallery_id = url.rstrip("/").split("/")[-1]
    folder = os.path.join("erome", gallery_id)
    os.makedirs(folder, exist_ok=True)

    # Collect unique media URLs
    media_urls = set()

    # From div.img[data-src]
    for div in soup.select('div.img[data-src]'):
        src = div.get('data-src')
        if src and src.startswith("https"):
            media_urls.add(src)

    # From <video><source src="...">
    for source in soup.select('video > source[src]'):
        src = source.get('src')
        if src and src.startswith("https"):
            media_urls.add(src)

    media_urls = list(media_urls)
    print(f"Found {len(media_urls)} media files.")

    download_all(media_urls, folder, referer=url)

    print(f"✅ Finished downloading to: {os.path.abspath(folder)}")

if __name__ == "__main__":
    gallery_url = input("Enter the Erome gallery URL: ").strip()
    download_erome_gallery(gallery_url)

