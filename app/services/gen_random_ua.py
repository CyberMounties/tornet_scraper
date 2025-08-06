import random


def gen_desktop_ua():
    os_options = [
        ("Windows NT", ["10.0", "11.0"]),
        ("Macintosh; Intel Mac OS X", ["15_5", "14_6", "13_6"]),
        ("X11; Linux", ["x86_64", "i686"]),
        ("X11; Ubuntu; Linux", ["x86_64", "i686"])
    ]
    
    browser = "Firefox"
    versions = ["140.0", "141.0", "142.0", "143.0"]
    
    os_type, os_versions = random.choice(os_options)
    os_version = random.choice(os_versions)
    
    if os_type == "Windows NT":
        os_string = f"{os_type} {os_version}; Win64; x64"
    elif os_type == "Macintosh; Intel Mac OS X":
        os_string = f"{os_type} {os_version.replace('_', '.')}"
    else:
        os_string = f"{os_type} {os_version}"
    
    # Construct user agent
    firefox_version = random.choice(versions)
    user_agent = f"Mozilla/5.0 ({os_string}; rv:{firefox_version}) Gecko/20100101 {browser}/{firefox_version}"
    return user_agent


if __name__ == "__main__":
    for _ in range(5):
        print(gen_desktop_ua())

