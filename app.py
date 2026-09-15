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

# --- 1. EXTRAKTIONS- & SCRAPER-LOGIK ---

def decode_cloudflare_email(cf_hex):
    try:
        key = int(cf_hex[:2], 16)
        return "".join([chr(int(cf_hex[i:i+2], 16) ^ key) for i in range(2, len(cf_hex), 2)])
    except:
        return ""

def extract_all_emails_advanced(html_content, soup):
    if not html_content: return []
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

        for img in soup.find_all(['img', 'div', 'span']):
            for attr in ['alt', 'title', 'data-email', 'data-mail', 'data-contact']:
                if img.has_attr(attr):
                    found_raw.append(img[attr])

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
        if '@' in el and '.' in el.split('@')[-1]:
            clean_emails.append(el)
            
    return list(set(clean_emails))

def extract_phone_advanced(soup, text):
    if soup:
        for a in soup.find_all('a', href=True):
            href = a['href'].lower()
            if 'tel:' in href:
                raw_tel = href.split('tel:')[-1].strip()
                clean_tel = re.sub(r'[^\d\+]', ' ', raw_tel)
                clean_tel = ' '.join(clean_tel.split())
                if len(re.sub(r'\D', '', clean_tel)) >= 6:
                    return clean_tel

    if text:
        patterns = [
            r'(?:Tel(?:efon)?|Fon|Mobil|Mobile|Phone|Call)\s*[:\.]?\s*(\+?[0-9\s\/\-\(\)]{8,25})',
            r'(\+49\s*[0-9\s\/\-\(\)]{8,20})',
            r'(0[1-9][0-9]{1,4}\s*[\/\-]?\s*[0-9\s\-]{5,15})'
        ]
        for p in patterns:
            match = re.search(p, text, re.IGNORECASE)
            if match:
                phone = match.group(1).strip()
                digits_only = re.sub(r'\D', '', phone)
                if len(digits_only) >= 6 and len(digits_only) <= 15:
                    return phone
    return "-"

def extract_owner_advanced(soup, raw_html):
    if not raw_html: return "-"
    
    clean_text = raw_html
    if soup:
        for tag in soup.find_all(["br", "p", "div", "tr", "li"]):
            tag.append("\n")
        clean_text = soup.get_text(separator=' ')

    # Erweitertes Keyword-Set für Entscheidungsfinder, Inhaber & Stakeholder
    patterns = [
        r'(?:Vertreten durch|Geschäftsführer(?:in)?|Geschäftsführung|Inhaber(?:in)?|Inh\.|GF|CEO|COO|CFO|CTO|'
        r'Vorstand|Prokurist(?:in)?|Gründer(?:in)?|Founder|Partner(?:in)?|Managing Director|Director|'
        r'Ansprechpartner(?:in)?|Point of Contact|Contact Person|Stakeholder|Gesellschafter(?:in)?|President|Owner|'
        r'Verantwortlich(?:er|e)?|Leitung|Vertretungsberechtigt(?:e|er)?)\s*[:|-]?\s*'
        r'([A-ZÄÖÜ][a-zäöüß\-]+(?:\s+[A-ZÄÖÜ][a-zäöüß\-]+){1,3})',
        
        r'(?:Angaben gemäß § 5 TMG|Impressum)\s*[\r\n]+(?:[A-Za-z0-9\s\.\-]+\n)?'
        r'([A-ZÄÖÜ][a-zäöüß\-]+(?:\s+[A-ZÄÖÜ][a-zäöüß\-]+){1,3})'
    ]
    
    for p in patterns:
        match = re.search(p, clean_text, re.IGNORECASE)
        if match:
            candidate = match.group(1).strip()
            bad_words = [
                'gmbh', 'ag', 'ltd', 'straße', 'strasse', 'telefon', 'email', 
                'impressum', 'kontakt', 'germany', 'deutschland', 'tel', 'fax', 
                'registergericht', 'hrb', 'ust', 'vat'
            ]
            if not any(bw in candidate.lower() for bw in bad_words):
                return candidate
    return "-"

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
            "Inhaber / GF / Contact": "-",
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
    
    base_url = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    pages_to_check = [url, base_url]
    company_name = original_input
    all_emails = []
    html_texts = []
    soups = []
    
    try:
        res = requests.get(url, headers=headers, timeout=5, allow_redirects=True)
        current_url = res.url
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            soups.append(soup)
            html_texts.append(res.text)
            all_emails.extend(extract_all_emails_advanced(res.text, soup))
            
            if title_tag := soup.find('title'):
                title_text = title_tag.text.split('|')[0].split('-')[0].strip()
                if title_text and "." in original_input:
                    company_name = title_text

            keywords = ['impressum', 'kontakt', 'contact', 'about', 'legal', 'imprint', 'team', 'ansprechpartner']
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
                all_emails.extend(extract_all_emails_advanced(r.text, soup_page))
        except: continue
            
    final_emails = list(set(all_emails))
    combined_html = "\n".join(html_texts)
    main_soup = soups[0] if soups else None
    
    owner = extract_owner_advanced(main_soup, combined_html)
    phone = extract_phone_advanced(main_soup, combined_html)
    
    return {
        "Eingabe": original_input,
        "Unternehmensname": company_name,
        "Inhaber / GF / Contact": owner,
        "Telefonnummer": phone,
        "E-Mail-Adresse": ", ".join(final_emails) if final_emails else "-",
        "Webseite": base_url,
        "Status": "✅ Erfolg" if final_emails or phone != "-" or owner != "-" else "⚠️ Teilweise"
    }

# --- 2. USER INTERFACE ---

st.set_page_config(page_title="GYameli's Pro Scraper", page_icon="🚀", layout="wide")

st.title("🚀 GYameli's Pro Scraper")
st.markdown("Füge deine Unternehmensnamen oder URLs ein (z. B. direkt aus **Spalte A einer Excel-Tabelle**).")

if "running" not in st.session_state:
    st.session_state.running = False
if "results" not in st.session_state:
    st.session_state.results = []

input_text = st.text_area(
    "Leads eingeben (1 pro Zeile, bis zu 300 Einträge)", 
    height=200, 
    placeholder="Müller Bau GmbH\nwww.zalando.de\nHotel Adlon Berlin\nhaecken.com"
)

col1, col2 = st.columns([1, 4])
with col1:
    start_btn = st.button("🚀 Scraping starten", type="primary")
with col2:
    stop_btn = st.button("⏹️ Scraping abbrechen & Teilergebnisse anzeigen")

if stop_btn:
    st.session_state.running = False
    st.warning("⚠️ Scraping wurde abgebrochen. Die bisherigen Ergebnisse stehen unten bereit.")

if start_btn:
    lines = [line.strip() for line in input_text.split('\n') if line.strip()]
    if not lines:
        st.warning("⚠️ Bitte füge mindestens eine URL oder einen Firmennamen ein.")
    else:
        st.session_state.running = True
        st.session_state.results = []
        
        start_time = time.time()
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
            future_to_input = {executor.submit(scrape_company, line): line for line in lines}
            completed = 0
            
            for future in concurrent.futures.as_completed(future_to_input):
                if not st.session_state.running:
                    break
                
                st.session_state.results.append(future.result())
                completed += 1
                
                elapsed_seconds = int(time.time() - start_time)
                progress = completed / len(lines)
                progress_bar.progress(progress)
                status_text.markdown(f"⏱️ **Verstrichene Zeit:** {elapsed_seconds}s | **Fortschritt:** {completed} von {len(lines)} Leads verarbeitet ({int(progress * 100)}%)")

        total_time = round(time.time() - start_time, 1)
        if st.session_state.running:
            status_text.markdown(f"✅ **Scraping beendet!** {len(st.session_state.results)} Leads in **{total_time} Sekunden** verarbeitet.")
        st.session_state.running = False

if st.session_state.results:
    df = pd.DataFrame(st.session_state.results)
    
    # 1-basierte Nummerierung
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
