# app/scrapers/marketplace_scraper.py
import json
import requests
from bs4 import BeautifulSoup
import logging


# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def create_pagination_batches(url_template, max_page=10):
    """
    Given a web URL with max pagination number, this function returns batches of 10 pagination ranges. 
    """
    if max_page < 1:
        return json.dumps({})
    all_urls = [url_template.format(page=page) for page in range(max_page, 0, -1)]
    batch_size = 10
    batches = {f"{i//batch_size + 1}": all_urls[i:i + batch_size] for i in range(0, len(all_urls), batch_size)}
    return json.dumps(batches)


def scrape_posts(session, proxy, useragent, pagination_range, timeout=30):
    """
    Given a list of web pages, it scraps all post details from every pagination page.
    """
    posts = {}
    headers = {'User-Agent': useragent}
    proxies = {'http': proxy, 'https': proxy} if proxy else None

    for url in pagination_range:
        logger.info(f"Scraping URL: {url}")
        try:
            response = session.get(url, headers=headers, proxies=proxies, timeout=timeout)
            logger.info(f"Response status code: {response.status_code}")
            response.raise_for_status()

            # Log response size and snippet
            logger.debug(f"Response size: {len(response.text)} bytes")
            logger.debug(f"Response snippet: {response.text[:200]}...")

            soup = BeautifulSoup(response.text, 'html.parser')
            table = soup.select_one('table.table-dark tbody')
            if not table:
                logger.error(f"No table found on {url}")
                continue

            table_rows = table.select('tr')
            logger.info(f"Found {len(table_rows)} table rows on {url}")

            for row in table_rows[:10]:
                try:
                    title = row.select_one('td:nth-child(1)').text.strip()
                    author = row.select_one('td:nth-child(2) a').text.strip()
                    timestamp = row.select_one('td:nth-child(3)').text.strip()
                    link = row.select_one('td:nth-child(5) a')['href']

                    logger.info(f"Extracted post: timestamp={timestamp}, title={title}, author={author}, link={link}")
                    posts[timestamp] = {
                        'title': title,
                        'author': author,
                        'link': link
                    }
                except AttributeError as e:
                    logger.error(f"Error parsing row on {url}: {e}")
                    continue

        except requests.RequestException as e:
            logger.error(f"Error scraping {url}: {e}")
            continue

    logger.info(f"Total posts scraped: {len(posts)}")
    return json.dumps(posts)


if __name__ == "__main__":
    session = requests.Session()
    session.cookies.set('session', '.eJwlzsENwzAIAMBd_O4DbINNlokAg9Jv0ryq7t5KvQnuXfY84zrK9jrveJT9ucpWbA0xIs5aZ8VM5EnhwqNNbblWVlmzMUEH9MkDmwZQTwkFDlqhkgounTm9Q7U0nYQsw6MlmtKYqBgUpAMkuJpnuEMsYxtQfpH7ivO_wfL5AtYwMDs.aH1ifQ.uRrB1FnMt3U_apyiWitI9LDnrGE')

    proxy = "socks5h://127.0.0.1:49075"
    useragent = "Mozilla/5.0 (Windows NT 11.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0"
    pagination_range = [
        "http://y5extjdmtegzt6n6qe3titrmgjvff4hiualgzy7n2jrahbmfkggbmqqd.onion/category/marketplace/Sellers?page=1",
        "http://y5extjdmtegzt6n6qe3titrmgjvff4hiualgzy7n2jrahbmfkggbmqqd.onion/category/marketplace/Sellers?page=2",
        "http://y5extjdmtegzt6n6qe3titrmgjvff4hiualgzy7n2jrahbmfkggbmqqd.onion/category/marketplace/Sellers?page=3"
    ]
    timeout = 30
    result = scrape_posts(session, proxy, useragent, pagination_range, timeout)
    print(result)
