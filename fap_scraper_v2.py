import os
import re
import time
import requests
from bs4 import BeautifulSoup
from tqdm import tqdm
from urllib.parse import urlparse
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from concurrent.futures import ThreadPoolExecutor

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/122.0.0.0 Safari/537.36"
}

session = requests.Session()
session.headers.update(HEADERS)

def sanitize_filename(url):
    return os.path.basename(urlparse(url).path.split("?")[0])

def download_file(url, folder):
    if '_300px' in url:
        return  # Skip 300px versions
    filename = sanitize_filename(url)
    path = os.path.join(folder, filename)
    try:
        r = session.get(url, stream=True, timeout=30)
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        with open(path, "wb") as f, tqdm(
            total=total,
            unit="B",
            unit_scale=True,
            unit_divisor=1024,
            desc=filename
        ) as bar:
            for chunk in r.iter_content(1024 * 512):
                if chunk:
                    f.write(chunk)
                    bar.update(len(chunk))
        print(f"✅ Downloaded: {filename}")
    except Exception as e:
        print(f"❌ Failed to download {url}: {e}")

def extract_full_image_url(thumbnail_url):
    return re.sub(r'_(\d+)px(?=\.(jpg|jpeg|png))', '', thumbnail_url)

def scrape_fapello_profile(profile_url, media_type):
    username = profile_url.rstrip("/").split("/")[-1]
    folder = os.path.join("fapello", username)
    os.makedirs(folder, exist_ok=True)

    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument(f"--user-agent={HEADERS['User-Agent']}")
    driver = webdriver.Chrome(options=chrome_options)

    print(f"🔍 Opening profile: {profile_url}")
    driver.get(profile_url)
    time.sleep(2)

    last_height = driver.execute_script("return document.body.scrollHeight")
    scroll_attempts = 0
    max_scrolls = 50

    while scroll_attempts < max_scrolls:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height
        scroll_attempts += 1

    print("📸 Scanning fully loaded page")
    soup = BeautifulSoup(driver.page_source, "html.parser")
    post_links = []

    for a in soup.select("a[href^='https://fapello.com/" + username + "/']"):
        parent = a.find_parent("div")
        has_play_icon = parent and parent.select_one("img[src*='icon-play.svg']")

        if media_type == "videos" and not has_play_icon:
            continue
        if media_type == "images" and has_play_icon:
            continue

        post_links.append(a.get("href"))

    post_links = list(set(post_links))

    media_urls = set()

    for post_url in post_links:
        try:
            print(f"🔗 Opening post: {post_url}")
            driver.get(post_url)
            time.sleep(2)
            post_soup = BeautifulSoup(driver.page_source, "html.parser")

            if media_type in ("both", "images"):
                for img in post_soup.select("img[src*='/content/']"):
                    src = img.get("src")
                    if src and username in src and '_300px' not in src:
                        media_urls.add(src)

            if media_type in ("both", "videos"):
                for source in post_soup.select("video > source[src*='/content/']"):
                    src = source.get("src")
                    if src and username in src:
                        media_urls.add(src)

        except Exception as e:
            print(f"❌ Failed to scrape post {post_url}: {e}")

    driver.quit()

    print(f"⬇️ Starting parallel downloads for {len(media_urls)} files...")
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(download_file, url, folder) for url in media_urls]
        for future in futures:
            future.result()

    print(f"✅ Finished downloading {len(media_urls)} media files from profile: {username}")

if __name__ == "__main__":
    profile = input("Enter the Fapello profile URL (e.g. https://fapello.com/angelicfukdoll): ").strip()
    media_type = input("Download type (images / videos / both): ").strip().lower()
    if media_type not in ("images", "videos", "both"):
        media_type = "both"
    scrape_fapello_profile(profile, media_type)
