# app/scrapers/profile_scraper.py
import logging
import requests
from bs4 import BeautifulSoup
import json


# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def scrape_profile(url, session_cookie, user_agent, tor_proxy, scrape_option="everything"):
    """
    Scrape profile details, posts, and posts where the user has commented, returning raw URIs.

    Args:
        url (str): The URL of the profile page to scrape.
        session_cookie (str): Session cookie for authentication.
        user_agent (str): User-Agent string for the HTTP request.
        tor_proxy (str): Tor proxy address (e.g., 'socks5h://127.0.0.1:9050').
        scrape_option (str): What to scrape: 'comments' (only comments), 'posts' (only posts),
                            or 'everything' (both, default).

    Returns:
        dict: JSON-serializable dictionary containing profile details, posts, comments, and counts.
              Returns an error dictionary if scraping fails.
    """
    valid_options = ["comments", "posts", "everything"]
    if scrape_option not in valid_options:
        logger.error(f"Invalid scrape_option: {scrape_option}. Must be one of {valid_options}")
        return {'error': f"Invalid scrape_option: {scrape_option}. Must be one of {valid_options}"}

    headers = {'User-Agent': user_agent}
    cookies = {'session': session_cookie}
    proxies = {'http': tor_proxy, 'https': tor_proxy}
    
    try:
        response = requests.get(url, headers=headers, cookies=cookies, proxies=proxies, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        result = {
            'profile': {},
            'posts': [],
            'comments': [],
            'post_count': 0,
            'comment_count': 0
        }
        
        profile_card = soup.select_one('.card.bg-dark.border-secondary.mb-4 .card-body')
        if profile_card:
            username = profile_card.select_one('h5.text-light.mb-0').text.strip() if profile_card.select_one('h5.text-light.mb-0') else 'N/A'
            total_posts = profile_card.select_one('p.text-light.mb-0').text.replace('Total Posts:', '').strip() if profile_card.select_one('p.text-light.mb-0') else '0'
            avatar_url = profile_card.select_one('img.rounded-circle')['src'] if profile_card.select_one('img.rounded-circle') else 'N/A'
            result['profile'] = {
                'username': username,
                'total_posts': total_posts,
                'avatar_url': avatar_url
            }
        
        if scrape_option in ["posts", "everything"]:
            posts_table = soup.select_one('.card.bg-dark.border-secondary.mb-4 table.table-dark.table-hover')
            if posts_table:
                post_rows = posts_table.select('tbody tr')
                for row in post_rows:
                    cols = row.select('td')
                    if len(cols) >= 7:
                        post_url = cols[6].select_one('a')['href'] if cols[6].select_one('a') else ''
                        post = {
                            'type': cols[0].text.strip(),
                            'category': cols[1].text.strip(),
                            'title': cols[2].text.strip(),
                            'price': cols[3].text.strip(),
                            'date': cols[4].text.strip(),
                            'comments': cols[5].text.strip(),
                            'post_url': post_url
                        }
                        result['posts'].append(post)
                result['post_count'] = len(result['posts'])
            else:
                logger.warning("Posts table not found")
        
        if scrape_option in ["comments", "everything"]:
            comments_table = soup.select_one('div.card-header.text-light:-soup-contains("User Comments") + div.card-body table.table-dark.table-hover')
            if comments_table:
                comment_rows = comments_table.select('tbody tr')
                for row in comment_rows:
                    cols = row.select('td')
                    if len(cols) >= 4:
                        post_comment_url = cols[3].select_one('a')['href'] if cols[3].select_one('a') else ''
                        comment = {
                            'post_type': cols[0].text.strip(),
                            'comment': cols[1].text.strip(),
                            'date': cols[2].text.strip(),
                            'post_comment_url': post_comment_url
                        }
                        result['comments'].append(comment)
                    else:
                        logger.warning(f"Comment row has insufficient columns: {len(cols)}")
                result['comment_count'] = len(result['comments'])
            else:
                logger.warning("Comments table not found")
        
        return result
    
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch page: {str(e)}")
        return {'error': f'Failed to fetch page: {str(e)}'}
    except Exception as e:
        logger.error(f"Error parsing page: {str(e)}")
        return {'error': f'Error parsing page: {str(e)}'}


# Example usage
if __name__ == '__main__':
    profile_url = 'http://z3zpjsqox4dzxkrk7o34e43cpnc5yrdkywumspqt2d5h3eibllcmswad.onion/profile/HackSavvy'
    session_cookie = '.eJwlzsENwzA'
    user_agent = 'Mozilla/5.0 (Windows NT 11.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0'
    tor_proxy = 'socks5h://127.0.0.1:49075'
    
    scraped_data = scrape_profile(profile_url, session_cookie, user_agent, tor_proxy, scrape_option="everything")

    print(json.dumps(scraped_data, indent=2))
