import requests
from bs4 import BeautifulSoup
from typing import List, Dict
import config
import urllib3

# Disable SSL warnings for self-signed certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class WebsiteScraper:
    def __init__(self):
        self.base_url = config.SCHOOL_WEBSITE
        self.cache = {}

    def scrape_page(self, url: str) -> str:
        """Scrape a single page and return its text content."""
        if url in self.cache:
            return self.cache[url]

        try:
            response = requests.get(url, timeout=10, verify=False)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')

            for tag in soup(["script", "style", "nav", "footer"]):
                tag.decompose()

            text = soup.get_text()
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            text = ' '.join(chunk for chunk in chunks if chunk)

            self.cache[url] = text
            return text

        except Exception as e:
            return f"Error scraping {url}: {str(e)}"

    def get_school_info(self, pages_to_scrape: List[str] = None) -> str:
        """
        Get school information by scraping specified pages.

        Args:
            pages_to_scrape: List of page paths or full URLs to scrape

        Returns:
            str: Combined text content from all pages
        """
        if pages_to_scrape is None:
            # Default to homepage only until key URLs are configured
            pages_to_scrape = ['/']

        all_content = []

        for page in pages_to_scrape:
            # Support both full URLs and relative paths
            if page.startswith('http'):
                url = page
            else:
                url = self.base_url.rstrip('/') + '/' + page.lstrip('/')

            content = self.scrape_page(url)
            all_content.append(f"=== {url} ===\n{content}\n")

        return "\n\n".join(all_content)


# Singleton instance
scraper = WebsiteScraper()
