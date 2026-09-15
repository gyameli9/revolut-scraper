import streamlit as st
import requests
from bs4 import BeautifulSoup
import re
import pandas as pd
import concurrent.futures
from urllib.parse import urljoin, urlparse
from duckduckgo_search import DDGS
import io

# --- 1. EXTRAKTIONS- & SCRAPER-LOGIK ---

def find_website_from_name(query):
    query = query.strip()
    if "." in query and " " not in query:
        if not query.startswith('http'): return "https://" + query
        return query
    try:
        results = DDGS().text(query + " website OR impressum", max_results=2)
        for res in results:
            href = res['href'].lower()
            if not any(bad in href for bad in ['linkedin.com', 'xing.com', 'wikipedia.org', 'northdata', 'gelbeseiten', 'kununu']):
                return res['href']
    except: pass
    return None

def extract_emails(text):
    if not text: return []
    text = re.sub(r'(?i)\s*[\(\[]\s*at\s*[\)\]]\s*', '@', text)
    text = re.sub(r'(?i)\s*[\(\[]\s*punkt\s*[\)\]]\s*', '.', text)
    text = re.sub(r'(?i)\s*\[dot\]\s*', '.', text)
    text = text.replace('&#64;', '@').replace('&#x40;', '@')
    text = re.sub(r'(?i)([a-zA-Z0-9._%+-]+)\s+at\s+([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', r'\1@\2', text)
    
    emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
    clean = []
    for e in emails:
        el = e.lower()
        if any(el.endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp']): continue
        if any(bad in el for bad in ['example.com', 'wixpress', 'sentry.io', 'schema.org']): continue
        clean.append(el)
    return list(set(clean))

def extract_phone(text):
    if not text: return "-"
    # Matcht gängige deutsche/internationale Telefonnummern nach Keywords
    phone_match = re.search(r'(?:Tel(?:efon)?|Fon|Mobil|Mobile)?\s*[:\.]?\s*(\+?[0-9\s\/\-\(\)]{8,25})', text, re.IGNORECASE)
    if phone_match:
        phone = phone_match.group(1).strip()
        if len(re.sub(r'\D', '', phone)) >= 6:
            return phone
    return "-"

def extract_owner(text):
    if not text: return "-"
    # Muster für Inhaber / Geschäftsführer in deutschen Impressen
    patterns = [
        r'(?:Vertreten durch|Inhaber|Geschäftsführer|Geschäftsführung|Inh\.|GF)\s*:\s*([A-ZÄÖÜ][a-zäöüß]+(?:\s+[A-ZÄÖÜ][a-zäöüß]+){1,3})',
        r'(?:Angaben gemäß § 5 TMG|Impressum)\s*[\r\n]+([A-ZÄÖÜ][a-zäöüß]+(?:\s+[A-ZÄÖÜ][a-zäöüß]+){1,3})'
    ]
    for p in patterns:
        match = re.search(p, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return "-"

def scrape_company(original_input):
    url = find_website_from_name(original_input)
    if not url:
        return {
            "Eingabe": original_input,
            "Unternehmensname": original_input,
            "Inhaber / GF": "-",
            "Telefonnummer": "-",
            "E-Mail-Adresse": "-",
            "Webseite": "-",
            "Status": "❌ Keine Webseite"
        }

    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    base_url = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    pages_to_check = [url, base_url]
    
    html_sources = []
    company_name = original_input
    
    try:
        res = requests.get(url, headers=headers, timeout=8, allow_redirects=True)
        current_url = res.url
        if res.status_code == 200:
            html_sources.append(res.text)
            soup = BeautifulSoup(res.text, 'html.parser')
            
            # Falls nur eine URL eingegeben wurde, Unternehmensname aus Title ziehen
            if title_tag := soup.find('title'):
                title_text = title_tag.text.split('|')[0].split('-')[0].strip()
                if title_text and "." in original_input:
                    company_name = title_text

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
    
    all_emails = []
    combined_text = ""
    
    for page in pages_to_check:
        try:
            r = requests.get(page, headers=headers, timeout=8)
            if r.status_code == 200:
                all_emails.extend(extract_emails(r.text))
                soup_page = BeautifulSoup(r.text, 'html.parser')
                combined_text += "\n" + soup_page.get_text(separator=' ')
        except: continue
            
    final_emails = list(set(all_emails))
    owner = extract_owner(combined_text)
    phone = extract_phone(combined_text)
    
    return {
        "Eingabe": original_input,
        "Unternehmensname": company_name,
        "Inhaber / GF": owner,
        "Telefonnummer": phone,
        "E-Mail-Adresse": ", ".join(final_emails) if final_emails else "-",
        "Webseite": base_url,
        "Status": "✅ Erfolg" if final_emails or phone != "-" else "⚠️ Teilweise"
    }

# --- 2. USER INTERFACE (STREAMLIT) ---

st.set_page_config(page_title="Revolut B2B Scraper", page_icon="🏢", layout="wide")

st.title("🏢 Revolut Lead-Scraper Pro")
st.markdown("Füge deine Unternehmensnamen oder URLs ein (z. B. kopiert aus **Spalte A einer Excel-Tabelle**).")

# Excel-freundliches Eingabefeld
input_text = st.text_area(
    "Leads eingeben (1 pro Zeile, bis zu 300 Einträge)", 
    height=200, 
    placeholder="Müller Bau GmbH\nwww.zalando.de\nHotel Adlon Berlin\nhaecken.com"
)

if st.button("🚀 Scraping starten", type="primary"):
    lines = [line.strip() for line in input_text.split('\n') if line.strip()]
    if not lines:
        st.warning("⚠️ Bitte füge mindestens eine URL oder einen Firmennamen ein.")
    else:
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        results = []
        # Parallele Verarbeitung für bis zu 300 Einträge
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
            future_to_input = {executor.submit(scrape_company, line): line for line in lines}
            completed = 0
            for future in concurrent.futures.as_completed(future_to_input):
                results.append(future.result())
                completed += 1
                progress_bar.progress(completed / len(lines))
                status_text.text(f"Scrape Lead {completed} von {len(lines)}...")

        status_text.text("✅ Scraping beendet!")
        df = pd.DataFrame(results)
        
        # Vorschau-Tabelle (Interaktiv: erlaubt direktes Markieren & Copy-Paste)
        st.subheader("📋 Ergebnisse (Direkt kopierbar)")
        st.dataframe(df, use_container_width=True)
        
        # Manueller Excel-Download Button
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False)
        output.seek(0)
        
        st.download_button(
            label="📥 Liste als Excel-Datei herunterladen",
            data=output,
            file_name="Revolut_Leads_Extrahiert.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
