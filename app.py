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
from bs4 import BeautifulSoup

try:
    from curl_cffi import requests as c_requests
    HAS_CURL_CFFI = True
except ImportError:
    import requests as c_requests
    HAS_CURL_CFFI = False

# ==============================================================================
# KONSTANTEN & FILTER-LISTEN
# ==============================================================================

HONORIFICS = ['dr.', 'dr', 'prof.', 'prof', 'dipl.-ing.', 'dipl.-kfm.', 'dipl.-jur.', 'dipl.-oec.', 'herr', 'frau', 'mr.', 'mrs.', 'ms.']

ALLOWED_LOWERCASE_PREFIXES = {'von', 'van', 'zu', 'zum', 'zur', 'de', 'del', 'der', 'den', 'la', 'le'}

COMPANY_LEGAL_TERMS = {
    'gmbh', 'ug', 'ag', 'kg', 'ohg', 'gbr', 'gmbh & co. kg', 'e.k.', 'e.kfr.', 'e.v.', 'ltd', 'limited', 'holding',
    'gesellschaft', 'haftungsbeschränkt', 'eingetragener kaufmann', 'eingetragene kauffrau', 'genossenschaft', 'verwaltung'
}

PERSON_STOPWORDS = {
    'hotel', 'gasthof', 'restaurant', 'pension', 'resort', 'ferienwohnung', 'ferienwohnungen', 'apartments', 'apartment',
    'zimmer', 'gästehaus', 'gastronomie', 'tourismus', 'tourist', 'service', 'team', 'kontakt', 'willkommen', 'rezeption',
    'buchung', 'reservierung', 'marketing', 'vertrieb', 'management', 'verwaltung', 'firma', 'unternehmen', 'geschäft',
    'immobilien', 'immobilienverwaltung', 'hausverwaltung', 'hotelbetrieb', 'webdesign', 'agentur', 'media', 'it', 'software',
    'riesige', 'aufenthalte', 'konzipiert', 'siehe', 'karte', 'unsere', 'unser', 'unseren', 'unseres', 'über', 'preise', 'cookies', 'datenschutz', 'agb',
    'impressum', 'angebot', 'angebote', 'uns', 'ihr', 'ihre', 'ihren', 'deutschland', 'germany', 'und', 'der', 'die', 'das', 'den', 'dem',
    'des', 'für', 'mit', 'von', 'aus', 'auf', 'straße', 'strasse', 'haus', 'stadt', 'telefon', 'fax', 'mail', 'email',
    'mo', 'di', 'mi', 'do', 'fr', 'sa', 'so', 'uhr', 'zeiten', 'öffnungszeiten', 'alle', 'rechte', 'vorbehalten', 'copyright',
    'seite', 'sehr', 'geehrte', 'inhalte', 'haftung', 'links', 'urheberrecht', 'widerspruch', 'angaben', 'erhältst', 'bekommst',
    'zugangsdaten', 'gebäude', 'einem', 'einer', 'einen', 'eines', 'dass', 'wenn', 'bitte', 'diese', 'dieser', 'nach', 'oder',
    'home', 'startseite', 'index', 'welcome', 'ansprechpartner', 'ansprechpartnerin', 'inhaber', 'inhaberin', 'geschäftsführer',
    'geschäftsführerin', 'geschäftsführung', 'vertreten', 'vertretungsberechtigt', 'vorstand', 'prokurist', 'prokuristin',
    'gesellschafter', 'gesellschafterin', 'gründer', 'gründerin', 'founder', 'owner', 'adresse',
    'herzlich', 'kontaktieren', 'jetzt', 'erfahren', 'mehr', 'leistungen'
}.union(COMPANY_LEGAL_TERMS)

AGENCY_KEYWORDS = [
    'design', 'webdesign', 'agentur', 'media', 'werbeagentur', 'marketing',
    'hosting', 'wordpress', 'jimdo', 'wix', 'typograf', 'it-service', 
    'software', 'dev', 'creator', 'disclaimer', 'datenschutz', 'webmaster',
    'provider', 'strato', 'ionos', 'hosteurope', 'netzwerk', 'pixel'
]

PRIORITY_PREFIXES = [
    'info@', 'kontakt@', 'contact@', 'empfang@', 'rezeption@', 'office@', 
    'service@', 'hallo@', 'hello@', 'buchhaltung@', 'mail@', 'post@', 
    'willkommen@', 'anfrage@', 'zentrale@'
]

INVALID_INPUT_PATTERNS = ['undefined', 'null', 'none', 'n/a', 'na', '-', 'no url', 'keine url', '']

PORTAL_DOMAINS = [
    'facebook.com', 'instagram.com', 'booking.com', 'holidaycheck.', 
    'tripadvisor.', 'airbnb.', 'charlottelovestotravel.com', 'pinterest.', 
    'expedia.', 'trivago.', 'hrs.de', 'linkedin.com', 'xing.com', 'youtube.com'
]

PAGE_TYPE_SCORES = {
    "impressum": 80,
    "legal": 75,
    "kontakt": 60,
    "about": 50,
    "team": 40,
    "homepage": 15
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

ROLE_PATTERN_STR = r"\b(?:" + "|".join(re.escape(r) for r in ROLE_SCORES.keys()) + r")\b"
ROLE_REGEX = re.compile(ROLE_PATTERN_STR, re.IGNORECASE)

# ==============================================================================
# HELFER & SEITEN-KLASSIFIZIERUNG
# ==============================================================================

def classify_page_type(url, link_text=""):
    val = f"{url} {link_text}".lower()
    if any(k in val for k in ['impressum', 'imprint', 'legal-notice', 'legalnotice']):
        return 'impressum'
    if any(k in val for k in ['legal', 'aviso-legal', 'mentions-legales']):
        return 'legal'
    if any(k in val for k in ['kontakt', 'contact', 'contact-us']):
        return 'kontakt'
    if any(k in val for k in ['ueber-uns', 'über-uns', 'about', 'about-us', 'company']):
        return 'about'
    if 'team' in val:
        return 'team'
    if any(k in val for k in ['datenschutz', 'privacy']):
        return 'datenschutz'
    return 'homepage'

def fetch_html(url):
    try:
        kwargs = {
            'timeout': 3.5,
            'headers': {'Accept-Language': 'de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7'}
        }
        if HAS_CURL_CFFI:
            kwargs['impersonate'] = "chrome110"
            
        res = c_requests.get(url, **kwargs)
        if res.status_code == 200:
            return res.text, res.url
    except Exception:
        pass
    return None, url

# ==============================================================================
# PERSONENEXTRAKTION & VALIDIERUNG
# ==============================================================================

def strip_honorifics(name_str):
    if not name_str:
        return ""
    cleaned = re.sub(r'^(?:(?:dr|prof)\.?\s+)+', '', str(name_str), flags=re.IGNORECASE)
    cleaned = re.sub(r'^(?:dipl\.-?(?:ing|kfm|jur|oec)\.?\s+)', '', cleaned, flags=re.IGNORECASE)
    return cleaned.strip()

def clean_person_name_string(raw_name):
    if not raw_name:
        return False
    
    raw_name = re.sub(r'\s+', ' ', str(raw_name)).strip()
    raw_name = strip_honorifics(raw_name)

    raw_name = re.split(
        r'\s*(?:,|;|\||HRB|HRA|Tel\.?|Telefon|E-Mail|Email|geb\.?|geboren|München|Berlin|Hamburg|Köln)\b',
        raw_name,
        maxsplit=1,
        flags=re.IGNORECASE
    )[0].strip()
    
    raw_name = raw_name.strip(" .,:;-")
    if not raw_name or len(raw_name) > 80:
        return False
    
    words = raw_name.split()
    if not (2 <= len(words) <= 5):
        return False

    valid_capitalized_words = 0
    for word in words:
        clean_word = word.strip(".,:;")
        if not clean_word:
            return False
        lower = clean_word.lower()

        if lower in ALLOWED_LOWERCASE_PREFIXES:
            continue

        if lower in PERSON_STOPWORDS:
            return False

        if not re.match(r"^[A-ZÄÖÜÀ-ÖØ-Ý][A-Za-zÄÖÜäöüßÀ-ÿ'\-]*$", clean_word):
            return False
            
        valid_capitalized_words += 1

    if valid_capitalized_words < 2:
        return False

    return raw_name

def is_valid_person_name(name_str):
    return clean_person_name_string(name_str) != False

def extract_jsonld_person_candidates(soup):
    candidates = []
    if not soup:
        return candidates
    
    scripts = soup.find_all('script', attrs={'type': re.compile(r'application/ld\+json', re.IGNORECASE)})
    
    def walk(obj):
        if isinstance(obj, dict):
            obj_type = obj.get('@type', '')
            if isinstance(obj_type, list):
                obj_type = ' '.join(str(x) for x in obj_type)
            obj_type = str(obj_type).lower()

            if 'person' in obj_type:
                name = obj.get('name')
                if isinstance(name, str):
                    clean = clean_person_name_string(name)
                    if clean:
                        candidates.append({'name': clean, 'score': 60, 'source': 'jsonld_person', 'role': 'person'})

            for key in ['founder', 'employee', 'author', 'creator']:
                value = obj.get(key)
                jsonld_score = 80 if key == 'founder' else 60
                
                if isinstance(value, dict):
                    name = value.get('name')
                    if isinstance(name, str):
                        clean = clean_person_name_string(name)
                        if clean:
                            candidates.append({'name': clean, 'score': jsonld_score, 'source': 'jsonld_' + key, 'role': key})
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict):
                            name = item.get('name')
                            if isinstance(name, str):
                                clean = clean_person_name_string(name)
                                if clean:
                                    candidates.append({'name': clean, 'score': jsonld_score, 'source': 'jsonld_' + key, 'role': key})

            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    for script in scripts:
        try:
            raw = script.string or script.get_text()
            if not raw:
                continue
            data = json.loads(raw)
            walk(data)
        except Exception:
            continue
    return candidates

def extract_person_candidates(soup, page_type="homepage"):
    candidates = []
    if not soup:
        return candidates
    
    candidates.extend(extract_jsonld_person_candidates(soup))
    page_bonus = PAGE_TYPE_SCORES.get(page_type.lower(), 15)
    
    soup_copy = BeautifulSoup(str(soup), 'html.parser')
    for tag in soup_copy.find_all(['br', 'p', 'div', 'tr', 'td', 'th', 'li', 'h1', 'h2', 'h3', 'h4', 'footer', 'header']):
        tag.append('\n')
        
    lines = [re.sub(r'\s+', ' ', line).strip() for line in soup_copy.get_text().split('\n') if line.strip()]

    for i, line in enumerate(lines):
        role_match = ROLE_REGEX.search(line)
        if role_match:
            matched_role = role_match.group(0).lower()
            role_score = ROLE_SCORES.get(matched_role, 50)

            after = line[role_match.end():].strip()
            after = re.sub(r'^[\s:,\-–—]+', '', after)
            
            if after:
                candidate = re.split(r'\s*(?:,|;|\||HRB|HRA|Tel\.?|Telefon|E-Mail|Email)\b', after, maxsplit=1, flags=re.IGNORECASE)[0].strip()
                clean = clean_person_name_string(candidate)
                if clean:
                    candidates.append({'name': clean, 'score': role_score + page_bonus, 'source': page_type.lower(), 'role': matched_role})

            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                clean = clean_person_name_string(next_line)
                if clean:
                    candidates.append({'name': clean, 'score': role_score + page_bonus + 5, 'source': page_type.lower(), 'role': matched_role})

    return candidates

def final_owner_validation(name_str):
    if not name_str or name_str == "Unknown":
        return False
    return is_valid_person_name(name_str)

def select_best_person_candidate(candidates):
    if not candidates:
        return "Unknown"

    grouped = {}
    for cand in candidates:
        raw_name = cand.get("name", "")
        clean_name = strip_honorifics(raw_name)
        cleaned_name = clean_person_name_string(clean_name)

        if not cleaned_name or not is_valid_person_name(cleaned_name):
            continue

        norm_key = cleaned_name.lower()
        source = cand.get("source", "homepage").lower()
        role = cand.get("role")
        base_score = cand.get("score", 0)

        if norm_key not in grouped:
            grouped[norm_key] = {
                "name": cleaned_name,
                "max_base_score": base_score,
                "count": 0,
                "sources": [],
                "roles": []
            }

        grouped[norm_key]["count"] += 1

        if source and source not in grouped[norm_key]["sources"]:
            grouped[norm_key]["sources"].append(source)

        if role and role.lower() not in grouped[norm_key]["roles"]:
            grouped[norm_key]["roles"].append(role.lower())

        if base_score > grouped[norm_key]["max_base_score"]:
            grouped[norm_key]["max_base_score"] = base_score

    if not grouped:
        return "Unknown"

    best_candidate_name = "Unknown"
    highest_score = -1

    for key, data in grouped.items():
        confirmation_bonus = min((data["count"] - 1) * 5, 20)
        final_score = data["max_base_score"] + confirmation_bonus

        if final_score > highest_score:
            highest_score = final_score
            best_candidate_name = data["name"]

    if highest_score < 70 or not final_owner_validation(best_candidate_name):
        return "Unknown"

    return best_candidate_name

def split_first_last_name(owner_str):
    if not owner_str or owner_str == "Unknown" or owner_str == "-":
        return "Unknown", "Unknown"
    
    parts = owner_str.strip().split()
    parts = [p for p in parts if p.lower() not in HONORIFICS]
    
    if len(parts) == 1:
        return "-", parts[0]
    elif len(parts) >= 2:
        return " ".join(parts[:-1]), parts[-1]
    return "Unknown", "Unknown"

# ==============================================================================
# UNTERNEHMENSEXTRAKTION & CANDIDATE-SCORING
# ==============================================================================

def extract_company_candidates(soup, page_type="homepage"):
    candidates = []
    if not soup:
        return candidates
    
    for script in soup.find_all('script', attrs={'type': re.compile(r'application/ld\+json', re.IGNORECASE)}):
        try:
            raw = script.string or script.get_text()
            if not raw:
                continue
            data = json.loads(raw)
            
            def walk_company(obj):
                if isinstance(obj, dict):
                    obj_type = str(obj.get('@type', '')).lower()
                    if any(k in obj_type for k in ['organization', 'localbusiness', 'corporation']):
                        name = obj.get('legalName') or obj.get('name')
                        if isinstance(name, str) and len(name.strip()) > 2:
                            candidates.append({'name': name.strip(), 'score': 110, 'source': 'jsonld'})
                    for value in obj.values():
                        walk_company(value)
                elif isinstance(obj, list):
                    for item in obj:
                        walk_company(item)
                        
            walk_company(data)
        except Exception:
            continue
            
    og_site = soup.find('meta', property='og:site_name')
    if og_site and og_site.get('content'):
        candidates.append({'name': og_site['content'].strip(), 'score': 100, 'source': 'og:site_name'})
        
    app_name = soup.find('meta', attrs={'name': 'application-name'})
    if app_name and app_name.get('content'):
        candidates.append({'name': app_name['content'].strip(), 'score': 90, 'source': 'meta'})
        
    for h1 in soup.find_all('h1')[:3]:
        name = re.sub(r'\s+', ' ', h1.get_text(' ', strip=True)).strip()
        if 3 <= len(name) <= 80:
            if not any(stop in name.lower() for stop in ['willkommen', 'herzlich', 'unsere leistungen', 'ihr partner', 'über uns']):
                candidates.append({'name': name, 'score': 70, 'source': 'h1'})
            
    title = soup.find('title')
    if title:
        title_text = re.sub(r'\s+', ' ', title.get_text(' ', strip=True)).strip()
        parts = re.split(r'\s*[|:–—]\s*', title_text)
        for part in parts[:2]:
            part = part.strip()
            if 3 <= len(part) <= 80:
                candidates.append({'name': part, 'score': 60, 'source': 'title'})
                
    return candidates

def clean_company_name(name):
    if not name:
        return None
    name = re.sub(r'\s+', ' ', str(name)).strip().strip(' |:-–—,.;')
    if not name or len(name) > 120:
        return None
    if name.lower() in {'startseite', 'homepage', 'home', 'willkommen', 'kontakt', 'contact', 'impressum', 'datenschutz', 'privacy', 'about', 'über uns'}:
        return None
    return name

def select_best_company_candidate(candidates):
    if not candidates:
        return "Unknown"
    grouped = {}
    for candidate in candidates:
        name = clean_company_name(candidate.get('name'))
        if not name:
            continue
        key = name.lower()
        if key not in grouped:
            grouped[key] = {'name': name, 'score': candidate.get('score', 0), 'count': 1}
        else:
            grouped[key]['score'] = max(grouped[key]['score'], candidate.get('score', 0))
            grouped[key]['count'] += 1
            
    if not grouped:
        return "Unknown"
        
    for item in grouped.values():
        item['final_score'] = item['score'] + min(item['count'] * 5, 15)
        
    best = max(grouped.values(), key=lambda x: x['final_score'])
    return best['name']

# ==============================================================================
# LINK-PRIORISIERUNG & CRAWLING
# ==============================================================================

def score_internal_link(link_text, href):
    value = f"{link_text} {href}".lower()
    score = 0
    if 'impressum' in value or 'imprint' in value:
        score += 100
    if 'legal-notice' in value or 'legalnotice' in value:
        score += 95
    if 'legal' in value or 'aviso-legal' in value:
        score += 85
    if 'kontakt' in value or 'contact' in value:
        score += 70
    if 'ueber-uns' in value or 'über-uns' in value or 'about' in value:
        score += 50
    if 'team' in value:
        score += 40
    if 'datenschutz' in value or 'privacy' in value:
        score += 10
    return score

# ==============================================================================
# E-MAIL & TELEFON EXTRAKTION
# ==============================================================================

def decode_cloudflare_email(cf_hex):
    try:
        key = int(cf_hex[:2], 16)
        return "".join([chr(int(cf_hex[i:i+2], 16) ^ key) for i in range(2, len(cf_hex), 2)])
    except Exception:
        return ""

def extract_all_emails_advanced(html_content, soup, domain=""):
    if not html_content: 
        return "-", "-"
    found_raw = []

    if soup:
        for elem in soup.find_all(attrs={"data-cfemail": True}):
            decoded = decode_cloudflare_email(elem['data-cfemail'])
            if decoded: 
                found_raw.append(decoded)

        for a in soup.find_all('a', href=True):
            href = a['href'].lower()
            if 'mailto:' in href:
                email = href.split('mailto:')[-1].split('?')[0].strip()
                if email: 
                    found_raw.append(email)

    text = html_content
    text = re.sub(r'(?i)\s*[\(\[]\s*at\s*[\)\]]\s*', '@', text)
    text = re.sub(r'(?i)\s*[\(\[]\s*punkt\s*[\)\]]\s*', '.', text)
    text = re.sub(r'(?i)\s*\[dot\]\s*', '.', text)
    text = text.replace('&#64;', '@').replace('&#x40;', '@').replace('%40', '@')
    text = re.sub(r'(?i)([a-zA-Z0-9._%+-]+)\s+at\s+([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', r'\1@\2', text)
    
    standard_emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
    found_raw.extend(standard_emails)

    clean_emails = []
    for e in found_raw:
        el = e.lower().strip()
        if any(el.endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp']): continue
        if any(bad in el for bad in ['example.com', 'wixpress', 'sentry.io', 'schema.org', 'domain.com']): continue
        if any(agency_word in el for agency_word in AGENCY_KEYWORDS): continue
        if '@' in el and '.' in el.split('@')[-1]:
            clean_emails.append(el)
            
    clean_unique = list(set(clean_emails))
    if not clean_unique: 
        return "-", "-"

    domain_match = []
    priority_pref = []
    others = []
    
    clean_dom = domain.lower().replace('www.', '') if domain else ""
    
    for email in clean_unique:
        email_dom = email.split('@')[-1].lower()
        
        is_exact_domain = False
        if clean_dom:
            is_exact_domain = (email_dom == clean_dom) or email_dom.endswith('.' + clean_dom)

        if clean_dom and is_exact_domain:
            domain_match.append(email)
        elif any(email.startswith(pref) for pref in PRIORITY_PREFIXES):
            priority_pref.append(email)
        else:
            others.append(email)
            
    final_ordered = domain_match + priority_pref + others
    primary_email = final_ordered[0]
    secondary_emails = ", ".join(final_ordered[1:]) if len(final_ordered) > 1 else "-"
    
    return primary_email, secondary_emails

def clean_and_format_phone(raw_phone):
    if not raw_phone or raw_phone == "-": return "-"
    cleaned = re.sub(r'[^\d+]', '', raw_phone)
    
    if cleaned.startswith('0049'):
        cleaned = '+49' + cleaned[4:]
    elif cleaned.startswith('0') and not cleaned.startswith('00'):
        cleaned = '+49' + cleaned[1:]
    elif cleaned.startswith('49') and not cleaned.startswith('+'):
        cleaned = '+' + cleaned
    elif not cleaned.startswith('+') and len(cleaned) >= 6:
        cleaned = '+49' + cleaned

    digits = re.sub(r'\D', '', cleaned)
    if 8 <= len(digits) <= 15:
        return cleaned
    return "-"

def extract_phone_advanced(soup, text):
    if soup:
        for a in soup.find_all('a', href=True):
            href = a['href'].lower()
            if 'tel:' in href:
                raw_tel = href.split('tel:')[-1].strip()
                res = clean_and_format_phone(raw_tel)
                if res != "-": 
                    return res

    if text:
        patterns = [
            r'(?:Tel(?:efon)?|Fon|Mobil|Mobile|Phone|Call)\s*[:\.]?\s*(\+?[0-9\s\/\-\(\)]{8,25})',
            r'(\+49\s*[0-9\s\/\-\(\)]{8,20})',
            r'(0[1-9][0-9]{1,4}\s*[\/\-]?\s*[0-9\s\-]{5,15})'
        ]
        for p in patterns:
            match = re.search(p, text, re.IGNORECASE)
            if match:
                res = clean_and_format_phone(match.group(1))
                if res != "-": 
                    return res
    return "-"

# ==============================================================================
# ROUTING & EXTERNE APIs (SERPER / DUCKDUCKGO)
# ==============================================================================

def clean_portal_url_to_name(url_str):
    try:
        path = unquote(urlparse(url_str).path)
        parts = [p for p in path.split('/') if p]
        if parts:
            name_part = parts[0].replace('-', ' ').replace('_', ' ')
            name_part = re.sub(r'\d+$', '', name_part).strip()
            if len(name_part) > 3:
                return name_part
    except Exception:
        pass
    return url_str

def find_website_from_name(query, serper_key=""):
    query = query.strip()
    
    if any(portal in query.lower() for portal in PORTAL_DOMAINS):
        query = clean_portal_url_to_name(query)

    if "." in query and " " not in query and not any(portal in query.lower() for portal in PORTAL_DOMAINS):
        if not query.startswith('http'):
            return "https://" + query
        return query
        
    if serper_key:
        try:
            headers = {'X-API-KEY': serper_key.strip(), 'Content-Type': 'application/json'}
            payload = {'q': f"{query} offizielle website OR impressum OR imprint", 'num': 2}
            res = c_requests.post('https://google.serper.dev/search', headers=headers, json=payload, timeout=2.5)
            if res.status_code == 200:
                data = res.json()
                for item in data.get('organic', []):
                    link = item.get('link', '')
                    if link and not any(bad in link.lower() for bad in PORTAL_DOMAINS + ['northdata', 'gelbeseiten']):
                        return link
        except Exception:
            pass

    time.sleep(0.2)
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query + " website OR impressum OR imprint", max_results=2))
            for res in results:
                href = res.get('href', '').lower()
                if href and not any(bad in href for bad in PORTAL_DOMAINS + ['northdata']):
                    return res['href']
    except Exception:
        pass
    return None

def search_email_in_google_index(domain, company_name, serper_key):
    if not serper_key: return "-", "-"
    try:
        headers = {'X-API-KEY': serper_key.strip(), 'Content-Type': 'application/json'}
        search_q = f'site:{domain} "@"' if domain else f'"{company_name}" email OR kontakt "@"'
        payload = {'q': search_q, 'num': 3}
        res = c_requests.post('https://google.serper.dev/search', headers=headers, json=payload, timeout=3.0)
        if res.status_code == 200:
            data = res.json()
            combined_text = ""
            for item in data.get('organic', []):
                combined_text += " " + item.get('snippet', '') + " " + item.get('title', '')
            p_email, s_emails = extract_all_emails_advanced(combined_text, None, domain)
            if p_email != "-": 
                return p_email, s_emails
    except Exception:
        pass
    return "-", "-"

# ==============================================================================
# FINALER DATENFLOW SCRAPE_COMPANY()
# ==============================================================================

def scrape_company(original_input, serper_key=""):
    clean_check = original_input.strip().lower()
    if not clean_check or clean_check in INVALID_INPUT_PATTERNS or 'undefined' in clean_check:
        return {
            "Vorname": "-", "Nachname": "-", "Unternehmensname": original_input,
            "E-Mail-Adresse": "-", "Telefonnummer": "-", "Webseite": "-",
            "Weitere E-Mails": "-", "Status": "❌ Keine URL/Eingabe", "Eingabe": original_input
        }

    url = find_website_from_name(original_input, serper_key)
    if not url:
        return {
            "Vorname": "Unknown", "Nachname": "Unknown", "Unternehmensname": original_input,
            "E-Mail-Adresse": "-", "Telefonnummer": "-", "Webseite": "-",
            "Weitere E-Mails": "-", "Status": "❌ Keine Webseite", "Eingabe": original_input
        }

    domain = urlparse(url).netloc.replace('www.', '')
    base_url = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    fallback_company = domain.split('.')[0].capitalize()
    
    html_texts = []
    soups = []
    loaded_pages_dict = {}
    candidate_links_tuples = []

    main_html, current_url = fetch_html(url)
    if main_html:
        soup = BeautifulSoup(main_html, 'html.parser')
        soups.append(soup)
        html_texts.append(main_html)
        loaded_pages_dict[url] = (main_html, soup)

        for a_tag in soup.find_all('a', href=True):
            href = a_tag.get('href', '').lower()
            text = a_tag.get_text(" ", strip=True)
            score = score_internal_link(text, href)
            if score > 0:
                full_link = urljoin(current_url, a_tag['href'])
                if urlparse(full_link).netloc.replace('www.', '') == domain:
                    clean_link = re.sub(r'(\?|#).*$', '', full_link)
                    if clean_link not in [l[0] for l in candidate_links_tuples]:
                        candidate_links_tuples.append((clean_link, score))

    candidate_links_tuples = sorted(candidate_links_tuples, key=lambda x: x[1], reverse=True)
    candidate_links = [link for link, score in candidate_links_tuples[:6]]

    fallback_paths = [
        base_url + '/impressum', base_url + '/imprint', base_url + '/legal-notice', 
        base_url + '/legal', base_url + '/kontakt', base_url + '/contact'
    ]
    
    pages_to_check = [url] + candidate_links + fallback_paths
    seen = set()
    final_pages = []
    for p in pages_to_check:
        if p not in seen and len(final_pages) < 8:
            seen.add(p)
            final_pages.append(p)

    all_person_candidates = []
    all_company_candidates = []
    all_phones = []

    for page in final_pages:
        if page in loaded_pages_dict:
            page_html, page_soup = loaded_pages_dict[page]
        else:
            page_html, _ = fetch_html(page)
            if not page_html:
                continue
            page_soup = BeautifulSoup(page_html, 'html.parser')
            soups.append(page_soup)
            html_texts.append(page_html)
            loaded_pages_dict[page] = (page_html, page_soup)

        p_type = classify_page_type(page)

        all_person_candidates.extend(extract_person_candidates(page_soup, page_type=p_type))
        all_company_candidates.extend(extract_company_candidates(page_soup, page_type=p_type))

        curr_text = page_soup.get_text(" ", strip=True)
        phone_found = extract_phone_advanced(page_soup, curr_text)
        if phone_found != "-":
            all_phones.append((phone_found, 100 if p_type in ['impressum', 'kontakt'] else 50))

    combined_html = "\n".join(html_texts)
    main_soup = soups[0] if soups else None

    primary_email, secondary_emails = extract_all_emails_advanced(combined_html, main_soup, domain)
    if primary_email == "-" and serper_key:
        g_primary, g_secondary = search_email_in_google_index(domain, original_input, serper_key)
        if g_primary != "-":
            primary_email = g_primary
            secondary_emails = g_secondary

    phone = "-"
    if all_phones:
        phone = sorted(all_phones, key=lambda x: x[1], reverse=True)[0][0]

    owner_raw = select_best_person_candidate(all_person_candidates)
    first_name, last_name = split_first_last_name(owner_raw)

    company_name = select_best_company_candidate(all_company_candidates)
    if company_name == "Unknown":
        company_name = original_input if original_input != url else fallback_company

    status_val = "✅ Erfolg" if primary_email != "-" else ("⚠️ Teilweise" if (phone != "-" or owner_raw != "Unknown") else "❌ Keine Daten")

    del html_texts
    del soups
    del combined_html
    gc.collect()

    return {
        "Vorname": first_name,
        "Nachname": last_name,
        "Unternehmensname": company_name,
        "E-Mail-Adresse": primary_email,
        "Telefonnummer": phone,
        "Webseite": base_url,
        "Weitere E-Mails": secondary_emails,
        "Status": status_val,
        "Eingabe": original_input
    }

# ==============================================================================
# STREAMLIT USER INTERFACE
# ==============================================================================

st.set_page_config(page_title="GYameli's Pro Scraper V2", page_icon="🚀", layout="wide")

st.title("🚀 GYameli's Pro Scraper V2")
st.markdown("Füge deine Unternehmensnamen oder URLs ein (z. B. direkt aus **Spalte A einer Excel-Tabelle**).")

st.sidebar.header("⚡ Serper.dev API (Optional)")
serper_key = st.sidebar.text_input("Serper API Key", type="password", help="Bypass für DuckDuckGo & Google-Index Fallback.")

if serper_key:
    st.sidebar.success("🔥 Google Search (Serper) aktiv!")
else:
    st.sidebar.info("💡 Tipp: Trage den Serper-Key ein, um versteckte E-Mails aus dem Google-Index abzurufen.")

if "state" not in st.session_state:
    st.session_state.state = "idle"
if "results" not in st.session_state:
    st.session_state.results = []
if "queue" not in st.session_state:
    st.session_state.queue = []
if "completed_count" not in st.session_state:
    st.session_state.completed_count = 0
if "total_count" not in st.session_state:
    st.session_state.total_count = 0
if "start_time" not in st.session_state:
    st.session_state.start_time = None
if "lead_text_area" not in st.session_state:
    st.session_state.lead_text_area = ""

def clear_input_box():
    st.session_state.lead_text_area = ""

input_text = st.text_area(
    "Leads eingeben (1 pro Zeile, unbegrenzt)", 
    height=200, 
    placeholder="Müller Bau GmbH München\nwww.zalando.de\nhttps://www.facebook.com/Gaestehaus-Beispiel\nundefined",
    key="lead_text_area"
)

col1, col2, col3, col4 = st.columns([1, 1, 1, 2])

with col1:
    if st.button("🚀 Neu Starten", type="primary"):
        lines = [line.strip() for line in input_text.split('\n') if line.strip()]
        if lines:
            st.session_state.queue = lines
            st.session_state.results = []
            st.session_state.completed_count = 0
            st.session_state.total_count = len(lines)
            st.session_state.start_time = time.time()
            st.session_state.state = "running"
            st.rerun()

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
    st.button("🗑️ Eingabe löschen", on_click=clear_input_box)

progress_box = st.empty()

def update_progress_ui():
    if st.session_state.total_count > 0:
        done = st.session_state.completed_count
        total = st.session_state.total_count
        progress = done / total
        elapsed = int(time.time() - st.session_state.start_time) if st.session_state.start_time else 0
        
        erfolg_count = sum(1 for r in st.session_state.results if r.get('Status') == '✅ Erfolg')
        success_rate = int((erfolg_count / done) * 100) if done > 0 else 0
        
        if done > 0:
            avg_per_lead = elapsed / done
            remaining_leads = total - done
            eta_seconds = int(remaining_leads * avg_per_lead)
            eta_m, eta_s = divmod(eta_seconds, 60)
            eta_str = f"ca. {eta_m}m {eta_s}s"
        else:
            eta_str = "Berechne..."

        with progress_box.container():
            st.progress(progress)
            if st.session_state.state == "running":
                st.markdown(
                    f"⏱️ **Zeit:** {elapsed}s | "
                    f"⏳ **Restzeit:** {eta_str} | "
                    f"📊 **Fortschritt:** {done}/{total} Leads ({int(progress * 100)}%) | "
                    f"🎯 **Erfolgsquote:** {erfolg_count}/{done} ({success_rate}%)"
                )
            elif st.session_state.state == "paused":
                st.warning(
                    f"⏸️ **Pausiert nach {elapsed}s:** {done}/{total} Leads verarbeitet. "
                    f"🎯 **Erfolgsquote:** {erfolg_count}/{done} ({success_rate}%)."
                )

if st.session_state.state in ["running", "paused"] or st.session_state.completed_count > 0:
    update_progress_ui()

if st.session_state.state == "running" and st.session_state.queue:
    batch_size = 5
    current_batch = st.session_state.queue[:batch_size]
    st.session_state.queue = st.session_state.queue[batch_size:]
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        future_to_input = {
            executor.submit(scrape_company, line, serper_key): line 
            for line in current_batch
        }
        for future in concurrent.futures.as_completed(future_to_input):
            st.session_state.results.append(future.result())
            st.session_state.completed_count += 1
            update_progress_ui()
            
    gc.collect() 
            
    if not st.session_state.queue:
        st.session_state.state = "idle"
        erfolg_final = sum(1 for r in st.session_state.results if r.get('Status') == '✅ Erfolg')
        rate_final = int((erfolg_final / st.session_state.completed_count) * 100) if st.session_state.completed_count > 0 else 0
        st.success(f"✅ Scraping vollständig beendet! {st.session_state.completed_count} Leads in {int(time.time() - st.session_state.start_time)}s verarbeitet. 🎯 Finale Erfolgsquote: {erfolg_final}/{st.session_state.completed_count} ({rate_final}%).")
    
    st.rerun()

if st.session_state.results:
    df_raw = pd.DataFrame(st.session_state.results)
    
    st.subheader(f"📋 Ergebnisse Gesamt ({len(df_raw)} Leads)")
    
    export_filter = st.radio(
        "🎯 Filter für Ansicht & Export wählen:",
        ["Alle Ergebnisse (Erfolg, Teilweise & Fehler)", "Nur Ergebnisse mit Status '✅ Erfolg' (inkl. E-Mail)"],
        horizontal=True
    )
    
    if export_filter == "Nur Ergebnisse mit Status '✅ Erfolg' (inkl. E-Mail)":
        df_display = df_raw[df_raw['Status'] == "✅ Erfolg"].copy()
    else:
        df_display = df_raw.copy()
        
    df_display.index = range(1, len(df_display) + 1)
    
    st.dataframe(df_display, use_container_width=True)
    
    if df_display.empty:
        st.warning("Keine Leads entsprechen dem gewählten Filter.")
    else:
        csv_data = df_display.to_csv(index=False, sep=';', encoding='utf-8-sig')
        
        col_dl1, col_dl2 = st.columns([1, 1])
        with col_dl1:
            st.download_button(
                label=f"📊 Für Google Sheets herunterladen ({len(df_display)} Leads)",
                data=csv_data,
                file_name="GYameli_Leads_GoogleSheets.csv",
                mime="text/csv"
            )
        with col_dl2:
            output_excel = io.BytesIO()
            with pd.ExcelWriter(output_excel, engine='openpyxl') as writer:
                df_display.to_excel(writer, index=False)
            output_excel.seek(0)
            
            st.download_button(
                label=f"📥 Als Excel herunterladen ({len(df_display)} Leads)",
                data=output_excel,
                file_name="GYameli_Leads.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
