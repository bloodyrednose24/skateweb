import atexit
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote_plus, urlparse

from bs4 import BeautifulSoup
from curl_cffi import requests as curl_requests
from flask import Flask, jsonify, request, render_template

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

app = Flask(__name__)
executor = ThreadPoolExecutor(max_workers=8)

MAX_SCRAPE_PAGES = 20
_selenium_lock = threading.RLock()
_driver = None

def _chrome_binary():
    """Find Chrome binary path across Windows, macOS, and Linux."""
    path = os.environ.get("CHROME_BINARY", "").strip()
    if path and os.path.isfile(path):
        return path
    
    # Try common paths by OS
    candidates = []
    if os.name == "nt":  # Windows
        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]
    elif os.name == "posix":
        if os.uname().sysname == "Darwin":  # macOS
            candidates = [r"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
        else:  # Linux
            candidates = ["/usr/bin/google-chrome", "/usr/bin/chromium"]
    
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return None


def get_driver():
    global _driver
    with _selenium_lock:
        if _driver is None:
            options = Options()
            options.add_argument("--headless=new")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option("useAutomationExtension", False)
            options.add_argument(
                "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            binary = _chrome_binary()
            if binary:
                options.binary_location = binary
            _driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
            _driver.execute_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            print("Chrome driver started")
        return _driver


def close_driver():
    global _driver
    with _selenium_lock:
        if _driver:
            try:
                _driver.quit()
            except Exception:
                pass
            _driver = None

atexit.register(close_driver)

SHOP_CONFIGS = {
    "boards-lv": {
        "name": "boards.lv",
        "base_url": "https://boards.lv",
        "fetch": "selenium",
        "urls": {
            "prebuilts": "https://boards.lv/lv/produkti/skate/skeitbords/skeitbordi",
            "decks":     "https://boards.lv/lv/produkti/skate/skeitbords/klaji",
            "trucks":    "https://boards.lv/lv/produkti/skate/skeitbords/treki",
            "wheels":    "https://boards.lv/lv/produkti/skate/skeitbords/ritenisi",
            "bearings":  "https://boards.lv/lv/produkti/skate/skeitbords/gultni",
            "griptape":  "https://boards.lv/en/products/skate/skateboard/griptape",
            "screws":    "https://boards.lv/lv/produkti/skate/skeitbords/skruves",
        },
        "selectors": {
            "product":  ".product-wrapper.position-relative.h-100.productBox",
            "name":     ".product-name a, p.product-name",
            "price":    ".product-price",
            "discount": ".discount",
            "link":     "a[href]",
            "size":     ".size-guide-wrap label",
        },
        "pagination": lambda url, page: f"{url}/page-{page}",
    },
    "skatedeluxe": {
        "name": "skatedeluxe.com",
        "base_url": "https://www.skatedeluxe.com",
        "fetch": "curl",
        "urls": {
            "prebuilts": "https://www.skatedeluxe.com/en/c/skateboards/skateboard-completes",
            "decks":     "https://www.skatedeluxe.com/en/c/skateboards/skateboard-decks",
            "trucks":    "https://www.skatedeluxe.com/en/c/skateboards/skateboard-trucks",
            "wheels":    "https://www.skatedeluxe.com/en/c/skateboards/skateboard-wheels",
            "bearings":  "https://www.skatedeluxe.com/en/c/skateboards/skateboard-bearings",
            "griptape":  "https://www.skatedeluxe.com/en/c/skateboards/skateboard-griptape",
            "screws":    "https://www.skatedeluxe.com/en/c/skateboards/skateboard-hardware",
        },
        "selectors": {
            "product":  ".listing-product",
            "name":     ".listing-product-name",
            "price":    ".listing-product-price-regular",
            "discount": ".listing-product-price-new",
            "link":     "a[href]",
            "size":     None,  # Size is extracted from product name for skatedeluxe
            "rating":   ".listing-product-rating",
        },
        "pagination": lambda url, page: f"{url}?page={page}",
    },
    "tactics": {
        "name": "tactics.com",
        "base_url": "https://www.tactics.com",
        "fetch": "curl",
        "urls": {
            "prebuilts": "https://www.tactics.com/skateboards",
            "decks":     "https://www.tactics.com/skateboard-decks",
            "trucks":    "https://www.tactics.com/skateboard-trucks",
            "wheels":    "https://www.tactics.com/skateboard-wheels",
            "bearings":  "https://www.tactics.com/skateboard-bearings",
            "griptape":  "https://www.tactics.com/skateboard-grip-tape",
            "screws":    "https://www.tactics.com/skateboard-hardware",
        },
        "selectors": {
            "product":  ".browse-grid-item",
            "name":     "[data-qa='product-name'], h2, a",
            "price":    ".browse-grid-item-price",
            "discount": ".sale-price",
            "link":     "a[href]",
            "size":     None,  # Size extracted from product name
            "rating":   ".product-rating",
        },
        "pagination": lambda url, page: f"{url}?page={page}",
    },
}

def fetch_with_curl(url):
    try:
        response = curl_requests.get(url, impersonate="chrome120", timeout=15)
        return response.text
    except Exception as e:
        print(f"Curl fetch error: {e}")
        return None

def extract_size(text):
    if not text:
        return None
    match = re.search(r'\b(7\.\d+|8\.\d+|9\.\d+)\b', text)
    if match:
        return float(match.group(1))
    return None

def parse_products(soup, sel, config, filter_size, budget):
    products = soup.select(sel["product"])
    results = []
    seen_links = set()

    for product in products:
        price_el    = product.select_one(sel["price"])
        discount_el = product.select_one(sel["discount"]) if sel.get("discount") else None
        link_el     = product.select_one(sel["link"])
        name_el     = product.select_one(sel["name"])

        display_price = discount_el.text.strip() if discount_el else (price_el.text.strip() if price_el else None)
        if not display_price:
            continue

        price_value = None
        raw = re.sub(r'[^0-9.,]', '', display_price).replace(',', '.')
        try:
            price_value = float(raw)
            if price_value > 10000:
                price_value = price_value / 100
        except (ValueError, TypeError):
            price_value = None

        href = link_el.get("href", "") if link_el else ""
        full_link = href if href.startswith("http") else config["base_url"] + href

        if full_link in seen_links:
            continue
        seen_links.add(full_link)

        display_name = name_el.text.strip() if name_el else "Unknown Product"
        on_sale = discount_el is not None

        # Identify product brand from name (first token as heuristic)
        brand = None
        if display_name:
            brand_guess = display_name.split()[0].strip().replace("\"", "").replace("'", "")
            brand = brand_guess

        # Extract size - prefer dedicated selector, fall back to product name
        size = None
        if sel.get("size"):
            size_el = product.select_one(sel["size"])
            size = extract_size(size_el.text if size_el else "")
        # If no size found, try extracting from product name
        if size is None:
            size = extract_size(display_name)

        if filter_size:
            if size is None or size < filter_size["min"] or size > filter_size["max"]:
                continue

        if budget:
            raw = re.sub(r'[^0-9.,]', '', display_price).replace(',', '.')
            try:
                numeric = float(raw)
                if numeric > 10000:
                    numeric = numeric / 100
                if numeric > budget:
                    continue
            except (ValueError, TypeError):
                pass

        img_el = product.select_one("img")
        image_url = ""
        if img_el:
            data_sources = img_el.get("data-sources", "")
            if data_sources:
                image_url = data_sources.split(",")[0]
            else:
                image_url = img_el.get("src") or img_el.get("data-src") or img_el.get("data-lazy-src") or ""
            if image_url and not image_url.startswith("http"):
                image_url = config["base_url"] + image_url

        page_rating = None
        rating_sel = sel.get("rating")
        if rating_sel:
            rating_el = product.select_one(rating_sel)
            if rating_el:
                stars = rating_el.select("svg")
                if stars:
                    page_rating = min(5.0, float(len(stars)))

        results.append({
            "name":         display_name,
            "brand":        brand,
            "price":        display_price,
            "price_value":  price_value,
            "link":         full_link,
            "on_sale":      on_sale,
            "size":         size,
            "shop":         config["name"],
            "image":        image_url,
            "page_rating":  page_rating,
            "company_rating": None,
        })

    return results


def _product_score(item):
    score = 0
    if item.get("on_sale"):
        score += 1000
    rating = item.get("page_rating")
    if isinstance(rating, (int, float)):
        score += rating * 100
    return score


def _order_products(products):
    by_shop = {}
    for item in products:
        by_shop.setdefault(item.get("shop", ""), []).append(item)

    for shop_items in by_shop.values():
        shop_items.sort(
            key=lambda p: (
                -_product_score(p),
                p.get("price_value") if p.get("price_value") is not None else float("inf"),
            )
        )

    ordered = []
    for shop in sorted(by_shop.keys()):
        shop_items = by_shop[shop]
        if shop_items:
            ordered.append(shop_items[0])

    remaining = []
    for shop_items in by_shop.values():
        remaining.extend(shop_items[1:])

    remaining.sort(
        key=lambda p: (
            -_product_score(p),
            p.get("price_value") if p.get("price_value") is not None else float("inf"),
        )
    )
    ordered.extend(remaining)
    return ordered


def scrape_shop_curl(shop_key, category_key, filter_size=None, budget=None):
    config = SHOP_CONFIGS.get(shop_key)
    if not config:
        return []

    base_url = config["urls"].get(category_key)
    if not base_url:
        return []

    sel = config["selectors"]
    all_results = []
    seen_links = set()
    page = 1

    while page <= MAX_SCRAPE_PAGES:
        url = config["pagination"](base_url, page)
        print(f"Fetching page {page}: {url}")

        html = fetch_with_curl(url)
        if not html:
            print(f"Failed to fetch page {page}, stopping")
            break

        soup = BeautifulSoup(html, "html.parser")
        products = soup.select(sel["product"])

        if not products:
            print(f"No products on page {page}, stopping")
            break

        page_results = parse_products(soup, sel, config, filter_size, budget)

        new_count = 0
        for p in page_results:
            if p["link"] not in seen_links:
                seen_links.add(p["link"])
                all_results.append(p)
                new_count += 1

        print(f"Page {page}: {new_count} new products, total so far: {len(all_results)}")

        if new_count == 0:
            print(f"No new products on page {page}, stopping")
            break

        page += 1

    return _order_products(all_results)

def scrape_shop_selenium(shop_key, category_key, filter_size=None, budget=None):
    config = SHOP_CONFIGS.get(shop_key)
    if not config:
        return []

    base_url = config["urls"].get(category_key)
    if not base_url:
        return []

    sel = config["selectors"]
    all_results = []
    seen_links = set()
    page = 1

    with _selenium_lock:
        driver = get_driver()
        while page <= MAX_SCRAPE_PAGES:
            url = config["pagination"](base_url, page)
            print(f"Fetching page {page}: {url}")

            driver.get("about:blank")
            time.sleep(0.3)
            driver.get(url)

            try:
                WebDriverWait(driver, 20).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, sel["product"]))
                )
            except Exception:
                print(f"Timeout on page {page}, stopping")
                break

            time.sleep(2)
            driver.execute_script("window.scrollTo(0, 1000);")
            time.sleep(1)

            elements = driver.find_elements(By.CSS_SELECTOR, sel["product"])
            print(f"Found {len(elements)} elements on page {page}")

            if not elements:
                print(f"No products on page {page}, stopping")
                break

            new_count = 0
            for element in elements:
                try:
                    link_el = element.find_elements(By.CSS_SELECTOR, sel["link"])
                    href = link_el[0].get_attribute("href") if link_el else ""
                    full_link = href if href and href.startswith("http") else config["base_url"] + (href or "")

                    if full_link in seen_links:
                        continue
                    seen_links.add(full_link)

                    name_el = element.find_elements(By.CSS_SELECTOR, sel["name"])
                    display_name = name_el[0].text.strip() if name_el else "Unknown Product"

                    price_el = element.find_elements(By.CSS_SELECTOR, sel["price"])
                    discount_sel = sel.get("discount")
                    discount_el = element.find_elements(By.CSS_SELECTOR, discount_sel) if discount_sel else []

                    on_sale = len(discount_el) > 0
                    display_price = discount_el[0].text.strip() if on_sale else (price_el[0].text.strip() if price_el else None)

                    if not display_price:
                        continue

                    size_sel = sel.get("size")
                    size_el = element.find_elements(By.CSS_SELECTOR, size_sel) if size_sel else []
                    size = extract_size(size_el[0].text.strip() if size_el else "")

                    if filter_size:
                        if size is None or size < filter_size["min"] or size > filter_size["max"]:
                            continue

                    price_value = None
                    if display_price:
                        raw = re.sub(r'[^0-9.,]', '', display_price).replace(',', '.')
                        try:
                            price_value = float(raw)
                            if price_value > 10000:
                                price_value = price_value / 100
                        except (ValueError, TypeError):
                            price_value = None

                    if budget and price_value is not None:
                        if price_value > budget:
                            continue

                    img_els = element.find_elements(By.CSS_SELECTOR, "img")
                    image_url = ""
                    if img_els:
                        # Try multiple image sources for better coverage
                        data_sources = img_els[0].get_attribute("data-sources") or ""
                        if data_sources:
                            image_url = data_sources.split(",")[0]
                        else:
                            image_url = (
                                img_els[0].get_attribute("src") or
                                img_els[0].get_attribute("data-src") or
                                img_els[0].get_attribute("data-lazy-src") or ""
                            )
                        if image_url and not image_url.startswith("http"):
                            image_url = config["base_url"] + image_url

                    # Extract page rating if available (consistent with curl version)
                    page_rating = None
                    rating_sel = sel.get("rating")
                    if rating_sel:
                        try:
                            rating_els = element.find_elements(By.CSS_SELECTOR, rating_sel)
                            if rating_els:
                                stars = rating_els[0].find_elements(By.CSS_SELECTOR, "svg")
                                if stars:
                                    page_rating = min(5.0, float(len(stars)))
                        except Exception:
                            pass

                    all_results.append({
                        "name":        display_name,
                        "price":       display_price,
                        "price_value": price_value,
                        "link":        full_link,
                        "on_sale":     on_sale,
                        "size":        size,
                        "shop":        config["name"],
                        "image":       image_url,
                        "page_rating": page_rating,
                    })
                    new_count += 1

                except Exception as e:
                    print(f"Error parsing element: {e}")
                    continue

            print(f"Page {page}: {new_count} new products, total so far: {len(all_results)}")

            if new_count == 0:
                print(f"No new products on page {page}, stopping")
                break

            page += 1

    return _order_products(all_results)


def scrape_shop(shop_key, category_key, filter_size=None, budget=None):
    config = SHOP_CONFIGS.get(shop_key)
    if not config:
        return []
    if config.get("fetch") == "selenium":
        return scrape_shop_selenium(shop_key, category_key, filter_size, budget)
    else:
        return scrape_shop_curl(shop_key, category_key, filter_size, budget)

@app.route("/")
def index():
    return render_template("index.html")

VALID_CATEGORIES = frozenset(
    {"prebuilts", "decks", "trucks", "wheels", "bearings", "griptape", "screws"}
)


def _is_safe_http_url(url: str) -> bool:
    try:
        p = urlparse(url)
        return p.scheme in ("http", "https") and bool(p.netloc)
    except Exception:
        return False


@app.route("/api/scrape", methods=["POST"])
def scrape():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Expected JSON body"}), 400

    shops = data.get("shops", [])
    category = data.get("category")
    filter_size = data.get("filter_size")
    budget = data.get("budget")

    # DEBUG: Log to file
    with open("debug.log", "a") as f:
        f.write(f"Request: category={category}, shops={shops}\n")
        f.write(f"SHOP_CONFIGS keys: {list(SHOP_CONFIGS.keys())}\n")

    if not category or category not in VALID_CATEGORIES:
        return jsonify({"error": "Invalid or missing category"}), 400
    if not isinstance(shops, list) or not shops:
        return jsonify({"error": "Select at least one shop"}), 400
    if not all(isinstance(s, str) and s in SHOP_CONFIGS for s in shops):
        with open("debug.log", "a") as f:
            f.write(f"Validation failed for shops: {shops}\n")
            for s in shops:
                f.write(f"  '{s}': is_string={isinstance(s, str)}, in_config={s in SHOP_CONFIGS}\n")
        return jsonify({"error": "Invalid shop selection"}), 400

    print(f"\n=== Scrape: shops={shops} category={category} ===")

    curl_shops     = [s for s in shops if SHOP_CONFIGS.get(s, {}).get("fetch") == "curl"]
    selenium_shops = [s for s in shops if SHOP_CONFIGS.get(s, {}).get("fetch") == "selenium"]

    all_results = []

    curl_futures = {
        shop: executor.submit(scrape_shop, shop, category, filter_size, budget)
        for shop in curl_shops
    }
    for shop, future in curl_futures.items():
        try:
            all_results.extend(future.result(timeout=120))
        except Exception as e:
            print(f"Error for {shop}: {e}")

    for shop in selenium_shops:
        try:
            all_results.extend(scrape_shop(shop, category, filter_size, budget))
        except Exception as e:
            print(f"Error for {shop}: {e}")

    all_results = _order_products(all_results)
    return jsonify(all_results)

@app.route("/api/rating")
def rating():
    name        = request.args.get("name", "")
    page_rating = request.args.get("page_rating")

    if page_rating:
        try:
            return jsonify({"rating": float(page_rating)})
        except (TypeError, ValueError):
            pass

    if not name:
        return jsonify({"rating": None})

    q = quote_plus(name[:200])
    ratings = []
    sites = [
        {
            "url":      f"https://www.tactics.com/search?q={q}",
            "selector": "[itemprop='ratingValue'], .rating, .product-rating"
        },
    ]

    # If company is provided, check Google reviews snippet fallback
    company = request.args.get("company", "").strip()
    if company:
        company_q = quote_plus(f"{company} skate brand review")
        sites.insert(0, {
            "url": f"https://www.google.com/search?q={company_q}",
            "selector": "div[role='heading'], span, .A503be"
        })

    for site in sites:
        try:
            html = fetch_with_curl(site["url"])
            if not html:
                continue
            soup = BeautifulSoup(html, "html.parser")
            el = soup.select_one(site["selector"])
            if not el:
                continue

            text = el.get_text(" ", strip=True) if el else ""
            text = text or el.get("content", "")

            # search for first rating pattern x.y / 5 or x.y out of 5
            match = re.search(r"([0-5](?:\.[0-9])?)\s*/\s*5", text)
            if not match:
                match = re.search(r"([0-5](?:\.[0-9])?)\s+(?:out of|out-of)\s+5", text, flags=re.IGNORECASE)
            if not match:
                match = re.search(r"\b([0-5](?:\.[0-9])?)\b", text)

            if match:
                val = float(match.group(1))
                if 0 < val <= 5:
                    ratings.append(val)
        except (ValueError, TypeError, AttributeError):
            pass

    rating_val = round(sum(ratings) / len(ratings), 1) if ratings else None
    return jsonify({"rating": rating_val})

@app.route("/api/debug")
def debug():
    url = request.args.get("url")
    if not url:
        return jsonify({"error": "url parameter required"}), 400
    selector = request.args.get(
        "selector",
        ".product-wrapper.position-relative.h-100.productBox",
    )
    method = request.args.get("method", "selenium")

    if not _is_safe_http_url(url):
        return jsonify({"error": "url must be http(s) with a host"}), 400

    if method == "selenium":
        with _selenium_lock:
            driver = get_driver()
            driver.get("about:blank")
            time.sleep(0.3)
            driver.get(url)
            try:
                WebDriverWait(driver, 20).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                )
            except Exception:
                pass
            time.sleep(3)
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            soup = BeautifulSoup(driver.page_source, "html.parser")
            bs_count = len(soup.select(selector))
            all_classes = set()
            for tag in soup.find_all(True):
                for c in tag.get("class", []):
                    if any(x in c.lower() for x in ["product", "item", "card", "listing", "browse"]):
                        all_classes.add(c)
            return jsonify({
                "selenium_count":      len(elements),
                "beautifulsoup_count": bs_count,
                "product_classes":     sorted(all_classes),
                "first_element_html":  elements[0].get_attribute("outerHTML")[:1000] if elements else None,
            })
    else:
        html = fetch_with_curl(url)
        if not html:
            return jsonify({"error": "Failed to fetch"})
        soup = BeautifulSoup(html, "html.parser")
        products = soup.select(selector)
        all_classes = set()
        for tag in soup.find_all(True):
            for c in tag.get("class", []):
                if any(x in c.lower() for x in ["product", "item", "card", "listing", "browse"]):
                    all_classes.add(c)
        return jsonify({
            "products_found":  len(products),
            "product_classes": sorted(all_classes),
            "first_product":   products[0].prettify()[:1000] if products else None,
        })


if __name__ == "__main__":
    _debug = os.environ.get("FLASK_DEBUG", "").strip().lower() in ("1", "true", "yes")
    app.run(debug=_debug, use_reloader=_debug)
