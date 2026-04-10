import requests
import urllib3
from typing import List
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
    def __init__(self):
        self.base_url = config.SCHOOL_WEBSITE
        self.cache = {}

    def scrape_page(self, url: str) -> str:
        if url in self.cache:
            return self.cache[url]
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
            self.cache[url] = text
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
            all_content.append(f"=== {url} ===\n{content}\n")
        return "\n\n".join(all_content)


scraper = WebsiteScraper()
