import sys
import re
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit,
    QComboBox, QProgressBar, QFileDialog
)
from PyQt5.QtCore import Qt


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
        # This is where you would route to the appropriate threaded downloader.
        # For now, just simulate.
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Downloading...")
        # Add threaded download logic later
        self.progress_bar.setValue(100)
        self.log_output.append("✅ Download finished.")


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = UniversalDownloaderGUI()
    window.show()
    sys.exit(app.exec_())
