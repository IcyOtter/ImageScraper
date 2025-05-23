import os
import requests
from bs4 import BeautifulSoup
from tqdm import tqdm
from urllib.parse import urlparse, unquote

HEADERS = {"User-Agent": "Mozilla/5.0"}
SAVE_DIR = "motherless_downloads"
os.makedirs(SAVE_DIR, exist_ok=True)


def sanitize_filename_from_url(url):
    path = urlparse(url).path  # /videos/FC64A05.mp4
    return os.path.basename(path)  # FC64A05.mp4

def download_file(url, filename=None):
    if not filename:
        filename = sanitize_filename_from_url(url)

    print(f"Downloading {url}")
    response = requests.get(url, headers=HEADERS, stream=True)
    total = int(response.headers.get('content-length', 0))

    save_path = os.path.join(SAVE_DIR, filename)

    with open(save_path, 'wb') as file, tqdm(
        desc=filename,
        total=total,
        unit='B',
        unit_scale=True,
        unit_divisor=1024,
    ) as bar:
        for data in response.iter_content(chunk_size=1024):
            size = file.write(data)
            bar.update(size)

def download_image_page(url):
    soup = BeautifulSoup(requests.get(url, headers=HEADERS).text, 'html.parser')
    img = soup.select_one('#motherless-media-image')
    if img:
        src = img.get('src')
        filename = sanitize_filename_from_url(src)
        download_file(src, filename)

def download_video_page(url):
    soup = BeautifulSoup(requests.get(url, headers=HEADERS).text, 'html.parser')
    source = soup.select_one('video source')
    if source:
        src = source.get('src')
        filename = sanitize_filename_from_url(src)
        download_file(src, filename)

def download_gallery_page(url):
    print(f"Downloading gallery from: {url}")
    response = requests.get(url, headers=HEADERS)
    soup = BeautifulSoup(response.text, 'html.parser')

    gallery_items = soup.select('div.desktop-thumb[data-codename]')
    print(f"Found {len(gallery_items)} gallery items")

    for item in gallery_items:
        codename = item.get('data-codename')
        mediatype = item.get('data-mediatype', 'image')

        if not codename:
            print("Missing codename, skipping.")
            continue

        if mediatype == "video":
            # Visit the actual video page
            video_page_url = f"https://motherless.com/{codename}"
            print(f"Fetching real video from: {video_page_url}")
            video_page = requests.get(video_page_url, headers=HEADERS)
            video_soup = BeautifulSoup(video_page.text, "html.parser")
            source = video_soup.select_one("video source")
            if source and source.get("src"):
                video_url = source["src"]
                filename = sanitize_filename_from_url(video_url)
                download_file(video_url, filename)
            else:
                print(f"Could not extract video from: {video_page_url}")
        else:
            # It's a JPG image
            file_url = f"https://cdn5-images.motherlessmedia.com/images/{codename}.jpg"
            filename = sanitize_filename_from_url(file_url)
            print(f"Downloading: {file_url}")
            download_file(file_url, filename)


def download_motherless(url):
    r = requests.get(url, headers=HEADERS)
    soup = BeautifulSoup(r.text, 'html.parser')

    if soup.select_one('#motherless-media-image'):
        download_image_page(url)
    elif soup.select_one('video source'):
        download_video_page(url)
    elif soup.select('div[data-file-url]'):
        download_gallery_page(url)
    else:
        print("Content type not recognized.")

# Example usage
if __name__ == "__main__":
    url = input("Enter a URL: ")  # Replace with actual URL
    download_motherless(url)






# Test Motherless URL
# https://motherless.com/GIE4DFD05 Gallery
# https://motherless.com/9C242C2 Image
# https://motherless.com/D3C8217 Video