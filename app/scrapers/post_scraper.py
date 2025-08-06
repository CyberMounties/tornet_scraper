# app/scrapers/post_scraper.py
import requests
from bs4 import BeautifulSoup
import json
from requests.exceptions import RequestException
import deepl
from anthropic import Anthropic
import logging


# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def scrape_post_details(
    post_link: str,
    session_cookie: str,
    tor_proxy: str,
    user_agent: str,
    timeout: int = 30
) -> str:
    """
    Scrapes details from a post given its link.
    
    Args:
        post_link (str): URL of the post to scrape
        session_cookie (str): Session cookie for authentication
        tor_proxy (str, optional): Proxy address for Tor routing
        user_agent (str, optional): User agent string for request headers
        timeout (int, optional): Request timeout in seconds (default: 30)
    
    Returns:
        str: JSON string containing title, timestamp, author, and content
    """
    logger.info(f"Starting to scrape post details from {post_link}")
    try:
        # Set up headers and cookies
        headers = {"User-Agent": user_agent}
        cookies = {"session": session_cookie}
        
        # Configure proxies if provided
        proxies = {"http": tor_proxy, "https": tor_proxy} if tor_proxy else None
        
        logger.debug(f"Making request to {post_link} with headers: {headers}, proxies: {proxies}")
        # Make request
        response = requests.get(post_link, headers=headers, cookies=cookies, 
                              proxies=proxies, timeout=timeout)
        response.raise_for_status()
        
        logger.debug("Parsing HTML response with BeautifulSoup")
        # Parse HTML with BeautifulSoup
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Extract details based on provided HTML structure
        title = soup.find('h2', class_='text-light')
        title = title.text.strip() if title else ""
        logger.debug(f"Extracted title: {title}")
        
        card_text = soup.find('p', class_='card-text text-light')
        content = ""
        author = ""
        timestamp = ""
        
        if card_text:
            logger.debug("Extracting content, author, and timestamp")
            # Extract content (text before Posted by)
            content_parts = card_text.get_text(separator="\n").split("Posted by:")
            content = content_parts[0].strip() if content_parts else ""
            
            # Extract author
            author_tag = card_text.find('a', class_='text-light')
            author = author_tag.text.strip() if author_tag else ""
            
            # Extract timestamp
            timestamp_tag = card_text.find('strong', string='Date:')
            if timestamp_tag and timestamp_tag.next_sibling:
                timestamp = timestamp_tag.next_sibling.strip()
        
        # Build result dictionary
        result = {
            "title": title,
            "timestamp": timestamp,
            "author": author,
            "content": content
        }
        
        logger.info(f"Successfully scraped post details: {result}")
        # Return JSON string
        return json.dumps(result, ensure_ascii=False)
    
    except RequestException as e:
        logger.error(f"Request failed: {str(e)}")
        result = {
            "error": f"Request failed: {str(e)}",
            "title": "",
            "timestamp": "",
            "author": "",
            "content": ""
        }
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Scraping failed: {str(e)}")
        result = {
            "error": f"Scraping failed: {str(e)}",
            "title": "",
            "timestamp": "",
            "author": "",
            "content": ""
        }
        return json.dumps(result, ensure_ascii=False)


def translate_string(
    input_string: str,
    auth_key: str,
    target_lang: str = "EN-US"
) -> str:
    """
    Detects the language of an input string and translates it to English if not already in English.
    
    Args:
        input_string (str): The string to analyze and potentially translate
        auth_key (str): DeepL API authentication key
        target_lang (str, optional): Target language for translation (default: EN-US)
    
    Returns:
        str: JSON string containing original and translated text with languages
    """
    logger.info(f"Starting translation for string: {input_string[:50]}...")
    try:
        # Initialize DeepL translator
        logger.debug("Initializing DeepL translator")
        translator = deepl.Translator(auth_key, send_platform_info=False)
        
        # Detect language and translate if necessary
        logger.debug(f"Detecting language and translating to {target_lang}")
        detection = translator.translate_text(
            input_string,
            target_lang=target_lang,
            source_lang=None
        )
        
        source_lang = detection.detected_source_lang
        is_translated = source_lang != "EN"
        translated_text = detection.text if is_translated else None
        
        # Build result dictionary
        result = {
            "original": {
                "text": input_string,
                "language": source_lang,
            },
            "translated": {
                "text": translated_text,
                "language": target_lang if is_translated else None,
                "translated": is_translated
            }
        }
        
        logger.info(f"Translation completed: Source lang={source_lang}, Translated={is_translated}")
        # Return JSON string
        return json.dumps(result, ensure_ascii=False)
    
    except deepl.DeepLException as e:
        logger.error(f"DeepL API error: {str(e)}")
        result = {
            "error": f"DeepL API error: {str(e)}",
            "original": {
                "text": input_string,
                "language": None
            },
            "translated": {
                "text": None,
                "language": None,
                "translated": False
            }
        }
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Unexpected error during translation: {str(e)}")
        result = {
            "error": f"Unexpected error: {str(e)}",
            "original": {
                "text": input_string,
                "language": None
            },
            "translated": {
                "text": None,
                "language": None,
                "translated": False
            }
        }
        return json.dumps(result, ensure_ascii=False)


def iab_classify(
    api_key: str,
    model_name: str,
    prompt: str,
    max_tokens: int = 100,
) -> dict:
    """
    Classify a post using Claude (e.g., Sonnet) to determine if it discusses selling initial access,
    unrelated items, or warnings/complaints.

    Args:
        api_key (str): Anthropic API key.
        model_name (str): Claude model name (e.g., 'claude-3-5-sonnet-20241022').
        prompt (str): Prompt with post text to classify.
        max_tokens (int, optional): Max output tokens. Defaults to 100.

    Returns:
        dict: JSON with classification, scores, and error (if any).
    """
    logger.info(f"Starting classification for prompt: {prompt[:50]}...")
    client = Anthropic(api_key=api_key)

    try:
        logger.debug(f"Sending classification request to Claude model: {model_name}")
        message = client.messages.create(
            model=model_name,
            max_tokens=max_tokens,
            temperature=0.1,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        content = message.content[0].text
        # Extract JSON between ```json and ```
        start = content.index("```json\n") + 7
        end = content.index("\n```", start)
        result = json.loads(content[start:end])
        logger.info(f"Classification completed: {result}")
        return json.dumps(result)
    except Exception as e:
        logger.error(f"Classification failed: {str(e)}")
        return {"error": f"Failed to classify post: {str(e)}", "classification": None, "scores": None}


if __name__ == "__main__":
    prompt = """
Does this post discuss selling initial access to a company (e.g., RDP, VPN, admin access), selling unrelated items (e.g., accounts, tools), or warnings/complaints? Classify it as:
- Positive Posts: direct sale of unauthorized access to a company, this usually include the target's name.
- Neutral Posts: general offers for tools, exploits or malware without naming a specific target.
- Negative Posts: off-topic or unrelated services such as hosting, spam tools or generic VPS sales.

The content must be specifically about selling access to a company or business whose name is mentioned in the post. 

Return **only** a JSON object with:
- `classification`: "Positive", "Neutral", or "Negative".
- `scores`: Probabilities for `positive`, `neutral`, `negative` (summing to 1).

Wrap the JSON in ```json
{
  ...
}
``` to ensure proper formatting. Do not include any reasoning or extra text.

Post:
```markdown
Selling access to Horizon Logistics\nRevenue: $1.2B\nAccess: RDP with DA\nPrice: 0.8 BTC\nDM for details
``` 
"""
    API_KEY = "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" 
    MODEL_NAME = "claude-3-7-sonnet-20250219"
    result = iab_classify(
        api_key=API_KEY,
        model_name=MODEL_NAME,
        prompt=prompt,
        max_tokens=100
    )
    print(result)

