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
from dotenv import load_dotenv
import praw

load_dotenv()

reddit = praw.Reddit(
    client_id=os.getenv("REDDIT_CLIENT_ID"),
    client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
    user_agent=os.getenv("REDDIT_USER_AGENT"),
    username=os.getenv("REDDIT_USERNAME"),
    password=os.getenv("REDDIT_PASSWORD")
)

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
    base_folder = Path("ISdownloads/erome")
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
        folder = self.base_folder / gallery_id
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
    base_folder = Path("ISdownloads/4chan")
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
        folder = self.base_folder / board / thread_id
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
    base_folder = Path("ISdownloads/fapello")
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
        folder = self.base_folder / username
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

class DownloadMotherlessThread(QThread):
    base_folder = Path("ISdownloads/motherless")
    progress_updated = pyqtSignal(int)
    log_message = pyqtSignal(str)

    def __init__(self, url):
        super().__init__()
        self.url = url

    def run(self):
        try:
            self.download_motherless(self.url)
        except Exception as e:
            self.log_message.emit(f"❌ Error: {e}")

    def sanitize_filename(self, url):
        path = urlparse(url).path
        return os.path.basename(path)

    def download_file(self, url, folder):
        if not url:
            self.log_message.emit("⚠️ Skipping empty URL.")
            return
        filename = self.sanitize_filename(url)
        path = folder / filename

        r = requests.get(url, headers=HEADERS, stream=True)
        total = int(r.headers.get("content-length", 0))
        with open(path, 'wb') as f:
            downloaded = 0
            for chunk in r.iter_content(1024):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        self.progress_updated.emit(int(downloaded * 100 / total))

    def download_motherless(self, url):
        folder = self.base_folder / urlparse(url).path.split("/")[-1]
        folder.mkdir(parents=True, exist_ok=True)
        soup = BeautifulSoup(requests.get(url, headers=HEADERS).text, 'html.parser')

        if soup.select_one('#motherless-media-image'):
            img = soup.select_one('#motherless-media-image')
            src = img.get('src')
            self.log_message.emit(f"🖼️ Downloading image: {src}")
            self.download_file(src, folder)
        elif soup.select_one('video source'):
            src = soup.select_one('video source').get('src')
            self.log_message.emit(f"🎞️ Downloading video: {src}")
            self.download_file(src, folder)
        elif soup.select('div[data-codename]'):
            items = soup.select('div[data-codename]')
            valid_items = [item for item in items if item.get("data-codename")]
            self.log_message.emit(f"📁 Found {len(valid_items)} gallery items")
            for i, div in enumerate(valid_items):
                codename = div.get("data-codename")
                mediatype = div.get("data-mediatype", "image")
                if mediatype == "video":
                    video_page_url = f"https://motherless.com/{codename}"
                    page = requests.get(video_page_url, headers=HEADERS)
                    page_soup = BeautifulSoup(page.text, 'html.parser')
                    source = page_soup.select_one("video source")
                    if source and source.get("src"):
                        file_url = source.get("src")
                        self.log_message.emit(f"⬇️ Downloading: {file_url}")
                        self.download_file(file_url, folder)
                else:
                    # Check for gif first, fallback to jpg
                    gif_url = f"https://cdn5-images.motherlessmedia.com/images/{codename}.gif"
                    jpg_url = f"https://cdn5-images.motherlessmedia.com/images/{codename}.jpg"
                    head = requests.head(gif_url, headers=HEADERS)
                    file_url = gif_url if head.status_code == 200 else jpg_url
                    self.log_message.emit(f"⬇️ Downloading: {file_url}")
                    self.download_file(file_url, folder)
                self.progress_updated.emit(int((i + 1) * 100 / len(valid_items)))
        else:
            self.log_message.emit("❌ Content type not recognized.")

        self.log_message.emit("✅ Finished downloading Motherless content")

class DownloadRedditThread(QThread):
    base_folder = Path("ISdownloads/reddit")
    progress_updated = pyqtSignal(int)
    log_message = pyqtSignal(str)

    def __init__(self, subreddit, limit):
        super().__init__()
        self.subreddit = subreddit
        self.limit = limit

    def sanitize_filename(self, url):
        return os.path.basename(urlparse(url).path.split("?")[0])

    def run(self):
        try:
            self.download_images_from_subreddit(self.subreddit, self.limit)
        except Exception as e:
            self.log_message.emit(f"❌ Error: {e}")

    def download_images_from_subreddit(self, subreddit_name, limit):
        subreddit = reddit.subreddit(subreddit_name)
        folder = self.base_folder / subreddit_name
        folder.mkdir(parents=True, exist_ok=True)

        count = 0
        posts = list(subreddit.hot(limit=100))

        for post in posts:
            url = post.url
            if any(url.lower().endswith(ext) for ext in SUPPORTED_EXTS):
                try:
                    response = requests.get(url, stream=True)
                    response.raise_for_status()
                    filename = self.sanitize_filename(url)
                    path = folder / filename
                    with open(path, 'wb') as f:
                        for chunk in response.iter_content(1024):
                            f.write(chunk)
                    self.log_message.emit(f"🖼️ Downloaded: {filename}")
                    count += 1
                    self.progress_updated.emit(int(count * 100 / limit))
                    if count >= limit:
                        break
                except Exception as e:
                    self.log_message.emit(f"❌ Failed to download {url}: {e}")

        self.log_message.emit(f"✅ Downloaded {count} image(s) from r/{subreddit_name}")

class UniversalDownloaderGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Universal Downloader")
        self.setGeometry(100, 100, 600, 400)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        from PyQt5.QtWidgets import QMenuBar, QMenu, QAction

        self.current_theme = "dark"

        self.menu_bar = QMenuBar(self)
        view_menu = self.menu_bar.addMenu("View")

        self.toggle_theme_action = QAction("Switch to Light Mode", self)
        self.toggle_theme_action.triggered.connect(self.toggle_theme_from_menu)
        view_menu.addAction(self.toggle_theme_action)

        layout.setMenuBar(self.menu_bar)

        self.apply_dark_theme()

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
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.progress_bar)

        # Log Output
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        layout.addWidget(self.log_output)

        self.setLayout(layout)

    def apply_dark_theme(self):
        self.setStyleSheet("""
            QWidget {
                background-color: #2b2b2b;
                color: #ffffff;
                font-family: Arial;
                font-size: 13px;
            }
            QLineEdit, QTextEdit, QComboBox, QProgressBar {
                background-color: #3c3f41;
                border: 1px solid #5c5c5c;
                padding: 4px;
                color: #ffffff;
            }
            QPushButton {
                background-color: #555555;
                border: 1px solid #888888;
                padding: 5px 10px;
                color: #ffffff;
            }
            QPushButton:hover {
                background-color: #777777;
            }
        """)

    def apply_light_theme(self):
        self.setStyleSheet("""
            QWidget {
                background-color: #f0f0f0;
                color: #000000;
                font-family: Arial;
                font-size: 13px;
            }
            QLineEdit, QTextEdit, QComboBox, QProgressBar {
                background-color: #ffffff;
                border: 1px solid #cccccc;
                padding: 4px;
                color: #000000;
            }
            QPushButton {
                background-color: #dddddd;
                border: 1px solid #aaaaaa;
                padding: 5px 10px;
                color: #000000;
            }
            QPushButton:hover {
                background-color: #bbbbbb;
            }
        """)

    def toggle_theme_from_menu(self):
        if self.current_theme == "dark":
            self.apply_light_theme()
            self.current_theme = "light"
            self.toggle_theme_action.setText("Switch to Dark Mode")
        else:
            self.apply_dark_theme()
            self.current_theme = "dark"
            self.toggle_theme_action.setText("Switch to Light Mode")

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

        base_folder = Path("ISdownloads")
        base_folder.mkdir(exist_ok=True)

        if "4chan.org" in url:
            Download4chanThread.base_folder = base_folder / "4chan"
            self.download_thread = Download4chanThread(url)
        elif "erome.com" in url:
            DownloadEromeThread.base_folder = base_folder / "erome"
            self.download_thread = DownloadEromeThread(url)
        elif "fapello.com" in url:
            media_type = self.media_type_dropdown.currentText()
            DownloadFapelloThread.base_folder = base_folder / "fapello"
            self.download_thread = DownloadFapelloThread(url, media_type)
        elif "motherless.com" in url:
            DownloadMotherlessThread.base_folder = base_folder / "motherless"
            self.download_thread = DownloadMotherlessThread(url)
        elif re.match(r"^(https?://)?(www\.)?reddit\.com|^r/", url):
            subreddit = url.split("/")[-1] if "/" in url else url.replace("r/", "").strip()
            try:
                limit = int(self.limit_input.text().strip())
            except ValueError:
                limit = 10  # Default
            DownloadRedditThread.base_folder = base_folder / "reddit"
            self.download_thread = DownloadRedditThread(subreddit, limit)
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
