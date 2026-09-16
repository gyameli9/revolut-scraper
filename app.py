import streamlit as st
import re
import pandas as pd
import concurrent.futures
from urllib.parse import urljoin, urlparse, unquote
from duckduckgo_search import DDGS
import io
import time
import gc
import json
import html
import threading
import difflib
import logging

from bs4 import BeautifulSoup

# ==============================================================================
# HTTP & FALLBACK IMPORTS
# ==============================================================================

try:
    from curl_cffi import requests as c_requests
    HAS_CURL_CFFI = True
except ImportError:
    import requests
    c_requests = requests
    HAS_CURL_CFFI = False

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False


# ==============================================================================
# GLOBALE KONFIGURATION
# ==============================================================================

MAX_PAGES_PER_SITE = 8
MAX_SEARCH_CANDIDATES = 6
MAX_VERIFICATION_CANDIDATES = 4

HTTP_TIMEOUT = 10.0
HTTP_RETRY_TIMEOUT = 14.0
PLAYWRIGHT_TIMEOUT = 18000

DDG_LOCK = threading.Lock()


# ==============================================================================
# PORTAL- UND FILTER-DOMAINEN (UM B2B-VERZEICHNISSE ERWEITERT)
# ==============================================================================

PORTAL_DOMAINS = [
    'facebook.com', 'instagram.com', 'linkedin.com', 'xing.com', 'youtube.com',
    'twitter.com', 'pinterest.com', 'booking.com', 'tripadvisor.', 'holidaycheck.',
    'airbnb.', 'expedia.', 'trivago.', '11880.com', 'gelbeseiten.de', 'dasoertliche.de',
    'northdata.de', 'northdata.com', 'trustpilot.com', 'provenexpert.com', 'golocal.de',
    'branchenbuch.', 'cylex.', 'wer-liefert-was.', 'wlw.de', 'wlw.at', 'wlw.ch',
    'yelp.com', 'kununu.com', 'companyhouse.de', 'companyhouse.com', 'creditreform.de',
    'zoominfo.com', 'openpr.de', 'kimeta.de', 'worldtenders.in', 'worldplaces.me',
    'arounddeal.com', 'eximpedia.app', 'logimat-messe.de', 'handelsregister.ai',
    'online-handelsregister.de', 'firmenwissen.de', 'dastelefonbuch.de',
    'enfsolar.com', 'ceginformacio.hu', 'haus-garten-freizeit.de', 'metro.it',
    'tracxn.com', 'deutsche-exportdatenbank.de', 'rocketreach.co', 'bloomberg.com',
    'keytobavaria.com'
]

AGENCY_KEYWORDS = [
    'design', 'webdesign', 'agentur', 'media', 'werbeagentur', 'marketing',
    'hosting', 'wordpress', 'jimdo', 'wix', 'typograf', 'it-service',
    'software', 'dev', 'creator', 'disclaimer', 'webmaster', 'provider', 'pixel'
]

INVALID_EMAIL_PREFIXES = [
    'noreply', 'no-reply', 'donotreply', 'do-not-reply', 'bounce', 'mailer-daemon'
]

PRIORITY_EMAIL_PREFIXES = [
    'info@', 'kontakt@', 'contact@', 'office@', 'service@', 'mail@',
    'post@', 'zentrale@', 'empfang@', 'rezeption@', 'buchhaltung@', 'anfrage@'
]

HONORIFICS = [
    'dr.', 'dr', 'prof.', 'prof', 'dipl.-ing.', 'dipl.-kfm.', 'dipl.-jur.',
    'dipl.-oec.', 'herr', 'frau', 'mr.', 'mrs.', 'ms.'
]

ALLOWED_LOWERCASE_PREFIXES = {
    'von', 'van', 'zu', 'zum', 'zur', 'de', 'del', 'der', 'den', 'la', 'le'
}


# ==============================================================================
# RECHTSFORMEN
# ==============================================================================

COMPANY_LEGAL_TERMS = {
    'gmbh', 'ug', 'ag', 'kg', 'ohg', 'gbr', 'gmbh & co. kg', 'e.k.', 'e.kfr.',
    'e.v.', 'ltd', 'limited', 'holding', 'gesellschaft', 'haftungsbeschränkt',
    'eingetragener kaufmann', 'eingetragene kauffrau', 'genossenschaft', 'verwaltung', 'mbh'
}

LEGAL_TERMS_SORTED = sorted(
    COMPANY_LEGAL_TERMS,
    key=len,
    reverse=True
)


# ==============================================================================
# PERSONEN-FILTER & STOPWORDS
# ==============================================================================

PERSON_STOPWORDS = {
    'hotel', 'gasthof', 'restaurant', 'pension', 'resort', 'ferienwohnung',
    'apartments', 'apartment', 'zimmer', 'gästehaus', 'gastronomie',
    'tourismus', 'tourist', 'service', 'team', 'kontakt', 'willkommen',
    'rezeption', 'buchung', 'reservierung', 'marketing', 'vertrieb',
    'management', 'verwaltung', 'firma', 'unternehmen', 'geschäft',
    'immobilien', 'hausverwaltung', 'hotelbetrieb', 'webdesign', 'agentur',
    'media', 'it', 'software', 'riesige', 'aufenthalte', 'konzipiert',
    'siehe', 'karte', 'unsere', 'unser', 'unseren', 'unseres', 'über',
    'preise', 'cookies', 'datenschutz', 'agb', 'impressum', 'angebot',
    'angebote', 'uns', 'ihr', 'ihre', 'ihren', 'deutschland', 'germany',
    'und', 'der', 'die', 'das', 'den', 'dem', 'des', 'für', 'mit', 'von',
    'aus', 'auf', 'straße', 'strasse', 'haus', 'stadt', 'telefon', 'fax',
    'mail', 'email', 'mo', 'di', 'mi', 'do', 'fr', 'sa', 'so', 'uhr',
    'zeiten', 'öffnungszeiten', 'alle', 'rechte', 'vorbehalten', 'copyright',
    'seite', 'sehr', 'geehrte', 'inhalte', 'haftung', 'links', 'urheberrecht',
    'widerspruch', 'angaben', 'erhältst', 'bekommst', 'zugangsdaten',
    'gebäude', 'einem', 'einer', 'einen', 'eines', 'dass', 'wenn', 'bitte',
    'diese', 'dieser', 'nach', 'oder', 'home', 'startseite', 'index',
    'welcome', 'ansprechpartner', 'ansprechpartnerin', 'inhaber', 'inhaberin',
    'geschäftsführer', 'geschäftsführerin', 'geschäftsführung', 'vertreten',
    'vertretungsberechtigt', 'vorstand', 'prokurist', 'prokuristin',
    'gesellschafter', 'gesellschafterin', 'gründer', 'gründerin', 'founder',
    'owner', 'adresse', 'herzlich', 'kontaktieren', 'jetzt', 'erfahren',
    'mehr', 'leistungen'
}.union(COMPANY_LEGAL_TERMS)

GENERIC_TITLES_STOPWORDS = {
    'home', 'startseite', 'homepage', 'willkommen', 'welcome', 'kontakt',
    'impressum', 'unternehmen', 'firma', 'company', 'about', 'about us',
    'team', 'datenschutz', 'privacy', 'cookie', 'cookies'
}

INVALID_INPUT_PATTERNS = {
    '', '-', 'unknown', 'n/a', 'na', 'none', 'null', 'undefined'
}


# ==============================================================================
# PAGE / ROLE SCORING
# ==============================================================================

PAGE_TYPE_SCORES = {
    "impressum": 80,
    "legal": 75,
    "kontakt": 60,
    "about": 50,
    "team": 40,
    "homepage": 15,
    "datenschutz": 10
}

ROLE_SCORES = {
    "geschäftsführer": 110,
    "geschäftsführerin": 110,
    "geschäftsführung": 105,
    "managing director": 110,
    "inhaber": 100,
    "inhaberin": 100,
    "owner": 100,
    "founder": 95,
    "gründer": 95,
    "gründerin": 95,
    "vorstand": 100,
    "vorständin": 100,
    "vertreten durch": 90,
    "prokurist": 80,
    "prokuristin": 80,
    "gesellschafter": 80,
    "gesellschafterin": 80,
    "ansprechpartner": 70,
    "ansprechpartnerin": 70
}

ROLE_PATTERN_STR = (
    r"\b(?:"
    + "|".join(re.escape(role) for role in ROLE_SCORES.keys())
    + r")\b"
)
ROLE_REGEX = re.compile(ROLE_PATTERN_STR, re.IGNORECASE)


# ==============================================================================
# TEXT & COMPANY NORMALIZATION
# ==============================================================================

def normalize_whitespace(value):
    if value is None:
        return ""
    return re.sub(r'\s+', ' ', str(value)).strip()


def normalize_domain(domain):
    if not domain:
        return ""
    domain = str(domain).lower().strip()
    if '://' in domain:
        domain = urlparse(domain).netloc
    domain = domain.split('/')[0].split(':')[0]
    if domain.startswith('www.'):
        domain = domain[4:]
    return domain


def extract_domain(url):
    try:
        return normalize_domain(urlparse(url).netloc)
    except Exception:
        return ""


def is_portal_domain(url_or_domain):
    value = str(url_or_domain).lower()
    domain = normalize_domain(value)
    for portal in PORTAL_DOMAINS:
        portal_clean = portal.lower().rstrip('.')
        if (domain == portal_clean or domain.endswith('.' + portal_clean) or portal_clean in domain):
            return True
    return False


def normalize_company_string(name):
    if not name:
        return ""
    value = str(name).lower().strip().replace("&", " und ")
    for term in LEGAL_TERMS_SORTED:
        pattern = r'(?<!\w)' + re.escape(term.lower()) + r'(?!\w)'
        value = re.sub(pattern, ' ', value)
    value = (
        value.replace('ä', 'ae')
             .replace('ö', 'oe')
             .replace('ü', 'ue')
             .replace('ß', 'ss')
    )
    value = re.sub(r'[^a-z0-9\s]', ' ', value)
    return re.sub(r'\s+', ' ', value).strip()


def company_tokens(name):
    normalized = normalize_company_string(name)
    if not normalized:
        return set()
    return {token for token in normalized.split() if len(token) >= 2}


def legal_term_score(name):
    if not name:
        return 0
    value = str(name).lower()
    score = 0
    for term in COMPANY_LEGAL_TERMS:
        if re.search(r'(?<!\w)' + re.escape(term.lower()) + r'(?!\w)', value):
            if term in {'gmbh', 'ug', 'ag', 'kg', 'ohg', 'gbr', 'e.k.', 'e.kfr.', 'ltd', 'limited'}:
                score += 8
            else:
                score += 4
    return min(score, 20)


def token_overlap_score(query, target):
    q_tokens = company_tokens(query)
    t_tokens = company_tokens(target)
    if not q_tokens or not t_tokens:
        return 0
    intersection = q_tokens.intersection(t_tokens)
    if not intersection:
        return 0
    query_coverage = len(intersection) / len(q_tokens)
    target_coverage = len(intersection) / len(t_tokens)
    if query_coverage + target_coverage == 0:
        return 0
    f1 = (2 * query_coverage * target_coverage) / (query_coverage + target_coverage)
    return int(f1 * 100)


def calculate_match_score(query, target_text):
    if not query or not target_text:
        return 0
    q_clean = normalize_company_string(query)
    t_clean = normalize_company_string(target_text)
    if not q_clean or not t_clean:
        return 0
    if q_clean == t_clean:
        return 100
    fuzzy = difflib.SequenceMatcher(None, q_clean, t_clean).ratio() * 100
    token_score = token_overlap_score(query, target_text)
    combined = (fuzzy * 0.55 + token_score * 0.45)
    legal_bonus = min(legal_term_score(query) + legal_term_score(target_text), 15)
    combined += legal_bonus
    return min(int(combined), 100)


def extract_domain_name(url):
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower().split(':')[0]
        if host.startswith('www.'):
            host = host[4:]
        parts = host.split('.')
        if len(parts) >= 2:
            if len(parts) >= 3 and parts[-2] in {'co', 'com', 'net', 'org', 'gov'}:
                return parts[-3]
            return parts[-2]
        return parts[0] if parts else ""
    except Exception:
        return ""


def is_portal_url(url):
    if not url:
        return True
    url_lower = url.lower()
    hostname = urlparse(url_lower).netloc.lower()
    if hostname.startswith('www.'):
        hostname = hostname[4:]
    for portal in PORTAL_DOMAINS:
        portal_clean = portal.lower().rstrip('.')
        if (hostname == portal_clean or hostname.endswith('.' + portal_clean) or portal_clean in hostname):
            return True
    return False


def normalize_candidate_url(url):
    if not url:
        return ""
    url = html.unescape(str(url)).strip()
    if not url.startswith(('http://', 'https://')):
        return ""
    try:
        parsed = urlparse(url)
        clean = parsed._replace(query="", fragment="").geturl()
        return clean.rstrip('/')
    except Exception:
        return url


# ==============================================================================
# SEARCH RESULT SCORING & CANDIDATE COLLECTION
# ==============================================================================

def score_search_candidate(query, url, title="", snippet=""):
    if not url:
        return {"score": -999, "accepted": False, "reason": "Keine URL"}

    clean_url = normalize_candidate_url(url)

    if not clean_url or is_portal_url(clean_url):
        return {"score": -999, "accepted": False, "reason": "Portal-/Verzeichnis-Domain"}

    domain_name = extract_domain_name(clean_url)
    title = title or ""
    snippet = snippet or ""

    domain_match = calculate_match_score(query, domain_name)
    title_match = calculate_match_score(query, title)
    snippet_match = calculate_match_score(query, snippet)

    score = 0
    score += domain_match * 0.40
    score += title_match * 0.40
    score += snippet_match * 0.20

    if normalize_company_string(query) and normalize_company_string(query) in normalize_company_string(title):
        score += 15

    if query.lower() in snippet.lower():
        score += 10

    score += legal_term_score(title) * 0.5

    path = urlparse(clean_url).path.strip('/').lower()

    if not path:
        score += 15
    elif path in {'de', 'en', 'index.html', 'index.php'}:
        score += 10

    if any(keyword in path for keyword in ['impressum', 'imprint', 'legal', 'kontakt', 'contact']):
        score += 20

    final_score = min(int(score), 100)

    return {
        "score": final_score,
        "accepted": final_score >= 35,
        "confidence": "hoch" if final_score >= 75 else ("mittel" if final_score >= 55 else "niedrig"),
        "url": clean_url,
        "domain_name": domain_name,
        "domain_match": int(domain_match),
        "title_match": int(title_match),
        "snippet_match": int(snippet_match),
        "title": title,
        "snippet": snippet,
        "reason": "Suchresultat bewertet"
    }


def deduplicate_search_candidates(candidates):
    grouped = {}
    for candidate in candidates:
        url = candidate.get("url", "")
        if not url:
            continue
        try:
            domain = urlparse(url).netloc.lower().replace('www.', '')
        except Exception:
            continue
        if not domain:
            continue
        old = grouped.get(domain)
        if old is None or candidate.get("score", -999) > old.get("score", -999):
            grouped[domain] = candidate
    return list(grouped.values())


def get_search_candidates_serper(query, serper_key, debug_log=None):
    candidates = []
    if not serper_key:
        return candidates
    try:
        headers = {'X-API-KEY': serper_key.strip(), 'Content-Type': 'application/json'}
        search_query = query.replace('"', '').strip()
        payload = {'q': f'{search_query} offizielle Website Impressum', 'num': 10}
        response = c_requests.post('https://google.serper.dev/search', headers=headers, json=payload, timeout=8.0)
        if response.status_code == 200:
            data = response.json()
            for position, item in enumerate(data.get("organic", []), start=1):
                link = item.get("link", "")
                title = item.get("title", "")
                snippet = item.get("snippet", "")
                scored = score_search_candidate(query, link, title, snippet)
                if scored.get("accepted"):
                    scored["source"] = "serper"
                    scored["position"] = position
                    candidates.append(scored)
        elif debug_log is not None:
            debug_log["errors"].append(f"Serper HTTP {response.status_code}")
    except Exception as e:
        if debug_log is not None:
            debug_log["errors"].append(f"Serper search error: {str(e)[:150]}")
    return candidates


def get_search_candidates_duckduckgo(query, debug_log=None):
    candidates = []
    try:
        with DDG_LOCK:
            time.sleep(0.8)
            with DDGS() as ddgs:
                search_query = query.replace('"', '').strip()
                results = ddgs.text(f'{search_query} offizielle Website Impressum', max_results=10)
                for position, item in enumerate(results, start=1):
                    link = item.get("href", "")
                    title = item.get("title", "")
                    snippet = item.get("body", "")
                    scored = score_search_candidate(query, link, title, snippet)
                    if scored.get("accepted"):
                        scored["source"] = "duckduckgo"
                        scored["position"] = position
                        candidates.append(scored)
    except Exception as e:
        if debug_log is not None:
            debug_log["errors"].append(f"DDG search error: {str(e)[:150]}")
    return candidates


def collect_search_candidates(query, serper_key="", debug_log=None):
    candidates = []
    queries_to_try = [query]

    umlaut_variant = (
        query.replace('ä', 'ae').replace('ö', 'oe').replace('ü', 'ue')
             .replace('Ä', 'Ae').replace('Ö', 'Oe').replace('Ü', 'Ue')
    )
    if umlaut_variant != query:
        queries_to_try.append(umlaut_variant)

    for q in queries_to_try:
        if serper_key:
            candidates.extend(get_search_candidates_serper(q, serper_key, debug_log))
        if len(candidates) < 3:
            candidates.extend(get_search_candidates_duckduckgo(q, debug_log))
        if candidates:
            break

    candidates = deduplicate_search_candidates(candidates)
    candidates.sort(key=lambda x: x.get("score", -999), reverse=True)
    candidates = candidates[:6]
    if debug_log is not None:
        debug_log["search_candidates"] = candidates
    return candidates


def is_direct_url_input(query):
    if not query:
        return False
    value = query.strip().lower()
    if re.match(r'^https?://', value) or value.startswith('www.'):
        return True
    if '.' in value and ' ' not in value and not is_portal_domain(value):
        return True
    return False


def normalize_input_url(query):
    value = query.strip()
    if not re.match(r'^https?://', value, flags=re.IGNORECASE):
        return 'https://' + value
    return value


def create_direct_candidate(query):
    url = normalize_input_url(query)
    return {
        "url": url,
        "title": "",
        "snippet": "",
        "score": 100,
        "match_score": 100,
        "source": "direct_input"
    }


def resolve_company_to_website(query, serper_key="", debug_log=None):
    if is_direct_url_input(query):
        candidate = create_direct_candidate(query)
        if debug_log is not None:
            debug_log["resolution_mode"] = "direct_input"
            debug_log["search_candidates"] = [candidate]
        return candidate

    candidates = collect_search_candidates(query, serper_key, debug_log)
    if not candidates:
        return None
    candidates = [c for c in candidates if c.get("score", 0) >= 20]
    return candidates[0] if candidates else None


# ==============================================================================
# HTTP FETCHING, RETRIES & PLAYWRIGHT
# ==============================================================================

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive"
}

NO_RETRY_STATUS_CODES = {400, 401, 403, 404, 405, 410, 451}


def create_http_session():
    try:
        if HAS_CURL_CFFI:
            return c_requests.Session()
        return requests.Session()
    except Exception:
        return None


def close_http_session(session):
    if session is None:
        return
    try:
        session.close()
    except Exception:
        pass


def build_request_kwargs(timeout):
    kwargs = {
        "timeout": timeout,
        "headers": DEFAULT_HEADERS,
        "allow_redirects": True
    }
    if HAS_CURL_CFFI:
        kwargs["impersonate"] = "chrome110"
    return kwargs


def classify_http_error(status_code=0, exception=None):
    if status_code:
        if status_code == 403: return "FORBIDDEN"
        if status_code == 404: return "NOT_FOUND"
        if status_code == 429: return "RATE_LIMITED"
        if 400 <= status_code < 500: return "CLIENT_ERROR"
        if 500 <= status_code < 600: return "SERVER_ERROR"
    if exception:
        err = str(exception).lower()
        if "timeout" in err or "timed out" in err: return "TIMEOUT"
        if "ssl" in err or "cert" in err: return "SSL_ERROR"
        if "connection" in err: return "CONNECTION_ERROR"
    return "REQUEST_ERROR"


def detect_spa_html(html_content):
    if not html_content:
        return False
    try:
        sample = html_content[:15000].lower()
        soup = BeautifulSoup(html_content[:30000], "html.parser")
        text_length = len(soup.get_text(" ", strip=True))
        if text_length > 250:
            return False
        spa_markers = ["enable javascript", "enable js", "app-root", "id=\"root\"", "id=\"app\"", "react", "vue", "angular"]
        return text_length < 150 and any(m in sample for m in spa_markers)
    except Exception:
        return False


def safe_playwright_fetch(url, timeout_ms=18000):
    result = {"success": False, "html": "", "final_url": url, "error": None, "status_code": 0}
    if not HAS_PLAYWRIGHT:
        result["error"] = "Playwright nicht installiert"
        return result
    browser = None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
            )
            context = browser.new_context(user_agent=USER_AGENT, ignore_https_errors=True)
            page = context.new_page()
            response = page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            if response:
                result["status_code"] = response.status
            page.wait_for_timeout(1200)
            rendered_html = page.content()
            if rendered_html and len(rendered_html) > 100:
                result["success"] = True
                result["html"] = rendered_html
                result["final_url"] = page.url
            else:
                result["error"] = "Kein HTML von Playwright"
    except Exception as e:
        result["error"] = f"Playwright: {str(e)[:180]}"
    finally:
        if browser:
            try: browser.close()
            except Exception: pass
    return result


def request_html_once(url, session, timeout):
    result = {"success": False, "html": "", "status_code": 0, "final_url": url, "error": None}
    try:
        kwargs = build_request_kwargs(timeout)
        req = session.get if session else (c_requests.get if HAS_CURL_CFFI else requests.get)
        response = req(url, **kwargs)
        result["status_code"] = response.status_code
        result["final_url"] = getattr(response, 'url', url)
        if 200 <= response.status_code < 300:
            result["html"] = response.text or ""
            result["success"] = bool(result["html"].strip())
            return result
        result["error"] = f"HTTP {response.status_code}"
        return result
    except Exception as e:
        result["error"] = str(e)[:250]
        return result


def fetch_html_page(url, session=None, use_playwright=True):
    result = {
        "url": url, "final_url": url, "html": "", "status_code": 0,
        "error": None, "is_spa": False, "attempts": []
    }
    if not url:
        result["error"] = "Leere URL"
        return result

    parsed = urlparse(normalize_input_url(url))
    https_url = parsed._replace(scheme="https").geturl()
    http_url = parsed._replace(scheme="http").geturl()

    own_session = False
    if session is None:
        session = create_http_session()
        own_session = True

    try:
        # HTTPS Try
        current = request_html_once(https_url, session, HTTP_TIMEOUT)
        result["attempts"].append(current)

        if current["success"]:
            result["html"] = current["html"]
            result["status_code"] = current["status_code"]
            result["final_url"] = current["final_url"]
            if detect_spa_html(current["html"]):
                result["is_spa"] = True
            else:
                return result

        # HTTP Fallback
        if not result["html"]:
            current = request_html_once(http_url, session, HTTP_TIMEOUT)
            result["attempts"].append(current)
            if current["success"]:
                result["html"] = current["html"]
                result["status_code"] = current["status_code"]
                result["final_url"] = current["final_url"]
                if not detect_spa_html(current["html"]):
                    return result

        # Playwright Fallback
        if use_playwright and HAS_PLAYWRIGHT and (result["is_spa"] or not result["html"]):
            pw_res = safe_playwright_fetch(https_url)
            if pw_res["success"]:
                result["html"] = pw_res["html"]
                result["final_url"] = pw_res["final_url"]
                result["status_code"] = pw_res["status_code"] or 200
                result["is_spa"] = False
                result["error"] = None
                return result

        result["error"] = current.get("error", "Fetch fehlgeschlagen")
        return result

    finally:
        if own_session:
            close_http_session(session)


# ==============================================================================
# INTERNAL LINK DISCOVERY & CRAWLING
# ==============================================================================

def classify_page_type(url, link_text=""):
    value = f"{url} {link_text}".lower()
    if any(k in value for k in ["impressum", "imprint", "legal-notice"]): return "impressum"
    if any(k in value for k in ["legal", "aviso-legal"]): return "legal"
    if any(k in value for k in ["kontakt", "contact"]): return "kontakt"
    if any(k in value for k in ["ueber-uns", "über-uns", "about", "company"]): return "about"
    if "team" in value or "ansprechpartner" in value: return "team"
    if "datenschutz" in value or "privacy" in value: return "datenschutz"
    return "homepage"


def score_internal_link(href, text, title=""):
    value = f"{href} {text} {title}".lower()
    score = 0
    if any(k in value for k in ["impressum", "imprint", "legal-notice"]): score += 100
    if any(k in value for k in ["kontakt", "contact"]): score += 80
    if any(k in value for k in ["ueber-uns", "über-uns", "about"]): score += 50
    if any(k in value for k in ["team", "ansprechpartner"]): score += 40
    if "datenschutz" in value: score += 10
    return score


def discover_internal_links(html_content, base_url, max_links=8):
    links = []
    if not html_content:
        return links
    try:
        soup = BeautifulSoup(html_content, "html.parser")
        base_domain = normalize_domain(base_url)
        for a_tag in soup.find_all("a", href=True):
            href_raw = a_tag.get("href", "").strip()
            if not href_raw or href_raw.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue
            full_url = urljoin(base_url, href_raw)
            if normalize_domain(full_url) != base_domain:
                continue
            clean_url = normalize_candidate_url(full_url)
            score = score_internal_link(clean_url, a_tag.get_text(" ", strip=True), a_tag.get("title", ""))
            if score > 0:
                links.append({"url": clean_url, "score": score})
        links.sort(key=lambda x: x["score"], reverse=True)
        unique = []
        seen = set()
        for item in links:
            if item["url"] not in seen:
                seen.add(item["url"])
                unique.append(item)
                if len(unique) >= max_links: break
        return unique
    except Exception:
        return []


# ==============================================================================
# EXTRACTION LOGIC (EMAILS, PHONES, COMPANIES, PERSONS)
# ==============================================================================

def decode_cloudflare_email(cf_hex):
    try:
        key = int(cf_hex[:2], 16)
        return "".join([chr(int(cf_hex[i:i+2], 16) ^ key) for i in range(2, len(cf_hex), 2)])
    except Exception: return ""


def extract_email_candidates(html_content, soup, page_url, page_type, site_domain):
    candidates = []
    found_raw = []
    if soup:
        for elem in soup.find_all(attrs={"data-cfemail": True}):
            dec = decode_cloudflare_email(elem['data-cfemail'])
            if dec: found_raw.append((dec, "cfemail"))
        for a in soup.find_all('a', href=True):
            href = a['href'].lower()
            if 'mailto:' in href:
                em = href.split('mailto:')[-1].split('?')[0].strip()
                if em: found_raw.append((em, "mailto"))

    text = html.unescape(html_content or "")
    text = re.sub(r'(?i)\s*[\(\[]\s*at\s*[\)\]]\s*', '@', text)
    text = text.replace('&#64;', '@').replace('&#x40;', '@').replace('%40', '@')
    for m in re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text):
        found_raw.append((m, "regex_body"))

    clean_dom = site_domain.lower().replace('www.', '')

    for email_str, src in found_raw:
        em = email_str.lower().strip().strip('.,:;()')
        if '@' not in em or '.' not in em.split('@')[-1]: continue
        prefix, em_domain = em.split('@', 1)
        if any(em_domain.endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.svg']): continue
        if prefix in INVALID_EMAIL_PREFIXES: continue

        is_exact_domain = (clean_dom and (em_domain == clean_dom or em_domain.endswith('.' + clean_dom)))
        if not is_exact_domain and any(kw in em for kw in AGENCY_KEYWORDS):
            continue

        score = 100 if is_exact_domain else 0
        if any(em.startswith(p) for p in PRIORITY_EMAIL_PREFIXES): score += 30
        if src in ["mailto", "cfemail"]: score += 20
        if page_type in ['impressum', 'legal']: score += 30

        candidates.append({"value": em, "score": score, "source": src, "page": page_type})
    return candidates


def extract_phone_candidates(page_html, soup, page_url, page_type):
    candidates = []
    raw_phones = []
    if soup:
        for a in soup.find_all('a', href=True):
            href = a['href'].lower()
            if 'tel:' in href:
                raw_phones.append((href.split('tel:')[-1].strip(), "tel_tag"))

    text = soup.get_text(" ", strip=True) if soup else page_html
    matches = re.findall(r'(?:Tel(?:efon)?|Fon|Mobil|Mobile|Phone|Call)?\s*[:\.]?\s*(\+?[0-9\s\/\-\(\)]{8,25})', text, re.IGNORECASE)
    for m in matches: raw_phones.append((m, "regex_body"))

    for raw_p, src in raw_phones:
        clean_p = re.sub(r'(\+\d{2,3})\s*\(0\)', r'\1 ', raw_p)
        clean_p = re.sub(r'\(0\)', '', clean_p)

        cleaned = re.sub(r'[^\d+]', '', clean_p)
        if cleaned.startswith('0049'): cleaned = '+49' + cleaned[4:]
        elif cleaned.startswith('0') and not cleaned.startswith('00'): cleaned = '+49' + cleaned[1:]
        elif cleaned.startswith('49') and not cleaned.startswith('+'): cleaned = '+' + cleaned

        if cleaned.count('+') > 1:
            cleaned = '+' + re.sub(r'\+', '', cleaned)

        digits_only = re.sub(r'\D', '', cleaned)
        if not (8 <= len(digits_only) <= 15) or 'fax' in raw_p.lower(): continue

        score = 50 if src == "tel_tag" else 20
        if page_type in ['impressum', 'kontakt']: score += 30
        candidates.append({"value": cleaned, "score": score, "source": src, "page": page_type})
    return candidates


def clean_company_name(name):
    if not name:
        return None
    name = re.sub(r'\s+', ' ', str(name)).strip().strip(' |:-–—,.;')
    if not name or len(name) > 120:
        return None

    if re.search(r'\.(?:de|com|net|org|eu|info|biz|at|ch|co|group|io|app)\b', name, re.IGNORECASE):
        return None
    if name.lower().startswith(('http://', 'https://', 'www.')):
        return None

    if name.lower() in GENERIC_TITLES_STOPWORDS:
        return None
    return name


def extract_company_candidates(soup, page_type):
    candidates = []
    if not soup: return candidates

    for script in soup.find_all('script', attrs={'type': re.compile(r'application/ld\+json', re.IGNORECASE)}):
        try:
            data = json.loads(script.string or script.get_text() or "{}")
            def walk_org(obj):
                if isinstance(obj, dict):
                    t = str(obj.get('@type', '')).lower()
                    if any(k in t for k in ['organization', 'localbusiness', 'corporation']):
                        name = obj.get('legalName') or obj.get('name')
                        if isinstance(name, str) and len(name.strip()) > 2:
                            candidates.append({"value": name.strip(), "score": 120, "source": "jsonld", "page": page_type})
                    for v in obj.values(): walk_org(v)
                elif isinstance(obj, list):
                    for i in obj: walk_org(i)
            walk_org(data)
        except Exception: pass

    og_site = soup.find('meta', property='og:site_name')
    if og_site and og_site.get('content'):
        candidates.append({"value": og_site['content'].strip(), "score": 100, "source": "og:site_name", "page": page_type})

    title = soup.find('title')
    if title:
        t_text = re.sub(r'\s+', ' ', title.get_text(' ', strip=True)).strip()
        parts = re.split(r'\s*[|:–—]\s*', t_text)
        for p in parts[:2]:
            p_clean = p.strip()
            if 3 <= len(p_clean) <= 80:
                candidates.append({"value": p_clean, "score": 60, "source": "title_tag", "page": page_type})
    return candidates


def strip_honorifics(name_str):
    if not name_str: return ""
    cleaned = re.sub(r'^(?:(?:dr|prof)\.?\s+)+', '', str(name_str), flags=re.IGNORECASE)
    cleaned = re.sub(r'^(?:dipl\.-?(?:ing|kfm|jur|oec)\.?\s+)', '', cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def clean_person_name_string(raw_name):
    if not raw_name: return False
    raw_name = strip_honorifics(re.sub(r'\s+', ' ', str(raw_name)).strip())
    raw_name = re.split(r'\s*(?:,|;|\||HRB|HRA|Tel\.?|Telefon|E-Mail|Email|geb\.?)\b', raw_name, maxsplit=1, flags=re.IGNORECASE)[0].strip(" .,:;-")
    if not raw_name or len(raw_name) > 80: return False
    words = raw_name.split()
    if not (2 <= len(words) <= 5): return False

    valid_capitalized = 0
    for w in words:
        clean_w = w.strip(".,:;")
        if not clean_w: return False
        lower_w = clean_w.lower()
        if lower_w in ALLOWED_LOWERCASE_PREFIXES: continue
        if lower_w in PERSON_STOPWORDS: return False
        if not re.match(r"^[A-ZÄÖÜÀ-ÖØ-Ý][A-Za-zÄÖÜäöüßÀ-ÿ'\-]*$", clean_w): return False
        valid_capitalized += 1

    return raw_name if valid_capitalized >= 2 else False


def extract_person_candidates(soup, page_type):
    candidates = []
    if not soup: return candidates
    page_bonus = PAGE_TYPE_SCORES.get(page_type.lower(), 15)

    text = soup.get_text(separator="\n")
    for line in text.splitlines():
        line_clean = line.strip()
        if not line_clean: continue
        role_match = ROLE_REGEX.search(line_clean)
        if role_match:
            matched_role = role_match.group(0).lower()
            role_score = ROLE_SCORES.get(matched_role, 50)
            potential_names_str = ROLE_REGEX.sub("", line_clean).strip(" :")

            raw_sub_names = re.split(r'\b(?:und|sowie|&|;)\b|[,/|\n]', potential_names_str, flags=re.IGNORECASE)
            for sub_name in raw_sub_names:
                cleaned_name = clean_person_name_string(sub_name)
                if cleaned_name:
                    candidates.append({"value": cleaned_name, "role": matched_role, "score": role_score + page_bonus, "source": f"dom_{page_type}"})
    return candidates


# ==============================================================================
# MATCHING & CANDIDATE SELECTION
# ==============================================================================

def select_best_candidate(candidates, candidate_type="company"):
    if not candidates: return None
    grouped = {}
    for candidate in candidates:
        raw_val = candidate.get("value", "")
        if not raw_val: continue

        if candidate_type == "person":
            val = strip_honorifics(raw_val)
            val = clean_person_name_string(val)
        elif candidate_type == "company":
            val = clean_company_name(raw_val)
        elif candidate_type == "email":
            val = raw_val.lower().strip().strip(".,:;()")
        elif candidate_type == "phone":
            val = raw_val.strip()
        else:
            val = raw_val.strip()

        if not val: continue

        key = re.sub(r"\s+", " ", val.lower()).strip()
        if key not in grouped:
            grouped[key] = {"value": val, "score": 0, "count": 0, "roles": set(), "sources": set(), "pages": set()}
        item = grouped[key]
        item["count"] += 1
        item["score"] = max(item["score"], float(candidate.get("score", 0)))
        if candidate.get("source"): item["sources"].add(candidate["source"])
        if candidate.get("page"): item["pages"].add(candidate["page"])
        if candidate.get("role"): item["roles"].add(candidate["role"])

    if not grouped: return None
    for item in grouped.values():
        item["final_score"] = item["score"] + min((item["count"] - 1) * 5, 20) + min(max(len(item["sources"]) - 1, 0) * 4, 12)

    best = max(grouped.values(), key=lambda x: x["final_score"])
    if candidate_type == "person" and best["final_score"] < 70: return None
    return {
        "value": best["value"], "score": round(best["score"], 2), "final_score": round(best["final_score"], 2),
        "count": best["count"], "sources": sorted(best["sources"]), "pages": sorted(best["pages"]), "roles": sorted(best["roles"])
    }


def extract_company_legal_terms(name):
    if not name: return set()
    text = str(name).lower()
    found = set()
    for term in LEGAL_TERMS_SORTED:
        if re.search(r"(?<!\w)" + re.escape(term.lower()) + r"(?!\w)", text):
            found.add(term.lower())
    return found


def score_company_identity(query, candidate_name):
    if not query or not candidate_name:
        return {"score": 0, "exact": False, "reason": "missing_value"}
    query_norm = normalize_company_string(query)
    candidate_norm = normalize_company_string(candidate_name)
    if not query_norm or not candidate_norm:
        return {"score": 0, "exact": False, "reason": "empty_normalized_value"}

    similarity = difflib.SequenceMatcher(None, query_norm, candidate_norm).ratio()
    score = similarity * 70
    if query_norm == candidate_norm: score += 30

    query_tokens = set(re.findall(r"[a-z0-9äöüß]+", str(query).lower())) - {normalize_company_string(t) for t in COMPANY_LEGAL_TERMS}
    candidate_tokens = set(re.findall(r"[a-z0-9äöüß]+", str(candidate_name).lower())) - {normalize_company_string(t) for t in COMPANY_LEGAL_TERMS}

    if query_tokens and candidate_tokens:
        intersection = query_tokens.intersection(candidate_tokens)
        token_ratio = len(intersection) / max(len(query_tokens), len(candidate_tokens))
        score += token_ratio * 25

    score = max(0, min(100, score))
    exact = (query_norm == candidate_norm or similarity >= 0.96)
    reason = "exact_or_near_exact" if exact else ("strong_match" if score >= 80 else "weak_match")
    return {
        "score": round(score, 2), "exact": exact, "reason": reason, "similarity": round(similarity * 100, 2),
        "query_normalized": query_norm, "candidate_normalized": candidate_norm,
        "query_legal_terms": sorted(extract_company_legal_terms(query)),
        "candidate_legal_terms": sorted(extract_company_legal_terms(candidate_name))
    }


def rank_company_candidates(query, candidates):
    ranked = []
    if not candidates: return ranked
    for candidate in candidates:
        candidate_name = candidate.get("value")
        if not candidate_name: continue
        identity = score_company_identity(query, candidate_name)
        extraction_score = float(candidate.get("score", 0))
        combined_score = (identity["score"] * 0.70) + (min(extraction_score, 120) / 120 * 30)
        ranked.append({
            **candidate, "identity_score": identity["score"], "identity_reason": identity["reason"],
            "identity_similarity": identity["similarity"], "combined_score": round(combined_score, 2),
            "query_legal_terms": identity["query_legal_terms"], "candidate_legal_terms": identity["candidate_legal_terms"]
        })
    ranked.sort(key=lambda x: x["combined_score"], reverse=True)
    return ranked


def select_best_company_for_query(query, candidates):
    ranked = rank_company_candidates(query, candidates)
    if not ranked or ranked[0]["combined_score"] < 50:
        return None
    best = ranked[0]
    return {
        "value": best["value"], "score": best.get("score", 0), "identity_score": best["identity_score"],
        "combined_score": best["combined_score"], "identity_reason": best["identity_reason"],
        "identity_similarity": best["identity_similarity"], "source": best.get("source"),
        "page": best.get("page"), "ranked_candidates": ranked[:8]
    }


def determine_match_status(resolved_info, company_match, has_email, has_phone, has_person):
    is_direct = bool(resolved_info and resolved_info.get("source") == "direct_input")

    if resolved_info and resolved_info.get("rejected"):
        return "⚠️ Unsicherer Treffer"

    # BEHOBEN: Bei Direkt-URL wird die Firmeneingabe automatisch als valider Kontext übernommen
    has_company = (company_match is not None) or is_direct

    if company_match:
        company_score = company_match.get("combined_score", 0)
        if company_score < 65 and not is_direct:
            return "⚠️ Unsicherer Treffer"
    elif not is_direct:
        if not has_email and not has_phone and not has_person:
            return "⚠️ Website erreichbar – Zuordnung unklar"

    if has_company and has_email and has_phone: return "✅ Erfolg"
    if has_company and has_email: return "🟢 E-Mail + Firma"
    if has_company and has_phone: return "🟡 Telefon + Firma"
    if has_company: return "🟠 Nur Firma"
    if has_email: return "🟢 Nur E-Mail"
    return "⚠️ Teilweise"


def build_company_matching_debug(query, candidates, selected):
    ranked = rank_company_candidates(query, candidates)
    return {
        "query": query, "candidate_count": len(candidates), "selected": selected,
        "candidates": [{
            "rank": idx, "name": c.get("value"), "source": c.get("source"), "page": c.get("page"),
            "extraction_score": c.get("score"), "identity_score": c.get("identity_score"),
            "combined_score": c.get("combined_score"), "reason": c.get("identity_reason")
        } for idx, c in enumerate(ranked[:10], start=1)]
    }


def build_base_url(url):
    parsed = urlparse(url)
    return f"{parsed.scheme or 'https'}://{parsed.netloc}" if parsed.netloc else ""


def is_same_domain(url_a, url_b):
    domain_a = normalize_domain(url_a)
    domain_b = normalize_domain(url_b)
    return bool(domain_a and domain_b and (domain_a == domain_b or domain_a.endswith("." + domain_b) or domain_b.endswith("." + domain_a)))


def search_email_in_google_index(domain, company_name, serper_key):
    if not serper_key: return "-", None
    domain = normalize_domain(f"https://{domain}")
    if not domain: return "-", None
    headers = {"X-API-KEY": serper_key.strip(), "Content-Type": "application/json"}
    found = []
    for query in [f'site:{domain} "@{domain}"', f'"{company_name}" "@{domain}"']:
        try:
            res = c_requests.post("https://google.serper.dev/search", headers=headers, json={"q": query, "num": 10}, timeout=8.0)
            if res.status_code == 200:
                for item in res.json().get("organic", []):
                    combined = " ".join([item.get("title", ""), item.get("snippet", ""), item.get("link", "")])
                    for em in re.findall(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", combined):
                        em = em.lower().strip(".,;:()[]<>")
                        if "@" in em and em.split("@", 1)[1] == domain and em not in found:
                            found.append(em)
        except Exception: continue
    if not found: return "-", None
    found.sort(key=lambda x: 100 if x.split("@")[0] in ["info", "kontakt", "contact", "office"] else 50, reverse=True)
    return found[0], found


# ==============================================================================
# V3 MASTER PIPELINE
# ==============================================================================

def scrape_single_lead_v3(input_lead, serper_key="", debug_mode=False):
    debug_log = {"input": input_lead, "pages_checked": [], "errors": [], "matching": {}}

    clean_check = input_lead.strip().lower()
    if not clean_check or clean_check in INVALID_INPUT_PATTERNS:
        return {
            "Vorname": "-", "Nachname": "-", "Unternehmensname": input_lead, "E-Mail-Adresse": "-",
            "Telefonnummer": "-", "Webseite": "-", "Weitere E-Mails": "-", "Status": "❌ Keine URL/Eingabe",
            "Eingabe": input_lead, "_debug": debug_log
        }

    res_info = resolve_company_to_website(input_lead, serper_key, debug_log)
    if not res_info:
        return {
            "Vorname": "Unknown", "Nachname": "Unknown", "Unternehmensname": input_lead, "E-Mail-Adresse": "-",
            "Telefonnummer": "-", "Webseite": "-", "Weitere E-Mails": "-", "Status": "❌ Suchfehler / Keine Website",
            "Eingabe": input_lead, "_debug": debug_log
        }

    url = res_info.get("url", "")
    debug_log["resolved_url"] = url
    debug_log["resolved_source"] = res_info.get("source")
    debug_log["resolved_match_score"] = res_info.get("match_score")

    domain = normalize_domain(url)
    base_url = build_base_url(url)

    session = create_http_session()
    main_fetch = fetch_html_page(url, session=session)
    debug_log["pages_checked"].append({
        "url": main_fetch.get("url"), "final_url": main_fetch.get("final_url"),
        "status": main_fetch.get("status_code"), "error": main_fetch.get("error"),
        "is_spa": main_fetch.get("is_spa", False)
    })

    if main_fetch.get("error") and not main_fetch.get("html"):
        return {
            "Vorname": "Unknown", "Nachname": "Unknown", "Unternehmensname": input_lead, "E-Mail-Adresse": "-",
            "Telefonnummer": "-", "Webseite": url, "Weitere E-Mails": "-", "Status": "❌ Website nicht erreichbar",
            "Eingabe": input_lead, "_debug": debug_log
        }

    main_html = main_fetch.get("html", "")
    main_soup = BeautifulSoup(main_html, "html.parser") if main_html else None
    final_url = main_fetch.get("final_url", url)
    final_domain = normalize_domain(final_url)
    if final_domain: domain = final_domain

    candidate_links = []
    if main_soup:
        for a_tag in main_soup.find_all("a", href=True):
            score = score_internal_link(a_tag.get("href", ""), a_tag.get_text(" ", strip=True), a_tag.get("title", ""))
            if score > 0:
                full_link = urljoin(final_url, a_tag['href'])
                if is_same_domain(full_link, final_url):
                    candidate_links.append((re.sub(r"(\?|#).*$", "", full_link), score))

    unique_links = {}
    for link, score in candidate_links:
        if link not in unique_links or score > unique_links[link]: unique_links[link] = score

    candidate_links = sorted(unique_links.items(), key=lambda x: x[1], reverse=True)
    fallback_urls = [urljoin(build_base_url(final_url) + "/", p) for p in ["impressum", "kontakt", "about"]]

    pages_to_check = [final_url] + [link for link, _ in candidate_links[:6]] + fallback_urls
    seen = set()
    final_pages = []
    for p in pages_to_check:
        norm_p = re.sub(r"(\?|#).*$", "", p).rstrip("/")
        if norm_p and norm_p not in seen:
            seen.add(norm_p)
            final_pages.append(p)
            if len(final_pages) >= MAX_PAGES_PER_SITE: break

    fetched_data = {final_url: main_fetch}
    subpages = [p for p in final_pages if p != final_url]

    if subpages:
        def fetch_subpage(page_url):
            thread_session = create_http_session()
            try: return fetch_html_page(page_url, session=thread_session)
            finally: close_http_session(thread_session)

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            future_map = {executor.submit(fetch_subpage, p): p for p in subpages}
            for future in concurrent.futures.as_completed(future_map):
                req_url = future_map[future]
                try: result = future.result()
                except Exception as exc:
                    result = {"url": req_url, "final_url": req_url, "html": "", "status_code": 0, "error": str(exc)}
                fetched_data[result.get("final_url") or req_url] = result
                debug_log["pages_checked"].append({
                    "url": result.get("url"), "final_url": result.get("final_url"),
                    "status": result.get("status_code"), "error": result.get("error")
                })

    close_http_session(session)

    all_emails, all_phones, all_companies, all_persons = [], [], [], []
    for p_url, p_data in fetched_data.items():
        p_html = p_data.get("html", "")
        if not p_html: continue
        try: p_soup = BeautifulSoup(p_html, "html.parser")
        except Exception: continue
        p_type = classify_page_type(p_url)

        try: all_emails.extend(extract_email_candidates(p_html, p_soup, p_url, p_type, domain))
        except Exception as e: debug_log["errors"].append(f"Email: {str(e)}")

        try: all_phones.extend(extract_phone_candidates(p_html, p_soup, p_url, p_type))
        except Exception as e: debug_log["errors"].append(f"Phone: {str(e)}")

        try: all_companies.extend(extract_company_candidates(p_soup, p_type))
        except Exception as e: debug_log["errors"].append(f"Company: {str(e)}")

        try: all_persons.extend(extract_person_candidates(p_soup, p_type))
        except Exception as e: debug_log["errors"].append(f"Person: {str(e)}")

    if not all_emails and serper_key:
        g_em, _ = search_email_in_google_index(domain, input_lead, serper_key)
        if g_em != "-": all_emails.append({"value": g_em, "score": 40, "source": "serper_google_index", "page": "search"})

    best_email = select_best_candidate(all_emails, candidate_type="email")
    best_phone = select_best_candidate(all_phones, candidate_type="phone")
    best_company = select_best_company_for_query(input_lead, all_companies)
    best_person = select_best_candidate(all_persons, candidate_type="person")

    debug_log["matching"] = build_company_matching_debug(input_lead, all_companies, best_company)
    debug_log["best_email"] = best_email
    debug_log["best_phone"] = best_phone
    debug_log["best_company"] = best_company
    debug_log["best_person"] = best_person

    primary_email = best_email["value"] if best_email else "-"
    secondary_emails = "-"
    if best_email:
        others = [e["value"] for e in all_emails if e.get("value") and e["value"] != primary_email]
        if others: secondary_emails = ", ".join(list(dict.fromkeys(others))[:3])

    phone = best_phone["value"] if best_phone else "-"
    company_val = best_company["value"] if best_company else (input_lead if res_info.get("source") == "direct_input" else "-")

    first_name, last_name = "Unknown", "Unknown"
    if best_person:
        parts = best_person["value"].split()
        if len(parts) == 1: first_name, last_name = "-", parts[0]
        else: first_name, last_name = " ".join(parts[:-1]), parts[-1]

    status_val = determine_match_status(
        res_info, best_company, primary_email != "-", phone != "-", best_person is not None
    )

    gc.collect()

    return {
        "Vorname": first_name, "Nachname": last_name, "Unternehmensname": company_val,
        "E-Mail-Adresse": primary_email, "Telefonnummer": phone, "Webseite": url,
        "Weitere E-Mails": secondary_emails, "Status": status_val, "Eingabe": input_lead,
        "_debug": debug_log
    }


# ==============================================================================
# STREAMLIT UI & QUEUE EXECUTION
# ==============================================================================

st.set_page_config(page_title="GYameli's Pro Scraper V3", page_icon="🚀", layout="wide")
st.title("🚀 GYameli's Pro Scraper V3")
st.caption("Website-Matching + Firmenidentifikation + Kontakt-Daten-Extraktion")

# SIDEBAR / EINSTELLUNGEN
st.sidebar.header("⚙️ Einstellungen")

serper_key = st.sidebar.text_input(
    "Serper API Key",
    type="password",
    help="Optional: Wird für die Google-Suche und den E-Mail-Fallback verwendet."
)

if serper_key.strip():
    st.sidebar.success("✅ Serper API aktiv")

debug_mode = st.sidebar.checkbox(
    "🔍 Debug-Modus",
    help="Zeigt Suchkandidaten, Matching-Entscheidungen, Scores, Fehler und Datenquellen."
)

def clear_text_input():
    st.session_state["lead_input_field"] = ""

# SESSION STATE
if "state" not in st.session_state: st.session_state.state = "idle"
if "results" not in st.session_state: st.session_state.results = []
if "queue" not in st.session_state: st.session_state.queue = []
if "completed_count" not in st.session_state: st.session_state.completed_count = 0
if "total_count" not in st.session_state: st.session_state.total_count = 0
if "start_time" not in st.session_state: st.session_state.start_time = None

input_text = st.text_area(
    "Leads eingeben (URLs oder Firmennamen, 1 pro Zeile)",
    height=200,
    placeholder="Müller Bau GmbH München\nwww.zalando.de\nHotel Adlon Berlin",
    key="lead_input_field"
)

col1, col2, col3, col4 = st.columns([1, 1, 1.5, 1.5])

with col1:
    if st.button("🚀 Neu Starten", type="primary"):
        lines = [line.strip() for line in input_text.splitlines() if line.strip()]
        if lines:
            st.session_state.queue = lines
            st.session_state.results = []
            st.session_state.completed_count = 0
            st.session_state.total_count = len(lines)
            st.session_state.start_time = time.time()
            st.session_state.state = "running"
            st.rerun()
        else:
            st.warning("Bitte mindestens einen Lead eingeben.")

with col2:
    if st.session_state.state == "running":
        if st.button("⏸️ Pausieren"):
            st.session_state.state = "paused"
            st.rerun()
    elif st.session_state.state == "paused":
        if st.button("▶️ Fortsetzen"):
            st.session_state.state = "running"
            st.rerun()

with col3:
    st.button("✏️ Eingabe löschen", on_click=clear_text_input)

with col4:
    if st.button("🗑️ Ergebnisse löschen"):
        st.session_state.results = []
        st.session_state.queue = []
        st.session_state.completed_count = 0
        st.session_state.total_count = 0
        st.session_state.start_time = None
        st.session_state.state = "idle"
        st.rerun()

progress_box = st.empty()


def update_progress_ui():
    if st.session_state.total_count <= 0: return
    done = st.session_state.completed_count
    total = st.session_state.total_count
    progress = min(done / total, 1.0)
    elapsed = int(time.time() - st.session_state.start_time) if st.session_state.start_time else 0
    success_count = sum(1 for r in st.session_state.results if r.get("Status", "").startswith(("✅", "🟢")))
    success_rate = int(success_count / done * 100) if done > 0 else 0
    eta_str = f"ca. {int((total - done) * (elapsed / done))}s" if done > 0 else "Berechne..."

    with progress_box.container():
        st.progress(progress)
        state_label = {"running": "🟢 Läuft", "paused": "⏸️ Pausiert", "idle": "✅ Fertig"}.get(st.session_state.state, st.session_state.state)
        st.markdown(f"**Status:** {state_label} | ⏱️ **Zeit:** {elapsed}s | ⏳ **Restzeit:** {eta_str} | 📊 **Fortschritt:** {done}/{total} | 🎯 **Erfolg:** {success_count} ({success_rate}%)")


if st.session_state.state in ["running", "paused"] or st.session_state.completed_count > 0:
    update_progress_ui()

if st.session_state.state == "running" and st.session_state.queue:
    batch_size = 3
    current_batch = st.session_state.queue[:batch_size]
    st.session_state.queue = st.session_state.queue[batch_size:]

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        future_to_input = {
            executor.submit(scrape_single_lead_v3, line, serper_key, debug_mode): line
            for line in current_batch
        }
        for future in concurrent.futures.as_completed(future_to_input):
            input_line = future_to_input[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {
                    "Vorname": "Unknown", "Nachname": "Unknown", "Unternehmensname": input_line,
                    "E-Mail-Adresse": "-", "Telefonnummer": "-", "Webseite": "-", "Weitere E-Mails": "-",
                    "Status": "❌ Interner Fehler", "Eingabe": input_line,
                    "_debug": {"input": input_line, "pages_checked": [], "errors": [f"Unhandled exception: {str(exc)}"]}
                }
            st.session_state.results.append(result)
            st.session_state.completed_count += 1
            update_progress_ui()

    gc.collect()

    if not st.session_state.queue:
        st.session_state.state = "idle"
        st.success("✅ Scraping vollständig beendet!")

    st.rerun()

if st.session_state.results:
    df_raw = pd.DataFrame(st.session_state.results)
    export_cols = [c for c in df_raw.columns if not c.startswith("_")]
    df_display = df_raw[export_cols].copy()
    df_display.index = range(1, len(df_display) + 1)

    st.subheader(f"📋 Ergebnisse Gesamt ({len(df_raw)} Leads)")
    st.dataframe(df_display, use_container_width=True, height=500)

    col_dl1, col_dl2 = st.columns([1, 1])

    with col_dl1:
        csv_data = df_display.to_csv(index=False, sep=";", encoding="utf-8-sig")
        st.download_button(
            "📊 Für Google Sheets herunterladen", data=csv_data,
            file_name="GYameli_V3.csv", mime="text/csv", use_container_width=True
        )

    with col_dl2:
        output_excel = io.BytesIO()
        with pd.ExcelWriter(output_excel, engine="openpyxl") as writer:
            df_display.to_excel(writer, index=False, sheet_name="Leads")
        output_excel.seek(0)
        st.download_button(
            "📥 Als Excel herunterladen", data=output_excel.getvalue(),
            file_name="GYameli_V3.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )

if debug_mode and st.session_state.results:
    st.subheader("🔍 Detaillierte Debug-Informationen")
    for index, result in enumerate(st.session_state.results, start=1):
        input_value = result.get("Eingabe", "-")
        status_value = result.get("Status", "-")
        with st.expander(f"#{index} | {input_value} → {status_value}"):
            debug_data = result.get("_debug", {})
            matching_decision = debug_data.get("matching_decision")
            if matching_decision:
                st.markdown("### 🎯 Matching-Entscheidung")
                match_cols = st.columns(4)
                with match_cols[0]: st.metric("Suchtreffer", str(matching_decision.get("resolved_match_score", "-")))
                with match_cols[1]: st.metric("Website-Firma", str(matching_decision.get("website_company", "-")))
                with match_cols[2]: st.metric("Firmen-Match", str(matching_decision.get("company_combined_score", "-")))
                with match_cols[3]: st.metric("Entscheidung", str(matching_decision.get("company_match_reason", "-")))

            st.markdown("### 🔎 Alle Matching-Kandidaten")
            candidates_debug = debug_data.get("matching", {}).get("candidates", [])
            if candidates_debug:
                st.dataframe(pd.DataFrame(candidates_debug), use_container_width=True, hide_index=True)

            st.markdown("### 🕷️ Crawl-Informationen")
            st.json(debug_data)
