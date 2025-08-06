# app/services/tornet_forum_login.py
import requests
from bs4 import BeautifulSoup
import base64
from PIL import Image
import time
import openai
import logging
import re
from typing import Optional
import os

try:
    from app.services.gen_random_ua import gen_desktop_ua
except:
    from gen_random_ua import gen_desktop_ua


# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def image_to_base64(image_path: str) -> Optional[str]:
    """Convert image to base64 string."""
    try:
        with open(image_path, "rb") as image_file:
            base64_string = base64.b64encode(image_file.read()).decode('utf-8')
            logger.info(f"Converted image {image_path} to base64 (length: {len(base64_string)} characters)")
            return base64_string
    except Exception as e:
        logger.error(f"Error converting image {image_path} to base64: {e}")
        return None


def resize_image(image_path: str, output_path: str, size: tuple = (354, 112)) -> bool:
    """Resize image to specified dimensions."""
    try:
        with Image.open(image_path) as img:
            original_size = img.size
            img = img.resize(size, Image.LANCZOS)
            img.save(output_path, "PNG")
            logger.info(f"Resized image {image_path} from {original_size} to {size}, saved to {output_path}")
            return True
    except Exception as e:
        logger.error(f"Error resizing image {image_path}: {e}")
        return False


def clean_captcha_text(captcha_text: str) -> Optional[str]:
    """Extract 6-character CAPTCHA code (uppercase letters and numbers) from text."""
    try:
        # Use regex to find 6-character sequence of uppercase letters and numbers
        match = re.search(r'[A-Z0-9]{6}', captcha_text)
        if match:
            cleaned_text = match.group(0)
            logger.info(f"Cleaned CAPTCHA text from '{captcha_text}' to '{cleaned_text}'")
            return cleaned_text
        else:
            logger.error(f"Could not extract 6-character code from CAPTCHA text: {captcha_text}")
            return None
    except Exception as e:
        logger.error(f"Error cleaning CAPTCHA text: {e}")
        return None


def solve_captcha(image_path: str, api_key: str, model_name: str, max_tokens: int, prompt: str) -> Optional[str]:
    """Solve CAPTCHA using OpenAI API."""
    try:
        # Resize image
        resized_path = "resized_captcha.png"
        if not resize_image(image_path, resized_path):
            logger.error("Failed to resize CAPTCHA image")
            return None

        # Convert to base64
        base64_image = image_to_base64(resized_path)
        if not base64_image:
            logger.error("Failed to convert resized CAPTCHA to base64")
            return None

        # Initialize OpenAI client
        client = openai.OpenAI(api_key=api_key)
        
        logger.info(f"Sending CAPTCHA to OpenAI API (model: {model_name}, max_tokens: {max_tokens})")
        logger.debug(f"Prompt sent to OpenAI: {prompt}")
        logger.debug(f"Base64 image length: {len(base64_image)} characters")

        response = client.chat.completions.create(
            model=model_name,
            max_tokens=max_tokens,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{base64_image}"
                            }
                        },
                        {
                            "type": "text",
                            "text": prompt
                        }
                    ]
                }
            ]
        )
        
        captcha_text = response.choices[0].message.content.strip()
        logger.info(f"OpenAI response - CAPTCHA text: {captcha_text}")
        
        # Clean the CAPTCHA text to extract only the 6-character code
        cleaned_captcha = clean_captcha_text(captcha_text)
        if not cleaned_captcha:
            logger.error("Failed to clean CAPTCHA text")
            return None
        return cleaned_captcha
    except Exception as e:
        logger.error(f"Error solving CAPTCHA: {e}")
        return None


def login_to_tor_website(
    api_key: str,
    max_tokens: int,
    model_name: str,
    login_url: str,
    username: str,
    password: str,
    tor_proxy: str,
    prompt: str,
    timeout: int = 20
) -> Optional[requests.Session]:
    """Attempt to log into Tor website and return session with cookies."""
    session = requests.Session()
    session.proxies = {'http': tor_proxy, 'https': tor_proxy}
    user_agent = gen_desktop_ua()
    session.headers.update({'User-Agent': user_agent})
    logger.info(f"Using User-Agent: {user_agent}")
    
    attempt_count = 0
    max_attempts = 9
    captcha_image_path = "captcha.png"
    
    while True:
        try:
            # Get login page
            logger.info(f"Fetching login page: {login_url}")
            response = session.get(login_url, timeout=timeout)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Find CAPTCHA image
            captcha_img = soup.find('img', alt='CAPTCHA')
            if not captcha_img:
                logger.error("CAPTCHA image not found in login page")
                attempt_count += 1
                if attempt_count >= max_attempts:
                    logger.info("Max attempts reached, waiting 5 minutes...")
                    time.sleep(300)
                    attempt_count = 0
                continue
                
            captcha_url = login_url.rsplit('/', 1)[0] + captcha_img['src']
            logger.info(f"Found CAPTCHA image at: {captcha_url}")
            
            # Download CAPTCHA
            logger.info(f"Downloading CAPTCHA from {captcha_url}")
            captcha_response = session.get(captcha_url, timeout=timeout)
            with open(captcha_image_path, 'wb') as f:
                f.write(captcha_response.content)
            logger.info(f"CAPTCHA saved to {captcha_image_path}")
            
            # Solve CAPTCHA
            logger.info(f"Solving CAPTCHA from {captcha_image_path}")
            captcha_text = solve_captcha(captcha_image_path, api_key, model_name, max_tokens, prompt)
            if not captcha_text:
                logger.error("Failed to solve CAPTCHA")
                attempt_count += 1
                if attempt_count >= max_attempts:
                    logger.info("Max attempts reached, waiting 5 minutes...")
                    time.sleep(300)
                    attempt_count = 0
                continue
            
            # Prepare login data
            login_data = {
                'username': username,
                'password': password,
                'captcha': captcha_text
            }
            logger.info(f"Submitting login data: {login_data}")
            
            # Check for CSRF token or other hidden inputs
            form = soup.find('form', method='POST')
            if form:
                hidden_inputs = form.find_all('input', type='hidden')
                for input_tag in hidden_inputs:
                    name = input_tag.get('name')
                    value = input_tag.get('value')
                    if name and value:
                        login_data[name] = value
                        logger.info(f"Added hidden form field: {name}={value}")
            
            # Submit login using the same session
            response = session.post(login_url, data=login_data, timeout=timeout)
            response_text = response.text.lower()
            logger.info(f"Login response received (status: {response.status_code})")
            logger.debug(f"Response text: {response_text[:200]}...") 
            
            # Check response
            if "invalid username or password" in response_text:
                logger.error("Invalid credentials provided")
                # Clean up temporary files
                for path in [captcha_image_path, "resized_captcha.png"]:
                    if os.path.exists(path):
                        logger.info(f"Cleaning up temporary file: {path}")
                        os.remove(path)
                return None
                
            if "invalid captcha" in response_text:
                logger.warning(f"Invalid CAPTCHA (attempt {attempt_count + 1}/{max_attempts})")
                attempt_count += 1
                if attempt_count >= max_attempts:
                    logger.info("Max attempts reached, waiting 5 minutes...")
                    time.sleep(300)  # 5 minutes
                    attempt_count = 0
                continue
                
            if "profile" in response_text and "logout" in response_text:
                logger.info("Login successful")
                logger.info(f"Cookies received: {session.cookies.get_dict()}")
                # Clean up temporary files
                for path in [captcha_image_path, "resized_captcha.png"]:
                    if os.path.exists(path):
                        logger.info(f"Cleaning up temporary file: {path}")
                        os.remove(path)
                return session
            else:
                logger.error("Unexpected response from server")
                attempt_count += 1
                if attempt_count >= max_attempts:
                    logger.info("Max attempts reached, waiting 5 minutes...")
                    time.sleep(300)
                    attempt_count = 0
                continue
                
        except requests.RequestException as e:
            logger.error(f"Request error: {e}")
            attempt_count += 1
            if attempt_count >= max_attempts:
                logger.info("Max attempts reached, waiting 5 minutes...")
                time.sleep(300)
                attempt_count = 0
            continue
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            attempt_count += 1
            if attempt_count >= max_attempts:
                logger.info("Max attempts reached, waiting 5 minutes...")
                time.sleep(300)
                attempt_count = 0
            continue


if __name__ == "__main__":
    login_params = {
        'api_key': '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',
        'max_tokens': 100,
        'model_name': 'gpt-4.1',
        'login_url': 'http://y5extjdmtegzt6n6qe3titrmgjvff4hiualgzy7n2jrahbmfkggbmqqd.onion/login',
        'username': 'DarkHacker',
        'password': 'pass123',
        'timeout': 30,
        'tor_proxy': 'socks5h://127.0.0.1:49075',
        'prompt': """
            The attached image is 6 characters, it contains letters and numbers. 
            The letters are all uppercase. I want you to analyze the image and 
            extract the characters for me, send the combined characters as answer.
        """
    }
    
    session = login_to_tor_website(**login_params)
    if session:
        logger.info("Login successful, final cookies:", session.cookies.get_dict())
        print("Login successful, cookies:", session.cookies.get_dict())
    else:
        logger.error("Login failed")
        print("Login failed")
