import time
import requests
import urllib3
from typing import List, Optional

from app import config

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


class WebsiteScraper:
    def __init__(self, base_url: str, cache_ttl_seconds: Optional[int] = None):
        self.base_url = base_url
        # None (the default) reads config.SCRAPER_CACHE_TTL_SECONDS at call
        # time rather than construction time, so tests can monkeypatch the
        # config value without needing to reconstruct the scraper — an
        # explicit int here (e.g. in a test) always wins over that default.
        self.cache_ttl_seconds = cache_ttl_seconds
        self.cache = {}  # url -> (text, cached_at_monotonic)

    def scrape_page(self, url: str) -> str:
        ttl = self.cache_ttl_seconds if self.cache_ttl_seconds is not None else config.SCRAPER_CACHE_TTL_SECONDS
        cached = self.cache.get(url)
        if cached is not None:
            text, cached_at = cached
            if time.monotonic() - cached_at < ttl:
                return text
        try:
            from bs4 import BeautifulSoup
            response = requests.get(url, timeout=10, verify=False, headers=HEADERS)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, "html.parser")
            for tag in soup(["script", "style", "nav", "footer"]):
                tag.decompose()
            text = soup.get_text()
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            text = " ".join(chunk for chunk in chunks if chunk)
            self.cache[url] = (text, time.monotonic())
            return text
        except Exception as e:
            return f"Error scraping {url}: {str(e)}"

    def get_school_info(self, pages: List[str] = None) -> str:
        if pages is None:
            pages = ["/"]
        all_content = []
        for page in pages:
            url = page if page.startswith("http") else self.base_url.rstrip("/") + "/" + page.lstrip("/")
            content = self.scrape_page(url)
            all_content.append(f'<scraped_page url="{url}">\n{content}\n</scraped_page>')
        return "\n\n".join(all_content)
