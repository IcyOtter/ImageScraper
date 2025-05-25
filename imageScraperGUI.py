import sys
import os
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import re
import asyncio
import requests
from bs4 import BeautifulSoup
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit,
    QComboBox, QProgressBar
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from pathlib import Path
import aiohttp
from tqdm.asyncio import tqdm
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Referer": "https://boards.4chan.org/",
}

SUPPORTED_EXTS = ['.jpg', '.png', '.gif', '.webm']

class DownloadEromeThread(QThread):
    progress_updated = pyqtSignal(int)
    log_message = pyqtSignal(str)

    def __init__(self, url):
        super().__init__()
        self.url = url

    def sanitize_filename(self, url):
        path = urlparse(url).path
        return Path(path).name

    def download_file(self, url, folder, referer=None):
        filename = self.sanitize_filename(url)
        path = folder / filename
        headers = HEADERS.copy()
        if referer:
            headers["Referer"] = referer

        try:
            with requests.get(url, stream=True, headers=headers, timeout=30) as response:
                response.raise_for_status()
                total = int(response.headers.get("content-length", 0))

                with open(path, "wb") as f:
                    downloaded = 0
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total:
                                self.progress_updated.emit(int(downloaded * 100 / total))
            return True
        except Exception as e:
            self.log_message.emit(f"❌ Failed to download {url}: {e}")
            return False

    def run(self):
        try:
            self.scrape_erome_gallery(self.url)
        except Exception as e:
            self.log_message.emit(f"❌ Error: {e}")

    def scrape_erome_gallery(self, url):
        self.log_message.emit(f"Scraping gallery: {url}")
        response = requests.get(url, headers=HEADERS)
        if response.status_code != 200:
            self.log_message.emit(f"❌ Failed to access gallery ({response.status_code})")
            return

        soup = BeautifulSoup(response.text, "html.parser")
        gallery_id = url.rstrip("/").split("/")[-1]
        folder = Path("erome") / gallery_id
        folder.mkdir(parents=True, exist_ok=True)

        media_urls = set()
        for div in soup.select('div.img[data-src]'):
            src = div.get('data-src')
            if src and src.startswith("https"):
                media_urls.add(src)
        for source in soup.select('video > source[src]'):
            src = source.get('src')
            if src and src.startswith("https"):
                media_urls.add(src)

        media_urls = list(media_urls)
        self.log_message.emit(f"Found {len(media_urls)} media files.")

        for i, url in enumerate(media_urls):
            self.download_file(url, folder, referer=self.url)
            self.progress_updated.emit(int((i + 1) * 100 / len(media_urls)))

        self.log_message.emit(f"✅ Finished downloading to: {folder.resolve()}")


class Download4chanThread(QThread):
    progress_updated = pyqtSignal(int)
    log_message = pyqtSignal(str)

    def __init__(self, url):
        super().__init__()
        self.url = url

    def run(self):
        asyncio.run(self.download_4chan_thread(self.url))

    def parse_4chan_thread_url(self, url):
        match = re.search(r'boards\.4chan(?:nel)?\.org/(\w+)/thread/(\d+)', url)
        if not match:
            raise ValueError("Invalid 4chan thread URL")
        return match.group(1), match.group(2)

    async def fetch_4chan_thread_data(self, session, board, thread_id):
        api_url = f"https://a.4cdn.org/{board}/thread/{thread_id}.json"
        async with session.get(api_url) as resp:
            if resp.status != 200:
                raise Exception(f"Failed to fetch thread data ({resp.status})")
            return await resp.json()

    def get_4chan_media_url(self, board, tim, ext):
        return f"https://i.4cdn.org/{board}/{tim}{ext}"

    async def download_file(self, session, url, save_path, sem):
        async with sem:
            for attempt in range(3):
                try:
                    async with session.get(url) as resp:
                        if resp.status == 429:
                            retry_after = int(resp.headers.get("Retry-After", 2 ** attempt))
                            await asyncio.sleep(retry_after)
                            continue
                        elif resp.status != 200:
                            self.log_message.emit(f"Failed ({resp.status}): {url}")
                            return False
                        data = await resp.read()
                        with open(save_path, "wb") as f:
                            f.write(data)
                        return True
                except Exception as e:
                    self.log_message.emit(f"Error downloading {url}: {e}")
                    await asyncio.sleep(2 ** attempt)
            return False

    async def download_4chan_thread(self, url, max_concurrent=5):
        board, thread_id = self.parse_4chan_thread_url(url)
        folder = Path("4chan") / board / thread_id
        folder.mkdir(parents=True, exist_ok=True)

        connector = aiohttp.TCPConnector(limit=10)
        timeout = aiohttp.ClientTimeout(total=None)
        sem = asyncio.Semaphore(max_concurrent)

        async with aiohttp.ClientSession(headers=HEADERS, connector=connector, timeout=timeout) as session:
            thread_data = await self.fetch_4chan_thread_data(session, board, thread_id)
            posts = thread_data.get("posts", [])
            downloads = []

            for post in posts:
                if "tim" in post and "ext" in post:
                    ext = post["ext"].lower()
                    if ext in SUPPORTED_EXTS:
                        url = self.get_4chan_media_url(board, post["tim"], ext)
                        save_path = folder / f"{post['tim']}{ext}"
                        downloads.append((url, save_path))

            total = len(downloads)
            if total == 0:
                self.log_message.emit("No downloadable media found.")
                return

            self.log_message.emit(f"Found {total} files. Starting download...")
            completed = 0

            tasks = [
                self.download_file(session, url, save_path, sem)
                for url, save_path in downloads
            ]

            for f in tqdm(asyncio.as_completed(tasks), total=total):
                await f
                completed += 1
                self.progress_updated.emit(int((completed / total) * 100))

            self.log_message.emit(f"✅ Download complete: {folder}")

class DownloadFapelloThread(QThread):
    progress_updated = pyqtSignal(int)
    log_message = pyqtSignal(str)

    def __init__(self, url, media_type):
        super().__init__()
        self.url = url
        self.media_type = media_type

    def run(self):
        try:
            self.scrape_fapello_profile(self.url, self.media_type)
        except Exception as e:
            self.log_message.emit(f"❌ Error: {e}")

    def sanitize_filename(self, url):
        return os.path.basename(urlparse(url).path.split("?")[0])

    def scrape_fapello_profile(self, profile_url, media_type):
        username = profile_url.rstrip("/").split("/")[-1]
        folder = Path("fapello") / username
        folder.mkdir(parents=True, exist_ok=True)

        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument(f"--user-agent={HEADERS['User-Agent']}")
        driver = webdriver.Chrome(options=chrome_options)

        self.log_message.emit(f"🔍 Opening profile: {profile_url}")
        driver.get(profile_url)
        time.sleep(2)

        last_height = driver.execute_script("return document.body.scrollHeight")
        scroll_attempts = 0

        while scroll_attempts < 30:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height
            scroll_attempts += 1

        soup = BeautifulSoup(driver.page_source, "html.parser")
        post_links = []

        for a in soup.select(f"a[href^='https://fapello.com/{username}/']"):
            parent = a.find_parent("div")
            has_play_icon = parent and parent.select_one("img[src*='icon-play.svg']")

            if media_type == "videos" and not has_play_icon:
                continue
            if media_type == "images" and has_play_icon:
                continue

            post_links.append(a.get("href"))

        media_urls = set()

        for post_url in set(post_links):
            try:
                self.log_message.emit(f"🔗 Opening post: {post_url}")
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
                self.log_message.emit(f"❌ Failed to scrape post {post_url}: {e}")

        driver.quit()

        self.log_message.emit(f"⬇️ Starting downloads for {len(media_urls)} files...")
        for i, url in enumerate(media_urls):
            try:
                r = requests.get(url, stream=True, timeout=30)
                r.raise_for_status()
                filename = self.sanitize_filename(url)
                path = folder / filename
                with open(path, "wb") as f:
                    for chunk in r.iter_content(1024 * 512):
                        f.write(chunk)
                self.progress_updated.emit(int((i + 1) * 100 / len(media_urls)))
            except Exception as e:
                self.log_message.emit(f"❌ Failed to download {url}: {e}")

        self.log_message.emit(f"✅ Finished downloading from profile: {username}")

class UniversalDownloaderGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Universal Downloader")
        self.setGeometry(100, 100, 600, 400)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        # URL Input
        url_layout = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Enter URL or subreddit (e.g. r/pics or https://boards.4chan.org/...)")
        self.url_input.textChanged.connect(self.update_controls_based_on_input)
        url_layout.addWidget(QLabel("Source:"))
        url_layout.addWidget(self.url_input)
        layout.addLayout(url_layout)

        # Dynamic Controls
        self.options_layout = QVBoxLayout()
        self.media_type_dropdown = QComboBox()
        self.media_type_dropdown.addItems(["images", "videos", "both"])
        self.media_type_dropdown.hide()

        self.filter_dropdown = QComboBox()
        self.filter_dropdown.addItems(["SFW", "NSFW", "Both"])
        self.filter_dropdown.hide()

        self.limit_input = QLineEdit()
        self.limit_input.setPlaceholderText("Image limit")
        self.limit_input.hide()

        self.options_layout.addWidget(self.media_type_dropdown)
        self.options_layout.addWidget(self.filter_dropdown)
        self.options_layout.addWidget(self.limit_input)
        layout.addLayout(self.options_layout)

        # Download button
        self.download_btn = QPushButton("Download")
        self.download_btn.clicked.connect(self.handle_download)
        layout.addWidget(self.download_btn)

        # Progress bar
        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)

        # Log Output
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        layout.addWidget(self.log_output)

        self.setLayout(layout)

    def update_controls_based_on_input(self):
        text = self.url_input.text().strip()

        self.media_type_dropdown.hide()
        self.filter_dropdown.hide()
        self.limit_input.hide()

        if re.match(r"^(https?://)?(www\.)?reddit\.com|^r/", text):
            self.filter_dropdown.show()
            self.limit_input.show()
        elif "fapello.com" in text:
            self.media_type_dropdown.show()
        elif "erome.com" in text or "motherless.com" in text or "4chan.org" in text:
            pass  # No extra options

    def handle_download(self):
        url = self.url_input.text().strip()
        self.log_output.append(f"Starting download for: {url}")

        if "4chan.org" in url:
            self.download_thread = Download4chanThread(url)
        elif "erome.com" in url:
            self.download_thread = DownloadEromeThread(url)
        elif "fapello.com" in url:
            media_type = self.media_type_dropdown.currentText()
            self.download_thread = DownloadFapelloThread(url, media_type)
        else:
            self.log_output.append("❌ Unsupported URL or feature not implemented yet.")
            return

        self.download_thread.progress_updated.connect(self.update_progress)
        self.download_thread.log_message.connect(self.log_output.append)
        self.download_thread.start()

    def update_progress(self, value):
        self.progress_bar.setValue(value)
        self.progress_bar.setFormat(f"Progress: {value}%")


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = UniversalDownloaderGUI()
    window.show()
    sys.exit(app.exec_())
