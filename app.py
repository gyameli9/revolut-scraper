import streamlit as st
import requests
from bs4 import BeautifulSoup
import re
import pandas as pd
import concurrent.futures
from urllib.parse import urljoin, urlparse
from duckduckgo_search import DDGS
import io
import time

# --- 1. FILTER & EXTRAKTIONS-LOGIK ---

AGENCY_KEYWORDS = [
    'design', 'webdesign', 'agentur', 'media', 'werbeagentur', 'marketing',
    'hosting', 'wordpress', 'jimdo', 'wix', 'typograf', 'it-service', 
    'software', 'dev', 'creator', 'disclaimer', 'datenschutz', 'webmaster',
    'provider', 'strato', 'ionos', 'hosteurope', 'netzwerk', 'pixel'
]

PRIORITY_PREFIXES = [
    'info@', 'empfang@', 'kontakt@', 'contact@', 'buchhaltung@', 'office@', 
    'hallo@', 'hello@', 'service@', 'rezeption@', 'mail@', 'post@', 
    'willkommen@', 'anfrage@', 'zentrale@'
]

GERMAN_STOPWORDS = {
    'riesige', 'aufenthalte', 'konzipiert', 'siehe', 'karte', 'unsere', 'über',
    'hotel', 'zimmer', 'preise', 'cookies', 'datenschutz', 'agb', 'impressum',
    'kontakt', 'willkommen', 'angebot', 'angebote', 'service', 'uns', 'ihr',
    'deutschland', 'germany', 'gmbh', 'co', 'kg', 'ag', 'ltd', 'und', 'der',
    'die', 'das', 'den', 'dem', 'des', 'für', 'mit', 'von', 'aus', 'auf',
    'straße', 'strasse', 'haus', 'stadt', 'telefon', 'fax', 'mail', 'email',
    'mo', 'di', 'mi', 'do', 'fr', 'sa', 'so', 'uhr', 'zeiten', 'öffnungszeiten',
    'alle', 'rechte', 'vorbehalten', 'copyright', 'seite', 'sehr', 'geehrte',
    'inhalte', 'haftung', 'links', 'urheberrecht', 'widerspruch', 'angaben',
    'erhältst', 'bekommst', 'zugangsdaten', 'gebäude', 'einem', 'einer', 'einen',
    'eines', 'dass', 'wenn', 'bitte', 'diese', 'dieser', 'nach', 'oder'
}

def decode_cloudflare_email(cf_hex):
    try:
        key = int(cf_hex[:2], 16)
        return "".join([chr(int(cf_hex[i:i+2], 16) ^ key) for i in range(2, len(cf_hex), 2)])
    except:
        return ""

def extract_all_emails_advanced(html_content, soup, domain=""):
    if not html_content: return "-"
    found_raw = []

    if soup:
        for elem in soup.find_all(attrs={"data-cfemail": True}):
            decoded = decode_cloudflare_email(elem['data-cfemail'])
            if decoded: found_raw.append(decoded)

        for a in soup.find_all('a', href=True):
            href = a['href'].lower()
            if 'mailto:' in href:
                email = href.split('mailto:')[-1].split('?')[0].strip()
                if email: found_raw.append(email)

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
    if not clean_unique: return "-"

    priority = []
    others = []
    
    for email in clean_unique:
        if any(email.startswith(pref) for pref in PRIORITY_PREFIXES):
            priority.append(email)
        elif domain and domain in email.split('@')[-1]:
            priority.append(email)
        else:
            others.append(email)
            
    final_ordered = priority + others
    return ", ".join(final_ordered)

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
                if res != "-": return res

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
                if res != "-": return res
    return "-"

def is_valid_person_name(candidate_str):
    """Prüft strikt, ob der String aus 2 bis 3 gültigen Namenswörtern besteht."""
    words = [w.strip(".,:;()[]\"'") for w in candidate_str.split() if w.strip(".,:;()[]\"'")]
    if not (2 <= len(words) <= 3):
        return False
        
    for w in words:
        w_lower = w.lower()
        if w_lower in GERMAN_STOPWORDS or len(w) < 2:
            return False
        # Wort muss mit einem Großbuchstaben beginnen und ein echter Name sein
        if not re.match(r'^[A-ZÄÖÜ][a-zäöüß\-]+$', w):
            return False
            
    return " ".join(words)

def extract_owner_advanced(soup, raw_html):
    """Präzisions-Erkennung für Inhaber, GFs und Holdings mit Unknown Fallback"""
    if not raw_html: return "Unknown"
    
    if soup:
        soup_copy = BeautifulSoup(str(soup), 'html.parser')
        for tag in soup_copy.find_all(["br", "p", "div", "tr", "li", "h1", "h2", "h3", "h4"]):
            tag.append("\n")
        lines = [re.sub(r'\s+', ' ', line).strip() for line in soup_copy.get_text().split('\n') if line.strip()]
    else:
        lines = [re.sub(r'\s+', ' ', line).strip() for line in raw_html.split('\n') if line.strip()]

    roles = [
        'geschäftsführerin', 'geschäftsführer', 'geschäftsführung', 'vertreten durch',
        'inhaberin', 'inhaber', 'inh.', 'gf', 'ceo', 'coo', 'cfo', 'vorstand',
        'prokurist', 'prokuristin', 'gründerin', 'gründer', 'founder', 'owner',
        'managing director', 'director', 'gesellschafterin', 'gesellschafter',
        'komplementär', 'komplementärin', 'vertretungsberechtigt', 'ansprechpartner'
    ]

    for i, line in enumerate(lines):
        line_lower = line.lower()
        for role in roles:
            if role in line_lower:
                after_role = re.sub(r'(?i)^.*?' + re.escape(role) + r'\s*[:|-]?\s*', '', line).strip()
                
                # Check A: Holding / Muttergesellschaft
                if any(corp in after_role.lower() for corp in ['gmbh', 'ag', 'kg', 'ltd', 'holding', 'verwaltungs']):
                    corp_match = re.search(r'([A-ZÄÖÜ0-9][A-Za-z0-9ÄÖÜäöüß\s\.\&\-]+\s*(?:GmbH|AG|KG|Ltd|Holding|Verwaltungs\s*GmbH))', after_role, re.IGNORECASE)
                    if corp_match: return corp_match.group(1).strip()

                # Check B: Personennamen auf derselben Zeile (Strikte 2-3 Wörter Prüfung)
                if after_role:
                    valid_name = is_valid_person_name(after_role)
                    if valid_name: return valid_name

                # Check C: Folgezeile prüfen (HTML <br> Fall)
                if i + 1 < len(lines):
                    next_line = lines[i+1].strip()
                    if any(corp in next_line.lower() for corp in ['gmbh', 'ag', 'kg', 'ltd', 'holding']):
                        corp_match = re.search(r'([A-ZÄÖÜ0-9][A-Za-z0-9ÄÖÜäöüß\s\.\&\-]+\s*(?:GmbH|AG|KG|Ltd|Holding))', next_line, re.IGNORECASE)
                        if corp_match: return corp_match.group(1).strip()

                    valid_name = is_valid_person_name(next_line)
                    if valid_name: return valid_name

    return "Unknown"

def find_website_from_name(query):
    query = query.strip()
    if "." in query and " " not in query:
        if not query.startswith('http'): return "https://" + query
        return query
    try:
        results = DDGS().text(query + " website OR impressum", max_results=2)
        for res in results:
            href = res['href'].lower()
            if not any(bad in href for bad in ['linkedin.com', 'xing.com', 'wikipedia.org', 'northdata', 'gelbeseiten']):
                return res['href']
    except: pass
    return None

def scrape_company(original_input):
    url = find_website_from_name(original_input)
    if not url:
        return {
            "Eingabe": original_input,
            "Unternehmensname": original_input,
            "Inhaber / GF / Contact": "Unknown",
            "Telefonnummer": "-",
            "E-Mail-Adresse": "-",
            "Webseite": "-",
            "Status": "❌ Keine Webseite"
        }

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7'
    }
    
    domain = urlparse(url).netloc.replace('www.', '')
    base_url = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    pages_to_check = [url, base_url]
    company_name = original_input
    html_texts = []
    soups = []
    
    try:
        res = requests.get(url, headers=headers, timeout=5, allow_redirects=True)
        current_url = res.url
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            soups.append(soup)
            html_texts.append(res.text)
            
            og_site = soup.find('meta', property='og:site_name')
            if og_site and og_site.get('content'):
                company_name = og_site['content'].strip()
            elif title_tag := soup.find('title'):
                title_text = title_tag.text.split('|')[0].split('-')[0].strip()
                if title_text: company_name = title_text

            keywords = ['impressum', 'kontakt', 'contact', 'about', 'legal', 'imprint', 'team']
            for a_tag in soup.find_all('a', href=True):
                href = a_tag.get('href', '').lower()
                text = a_tag.get_text().lower()
                if any(k in href for k in keywords) or any(k in text for k in keywords):
                    pages_to_check.append(urljoin(current_url, a_tag['href']))
    except:
        pages_to_check = [url]

    pages_to_check.extend([base_url + '/impressum', base_url + '/kontakt'])
    pages_to_check = list(set(pages_to_check))
    
    for page in pages_to_check:
        try:
            r = requests.get(page, headers=headers, timeout=5)
            if r.status_code == 200:
                soup_page = BeautifulSoup(r.text, 'html.parser')
                soups.append(soup_page)
                html_texts.append(r.text)
        except: continue
            
    combined_html = "\n".join(html_texts)
    main_soup = soups[0] if soups else None
    
    emails_formatted = extract_all_emails_advanced(combined_html, main_soup, domain)
    owner = extract_owner_advanced(main_soup, combined_html)
    phone = extract_phone_advanced(main_soup, combined_html)
    
    return {
        "Eingabe": original_input,
        "Unternehmensname": company_name,
        "Inhaber / GF / Contact": owner,
        "Telefonnummer": phone,
        "E-Mail-Adresse": emails_formatted,
        "Webseite": base_url,
        "Status": "✅ Erfolg" if emails_formatted != "-" or phone != "-" or owner != "Unknown" else "⚠️ Teilweise"
    }

# --- 2. USER INTERFACE (STATE & BUTTONS) ---

st.set_page_config(page_title="GYameli's Pro Scraper", page_icon="🚀", layout="wide")

st.title("🚀 GYameli's Pro Scraper")
st.markdown("Füge deine Unternehmensnamen oder URLs ein (z. B. direkt aus **Spalte A einer Excel-Tabelle**).")

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
if "input_text_val" not in st.session_state:
    st.session_state.input_text_val = ""

# Eingabefeld mit Session-State-Verknüpfung
input_text = st.text_area(
    "Leads eingeben (1 pro Zeile, bis zu 300 Einträge)", 
    value=st.session_state.input_text_val,
    height=200, 
    placeholder="Müller Bau GmbH München\nwww.zalando.de\nHotel Adlon Berlin\nhaecken.com",
    key="lead_text_area"
)

col1, col2, col3, col4 = st.columns([1, 1, 1, 2])

with col1:
    if st.button("🚀 Neu Starten", type="primary"):
        lines = [line.strip() for line in input_text.split('\n') if line.strip()]
        if lines:
            st.session_state.input_text_val = input_text
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
    if st.button("🗑️ Liste löschen"):
        st.session_state.input_text_val = ""
        st.session_state.results = []
        st.session_state.queue = []
        st.session_state.completed_count = 0
        st.session_state.total_count = 0
        st.session_state.state = "idle"
        st.rerun()

# --- FORTSCHRITTSBALKEN & TIMER ---

if st.session_state.state in ["running", "paused"] or st.session_state.completed_count > 0:
    progress = (st.session_state.completed_count / st.session_state.total_count) if st.session_state.total_count > 0 else 0
    st.progress(progress)
    
    elapsed = int(time.time() - st.session_state.start_time) if st.session_state.start_time else 0
    
    if st.session_state.state == "running":
        st.markdown(f"⏱️ **Verstrichene Zeit:** {elapsed}s | ⏳ **Fortschritt:** {st.session_state.completed_count} von {st.session_state.total_count} Leads verarbeitet ({int(progress * 100)}%)")
    elif st.session_state.state == "paused":
        st.warning(f"⏸️ **Pausiert nach {elapsed}s:** {st.session_state.completed_count} von {st.session_state.total_count} Leads verarbeitet ({int(progress * 100)}%). Klicke auf '▶️ Fortsetzen', um weiterzumachen.")

# --- BATCH PROCESSOR ---

if st.session_state.state == "running" and st.session_state.queue:
    batch_size = 5
    current_batch = st.session_state.queue[:batch_size]
    st.session_state.queue = st.session_state.queue[batch_size:]
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        future_to_input = {executor.submit(scrape_company, line): line for line in current_batch}
        for future in concurrent.futures.as_completed(future_to_input):
            st.session_state.results.append(future.result())
            st.session_state.completed_count += 1
            
    if not st.session_state.queue:
        st.session_state.state = "idle"
        st.success(f"✅ Scraping vollständig beendet! {st.session_state.completed_count} Leads in {int(time.time() - st.session_state.start_time)}s verarbeitet.")
    
    st.rerun()

# --- ERGEBNIS-TABELLE & DOWNLOADS ---

if st.session_state.results:
    df = pd.DataFrame(st.session_state.results)
    df.index = range(1, len(df) + 1)
    
    st.subheader(f"📋 Ergebnisse ({len(df)} Leads)")
    st.dataframe(df, use_container_width=True)
    
    csv_data = df.to_csv(index=False, sep=';', encoding='utf-8-sig')
    
    col_dl1, col_dl2 = st.columns([1, 1])
    with col_dl1:
        st.download_button(
            label="📊 Für Google Sheets herunterladen (CSV)",
            data=csv_data,
            file_name="GYameli_Leads_GoogleSheets.csv",
            mime="text/csv"
        )
    with col_dl2:
        output_excel = io.BytesIO()
        with pd.ExcelWriter(output_excel, engine='openpyxl') as writer:
            df.to_excel(writer, index=False)
        output_excel.seek(0)
        
        st.download_button(
            label="📥 Als Excel herunterladen (.xlsx)",
            data=output_excel,
            file_name="GYameli_Leads.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
