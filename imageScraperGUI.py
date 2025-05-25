import sys
import re
import asyncio
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit,
    QComboBox, QProgressBar
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from pathlib import Path
import aiohttp
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
