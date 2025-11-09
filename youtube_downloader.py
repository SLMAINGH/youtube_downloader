import streamlit as st
import requests
from datetime import datetime
from typing import List, Dict
import time
import json
import zipfile
import io
import re
import google.generativeai as genai

st.set_page_config(
    page_title="YouTube Transcript Downloader & Analyzer",
    page_icon="📝",
    layout="wide"
)

# Initialize session state
if 'results' not in st.session_state:
    st.session_state.results = []
if 'transcripts' not in st.session_state:
    st.session_state.transcripts = []
if 'analysis_result' not in st.session_state:
    st.session_state.analysis_result = None

def log_result(message: str):
    """Add message to results"""
    st.session_state.results.append(message)

def clear_results():
    """Clear results"""
    st.session_state.results = []
    st.session_state.transcripts = []
    st.session_state.analysis_result = None

def extract_video_id(url: str) -> str:
    """Extract video ID from YouTube URL"""
    if "youtube.com/watch?v=" in url:
        return url.split("v=")[1].split("&")[0]
    elif "youtu.be/" in url:
        return url.split("youtu.be/")[1].split("?")[0]
    elif len(url) == 11:  # Direct video ID
        return url
    return None

def fetch_channel_videos(api_key: str, channel_id: str, video_type: str = "all", limit: int = 500) -> Dict:
    """Fetch videos from a YouTube channel"""
    url = "https://api.supadata.ai/v1/youtube/channel/videos"
    headers = {"x-api-key": api_key}
    params = {
        "id": channel_id,
        "type": video_type,
        "limit": limit
    }
    
    response = requests.get(url, headers=headers, params=params)
    
    if response.status_code == 200:
        return response.json()
    else:
        st.error(f"❌ Błąd API: {response.status_code}")
        st.error(f"Odpowiedź: {response.text}")
        return None

def fetch_video_metadata(api_key: str, video_id: str) -> Dict:
    """Fetch metadata for a single video"""
    url = "https://api.supadata.ai/v1/youtube/video"
    headers = {"x-api-key": api_key}
    params = {"id": video_id}
    
    response = requests.get(url, headers=headers, params=params)
    
    if response.status_code == 200:
        return response.json()
    else:
        return None

def check_transcript_availability(metadata: Dict, preferred_langs: List[str]) -> Dict:
    """Check if transcript is available in preferred languages based on metadata"""
    if not metadata:
        return None
    
    available_langs = metadata.get('transcriptLanguages', [])
    
    # Check if any preferred language is available
    for lang in preferred_langs:
        if lang in available_langs:
            return {
                'available': True,
                'lang': lang,
                'all_langs': available_langs,
                'title': metadata.get('title', 'N/A')
            }
    
    return {
        'available': False,
        'lang': None,
        'all_langs': available_langs,
        'title': metadata.get('title', 'N/A')
    }

def fetch_transcript(api_key: str, video_id: str, lang: str, as_text: bool = True) -> Dict:
    """Fetch transcript for a video in specified language"""
    url = "https://api.supadata.ai/v1/youtube/transcript"
    headers = {"x-api-key": api_key}
    params = {
        "videoId": video_id,
        "lang": lang,
        "text": str(as_text).lower()
    }
    
    try:
        response = requests.get(url, headers=headers, params=params)
        
        if response.status_code == 200:
            data = response.json()
            
            # Convert content to string if it's a list
            content = data.get('content', '')
            if isinstance(content, list):
                # If it's a list of segments with timestamps
                content = '\n'.join([segment.get('text', '') for segment in content])
            
            data['content'] = content
            return data
        else:
            return None
    except Exception as e:
        return None

def sanitize_filename(filename: str, max_length: int = 200) -> str:
    """Sanitize filename to be safe for all operating systems"""
    # Remove or replace invalid characters
    # Invalid chars for Windows: < > : " / \ | ? *
    # Also remove newlines and other control characters
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', filename)
    
    # Replace multiple spaces with single space
    filename = re.sub(r'\s+', ' ', filename)
    
    # Remove leading/trailing spaces and dots (problematic on Windows)
    filename = filename.strip(' .')
    
    # If filename is empty after sanitization, use a default
    if not filename:
        filename = "untitled"
    
    # Limit length (leave room for extension and video_id)
    if len(filename) > max_length:
        filename = filename[:max_length]
    
    return filename


def create_transcripts_zip(transcripts: List[Dict], format: str = 'txt') -> bytes:
    """Create a ZIP file with individual transcript files"""
    zip_buffer = io.BytesIO()
    
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for transcript in transcripts:
            video_id = transcript['video_id']
            lang = transcript['lang']
            title = transcript.get('title', 'untitled')
            
            # Sanitize title for filename
            safe_title = sanitize_filename(title)
            
            if format == 'txt':
                # TXT format
                content = transcript['transcript']
                if isinstance(content, list):
                    content = '\n'.join([str(item) for item in content])
                
                filename = f"{safe_title}_transcript_{lang}.txt"
                zip_file.writestr(filename, str(content))
                
            elif format == 'json':
                # JSON format
                json_content = json.dumps({
                    'video_id': video_id,
                    'title': transcript['title'],
                    'lang': lang,
                    'all_langs': transcript['all_langs'],
                    'transcript': transcript['transcript'],
                    'url': f"https://youtube.com/watch?v={video_id}"
                }, ensure_ascii=False, indent=2)
                
                filename = f"{safe_title}_transcript_{lang}.json"
                zip_file.writestr(filename, json_content)
    
    zip_buffer.seek(0)
    return zip_buffer.getvalue()


def filter_by_date(api_key: str, video_ids: List[str], target_date: datetime) -> List[Dict]:
    """Filter videos by upload date"""
    filtered = []
    progress_bar = st.progress(0)
    
    for idx, vid_id in enumerate(video_ids[:50]):  # Limit to avoid too many API calls
        try:
            data = fetch_video_metadata(api_key, vid_id)
            if data:
                upload_date = datetime.strptime(data["uploadDate"][:10], "%Y-%m-%d")
                if upload_date >= target_date:
                    filtered.append({
                        'id': vid_id,
                        'title': data.get('title', 'N/A'),
                        'date': data.get('uploadDate', 'N/A')[:10],
                        'views': data.get('viewCount', 0)
                    })
            progress_bar.progress((idx + 1) / min(len(video_ids), 50))
            time.sleep(0.1)  # Rate limiting
        except Exception as e:
            continue
    
    progress_bar.empty()
    return filtered


def analyze_transcripts_with_gemini(gemini_api_key: str, transcripts: List[Dict], analysis_language: str = "pl") -> Dict:
    """Analyze transcripts using Gemini AI"""
    
    # Configure Gemini
    genai.configure(api_key=gemini_api_key)
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    # Combine transcripts
    combined_text = ""
    for t in transcripts:
        combined_text += f"\n{'='*80}\n"
        combined_text += f"Video: {t['title']}\n"
        combined_text += f"ID: {t['video_id']}\n"
        combined_text += f"Język: {t['lang']}\n"
        combined_text += f"{'='*80}\n\n"
        
        transcript_content = t['transcript']
        if isinstance(transcript_content, list):
            transcript_content = '\n'.join([str(item) for item in transcript_content])
        
        combined_text += f"{transcript_content}\n\n"
    
    # Create universal prompt
    prompt = f"""Przeanalizuj poniższe transkrypty wideo i wyciągnij z nich kluczowe informacje. Twoim celem jest stworzenie strukturalnej bazy wiedzy, która będzie użyteczna dla użytkownika.

Transkrypty do analizy:
---
{combined_text}
---

Twoja odpowiedź **MUSI** być **TYLKO** w formacie JSON. Nie dołączaj żadnego tekstu przed otwarciem `{{` ani po zamknięciu `}}`.

Obiekt JSON powinien zawierać następujące klucze:

1. `overall_summary`: (String) Ogólne podsumowanie wszystkich przeanalizowanych transkryptów (3-5 zdań) w języku polskim.

2. `main_topics`: (Array of Strings) Lista głównych tematów poruszanych we wszystkich transkryptach (5-10 tematów), w języku polskim.

3. `videos_analysis`: (Array of Objects) Tablica obiektów, gdzie każdy element reprezentuje jeden video. Każdy obiekt **MUSI** zawierać:
   * `video_id`: (String) ID wideo z YouTube
   * `title`: (String) Tytuł wideo
   * `summary`: (String) Zwięzłe podsumowanie treści tego konkretnego wideo (2-3 zdania), w języku polskim
   * `key_points`: (Array of Strings) Lista najważniejszych punktów/wniosków z tego wideo (3-7 punktów), w języku polskim
   * `topics`: (Array of Strings) Główne tematy poruszane w tym wideo, w języku polskim
   * `entities`: (Object) Obiekty wspomniane w wideo, zawierający:
     - `tools`: (Array of Strings) Wymienione narzędzia/platformy/aplikacje (zachowaj oryginalne nazwy w języku angielskim)
     - `technologies`: (Array of Strings) Wymienione technologie/frameworki/języki (zachowaj oryginalne nazwy)
     - `companies`: (Array of Strings) Wymienione firmy/marki
     - `people`: (Array of Strings) Wymienione osoby (jeśli występują)
   * `use_cases`: (Array of Objects, opcjonalne) Jeśli w wideo są omawiane konkretne przypadki użycia/strategie, każdy obiekt powinien zawierać:
     - `problem`: (String) Opisany problem/wyzwanie, w języku polskim
     - `solution`: (String) Zaproponowane rozwiązanie, w języku polskim
     - `tools_used`: (Array of Strings) Narzędzia użyte w rozwiązaniu
   * `actionable_insights`: (Array of Strings) Praktyczne wnioski/porady, które widz może wdrożyć (jeśli występują), w języku polskim
   * `difficulty_level`: (String) Poziom trudności treści: "Beginner", "Intermediate", "Advanced"
   * `tags`: (Array of Strings) Tagi kategoryzujące video (np. "Tutorial", "Strategy", "Review", "Case Study", "Tips"), w języku angielskim

4. `common_patterns`: (Object) Wspólne wzorce/tematy występujące w wielu transkryptach:
   * `recurring_tools`: (Array of Strings) Narzędzia wymieniane w wielu wideo
   * `recurring_concepts`: (Array of Strings) Koncepcje/strategie pojawiające się wielokrotnie, w języku polskim
   * `trends`: (Array of Strings) Zauważone trendy/tendencje, w języku polskim

5. `metadata`: (Object) Metadane analizy:
   * `total_videos`: (Number) Liczba przeanalizowanych wideo
   * `total_words`: (Number) Przybliżona liczba słów we wszystkich transkryptach
   * `analysis_date`: (String) Data analizy w formacie ISO
   * `language`: (String) Język transkryptów

Przykładowa struktura JSON:
{{
  "overall_summary": "Transkrypty koncentrują się na...",
  "main_topics": ["Temat 1", "Temat 2", "Temat 3"],
  "videos_analysis": [
    {{
      "video_id": "abc123",
      "title": "Tytuł wideo",
      "summary": "To wideo omawia...",
      "key_points": ["Punkt 1", "Punkt 2"],
      "topics": ["Temat A", "Temat B"],
      "entities": {{
        "tools": ["Tool1", "Tool2"],
        "technologies": ["React", "Python"],
        "companies": ["Company A"],
        "people": []
      }},
      "use_cases": [
        {{
          "problem": "Jak rozwiązać problem X?",
          "solution": "Użyj narzędzia Y aby...",
          "tools_used": ["Tool Y", "Tool Z"]
        }}
      ],
      "actionable_insights": ["Insight 1", "Insight 2"],
      "difficulty_level": "Intermediate",
      "tags": ["Tutorial", "Strategy"]
    }}
  ],
  "common_patterns": {{
    "recurring_tools": ["Tool A", "Tool B"],
    "recurring_concepts": ["Koncepcja X", "Koncepcja Y"],
    "trends": ["Trend 1", "Trend 2"]
  }},
  "metadata": {{
    "total_videos": 5,
    "total_words": 15000,
    "analysis_date": "2025-11-09",
    "language": "pl/en"
  }}
}}

Upewnij się, że końcowy wynik to pojedynczy, poprawny obiekt JSON zaczynający się od `{{` i kończący się `}}`. 
Odpowiadaj w języku polskim dla pól opisowych, ale zachowaj oryginalne angielskie nazwy dla narzędzi, technologii i tagów.
Jeśli jakieś informacje nie występują w transkryptach (np. use_cases, people), użyj pustej tablicy [] lub odpowiednio oznacz ich brak.
"""
    
    try:
        # Generate response
        response = model.generate_content(prompt)
        
        # Extract JSON from response
        response_text = response.text.strip()
        
        # Remove markdown code blocks if present
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.startswith("```"):
            response_text = response_text[3:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]
        
        response_text = response_text.strip()
        
        # Parse JSON
        analysis_result = json.loads(response_text)
        
        return {
            'success': True,
            'data': analysis_result
        }
        
    except json.JSONDecodeError as e:
        return {
            'success': False,
            'error': f"Błąd parsowania JSON: {str(e)}",
            'raw_response': response.text if 'response' in locals() else None
        }
    except Exception as e:
        return {
            'success': False,
            'error': f"Błąd analizy: {str(e)}"
        }


# Main App
st.title("📝 YouTube Transcript Downloader & AI Analyzer")
st.markdown("---")

# API Key input
with st.sidebar:
    st.header("⚙️ Konfiguracja")
    api_key = st.text_input("Supadata API Key", type="password", help="Klucz API do pobierania transkryptów")
    
    st.markdown("---")
    st.markdown("### 🤖 Gemini AI (opcjonalnie)")
    gemini_api_key = st.text_input("Google Gemini API Key", type="password", help="Klucz API do analizy transkryptów przez AI")
    
    if gemini_api_key:
        st.success("✅ Gemini API skonfigurowane - możesz analizować transkrypty!")
    else:
        st.info("ℹ️ Dodaj klucz Gemini aby włączyć analizę AI")
    
    st.markdown("---")
    st.markdown("### 🌐 Języki transkryptów")
    
    use_english = st.checkbox("Angielski (en)", value=True)
    use_polish = st.checkbox("Polski (pl)", value=True)
    
    preferred_langs = []
    if use_english:
        preferred_langs.append('en')
    if use_polish:
        preferred_langs.append('pl')
    
    st.info(f"Wybrane języki: {', '.join(preferred_langs) if preferred_langs else 'Brak'}")
    
    st.markdown("---")
    st.markdown("### 📚 Instrukcja")
    st.markdown("""
    1. Wprowadź klucz API Supadata
    2. (Opcjonalnie) Dodaj klucz Gemini dla AI
    3. Wybierz języki transkryptów
    4. Wybierz tryb i pobierz filmy
    5. Pobierz transkrypty
    6. (Opcjonalnie) Analizuj przez AI
    """)
    
    st.markdown("---")


# Mode selection
st.header("📋 Wybierz tryb")
mode = st.radio(
    "Wybierz tryb działania:",
    ["Wszystkie filmiki", "Filmiki od określonej daty / X najnowszych", "Sprecyzowane linki"],
    horizontal=True
)

st.markdown("---")

# Mode 1: All videos
if mode == "Wszystkie filmiki":
    st.subheader("📺 Wszystkie filmiki z kanału")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        channel_id = st.text_input(
            "URL/ID/Handle kanału",
            placeholder="@RickAstleyVEVO lub UCuAXFkgsw1L7xaCfnd5JJOw",
            help="Możesz podać: @handle, ID kanału lub pełny URL"
        )
    
    with col2:
        video_type = st.selectbox(
            "Typ wideo",
            ["all", "video", "short", "live"],
            format_func=lambda x: {
                "all": "Wszystkie",
                "video": "Tylko video",
                "short": "Tylko Shorts",
                "live": "Tylko live"
            }[x]
        )
    
    if st.button("🔍 Pobierz listę filmików", type="primary", use_container_width=True):
        if not api_key:
            st.error("❌ Proszę wprowadzić API Key!")
        elif not channel_id:
            st.error("❌ Proszę wprowadzić ID/URL kanału!")
        else:
            with st.spinner("Pobieranie danych..."):
                clear_results()
                data = fetch_channel_videos(api_key, channel_id, video_type, 500)
                
                if data:
                    video_ids = data.get("videoIds", [])
                    short_ids = data.get("shortIds", [])
                    live_ids = data.get("liveIds", [])
                    total = len(video_ids) + len(short_ids) + len(live_ids)
                    
                    # Store in session state
                    st.session_state.video_ids = video_ids + short_ids + live_ids
                    
                    st.success(f"✅ Pobrano łącznie: {total} filmików")
                    
                    # Show statistics
                    col1, col2, col3 = st.columns(3)
                    col1.metric("🎬 Normalne video", len(video_ids))
                    col2.metric("📱 Shorts", len(short_ids))
                    col3.metric("🔴 Live", len(live_ids))
                    
                    # Show video IDs
                    if video_ids:
                        st.subheader("📹 Lista Video ID")
                        for vid_id in video_ids[:50]:
                            st.code(f"https://youtube.com/watch?v={vid_id}", language=None)
                        if len(video_ids) > 50:
                            st.info(f"... i {len(video_ids) - 50} więcej")
                    
                    # Download button for all IDs
                    all_ids = video_ids + short_ids + live_ids
                    if all_ids:
                        st.download_button(
                            "📥 Pobierz wszystkie ID jako TXT",
                            "\n".join(all_ids),
                            file_name=f"youtube_ids_{channel_id}.txt",
                            mime="text/plain"
                        )

# Mode 2: Filtered videos
elif mode == "Filmiki od określonej daty / X najnowszych":
    st.subheader("🔍 Filmiki filtrowane")
    
    channel_id = st.text_input(
        "URL/ID/Handle kanału",
        placeholder="@RickAstleyVEVO",
        key="channel_filtered"
    )
    
    col1, col2 = st.columns(2)
    
    with col1:
        filter_type = st.radio(
            "Typ filtrowania",
            ["X najnowszych", "Od daty"],
            horizontal=True
        )
    
    with col2:
        video_type = st.selectbox(
            "Typ wideo",
            ["all", "video", "short"],
            format_func=lambda x: {
                "all": "Wszystkie",
                "video": "Tylko video",
                "short": "Tylko Shorts"
            }[x],
            key="video_type_filtered"
        )
    
    if filter_type == "X najnowszych":
        limit = st.number_input("Liczba najnowszych filmików", min_value=1, max_value=5000, value=10)
        
        if st.button("🔍 Pobierz najnowsze filmiki", type="primary", use_container_width=True):
            if not api_key or not channel_id:
                st.error("❌ Proszę wypełnić wszystkie pola!")
            else:
                with st.spinner(f"Pobieranie {limit} najnowszych filmików..."):
                    data = fetch_channel_videos(api_key, channel_id, video_type, limit)
                    
                    if data:
                        video_ids = data.get("videoIds", [])
                        st.session_state.video_ids = video_ids
                        
                        st.success(f"✅ Pobrano {len(video_ids)} filmików")
                        
                        for vid_id in video_ids:
                            st.code(f"https://youtube.com/watch?v={vid_id}", language=None)
    
    else:  # Od daty
        target_date = st.date_input("Data początkowa", value=datetime(2024, 1, 1))
        
        if st.button("🔍 Pobierz filmiki od daty", type="primary", use_container_width=True):
            if not api_key or not channel_id:
                st.error("❌ Proszę wypełnić wszystkie pola!")
            else:
                with st.spinner("Pobieranie i filtrowanie filmików..."):
                    # First get all videos
                    data = fetch_channel_videos(api_key, channel_id, video_type, 500)
                    
                    if data:
                        video_ids = data.get("videoIds", [])
                        st.info(f"📊 Pobrano {len(video_ids)} video ID. Sprawdzanie dat...")
                        
                        # Filter by date
                        filtered = filter_by_date(api_key, video_ids, datetime.combine(target_date, datetime.min.time()))
                        
                        if filtered:
                            st.session_state.video_ids = [v['id'] for v in filtered]
                            
                            st.success(f"✅ Znaleziono {len(filtered)} filmików od {target_date}")
                            
                            # Display results in a table
                            for video in filtered:
                                with st.container():
                                    col1, col2, col3 = st.columns([3, 1, 1])
                                    col1.write(f"**{video['title']}**")
                                    col2.write(f"📅 {video['date']}")
                                    col3.write(f"👁️ {video['views']:,}")
                                    st.code(f"https://youtube.com/watch?v={video['id']}", language=None)
                        else:
                            st.warning("Nie znaleziono filmików spełniających kryteria")

# Mode 3: Specific links
else:
    st.subheader("🔗 Sprecyzowane linki")
    
    links = st.text_area(
        "Wklej linki do filmików (jeden na linię)",
        height=200,
        placeholder="https://www.youtube.com/watch?v=dQw4w9WgXcQ\nhttps://youtu.be/xvFZjo5PgG0\ndQw4w9WgXcQ"
    )
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("📋 Wyciągnij ID z linków", type="primary", use_container_width=True):
            if not links:
                st.error("❌ Proszę wkleić linki!")
            else:
                links_list = [l.strip() for l in links.split('\n') if l.strip()]
                video_ids = []
                
                for link in links_list:
                    vid_id = extract_video_id(link)
                    if vid_id:
                        video_ids.append(vid_id)
                
                st.session_state.video_ids = video_ids
                
                st.success(f"✅ Znaleziono {len(video_ids)} poprawnych ID:")
                for vid_id in video_ids:
                    st.code(f"https://youtube.com/watch?v={vid_id}", language=None)
                
                if video_ids:
                    st.download_button(
                        "📥 Pobierz ID jako TXT",
                        "\n".join(video_ids),
                        file_name="video_ids.txt",
                        mime="text/plain"
                    )
    
    with col2:
        if st.button("📊 Pobierz metadane", type="secondary", use_container_width=True):
            if not api_key:
                st.error("❌ Proszę wprowadzić API Key!")
            elif not links:
                st.error("❌ Proszę wkleić linki!")
            else:
                links_list = [l.strip() for l in links.split('\n') if l.strip()]
                
                with st.spinner("Pobieranie metadanych..."):
                    for link in links_list[:10]:  # Limit to 10
                        vid_id = extract_video_id(link)
                        if vid_id:
                            data = fetch_video_metadata(api_key, vid_id)
                            if data:
                                with st.expander(f"🎬 {data.get('title', 'N/A')}"):
                                    col1, col2 = st.columns(2)
                                    with col1:
                                        st.write(f"**ID:** {data.get('id', 'N/A')}")
                                        st.write(f"**Kanał:** {data.get('channel', {}).get('name', 'N/A')}")
                                        st.write(f"**Data:** {data.get('uploadDate', 'N/A')[:10]}")
                                    with col2:
                                        st.write(f"**Wyświetlenia:** {data.get('viewCount', 0):,}")
                                        st.write(f"**Polubienia:** {data.get('likeCount', 0):,}")
                                        st.write(f"**Czas trwania:** {data.get('duration', 0)}s")
                                    
                                    st.write(f"**Opis:** {data.get('description', 'N/A')[:200]}...")
                            time.sleep(0.2)  # Rate limiting

# TRANSCRIPT SECTION
st.markdown("---")
st.header("📝 Pobieranie transkryptów")

if 'video_ids' in st.session_state and st.session_state.video_ids:
    st.info(f"📊 Znaleziono {len(st.session_state.video_ids)} filmików do sprawdzenia")
    
    col1, col2 = st.columns(2)
    
    with col1:
        max_videos = st.number_input(
            "Maksymalna liczba filmików do przetworzenia",
            min_value=1,
            max_value=len(st.session_state.video_ids),
            value=min(10, len(st.session_state.video_ids))
        )
    
    with col2:
        as_text = st.checkbox("Pobierz jako czysty tekst (bez timestampów)", value=True)
    
    if st.button("🎬 Pobierz transkrypty", type="primary", use_container_width=True):
        if not api_key:
            st.error("❌ Proszę wprowadzić API Key!")
        elif not preferred_langs:
            st.error("❌ Proszę wybrać przynajmniej jeden język!")
        else:
            st.session_state.transcripts = []
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            videos_to_process = st.session_state.video_ids[:max_videos]
            
            for idx, video_id in enumerate(videos_to_process):
                status_text.text(f"Przetwarzanie {idx + 1}/{len(videos_to_process)}: {video_id}")
                
                # Fetch metadata once
                metadata = fetch_video_metadata(api_key, video_id)
                
                if not metadata:
                    st.warning(f"⚠️ Nie udało się pobrać metadanych dla {video_id}")
                    progress_bar.progress((idx + 1) / len(videos_to_process))
                    time.sleep(0.3)
                    continue
                
                # Check availability using already fetched metadata
                availability = check_transcript_availability(metadata, preferred_langs)
                
                if availability and availability['available']:
                    # Fetch transcript
                    transcript_data = fetch_transcript(api_key, video_id, availability['lang'], as_text)
                    
                    if transcript_data:
                        st.session_state.transcripts.append({
                            'video_id': video_id,
                            'title': availability['title'],
                            'lang': availability['lang'],
                            'transcript': transcript_data.get('content', ''),
                            'all_langs': availability['all_langs']
                        })
                        st.success(f"✅ {availability['title'][:50]}... [{availability['lang']}]")
                    else:
                        st.warning(f"⚠️ Nie udało się pobrać transkryptu dla {video_id}")
                else:
                    available_str = ', '.join(availability['all_langs']) if availability and availability['all_langs'] else 'brak'
                    st.warning(f"⚠️ {availability['title'][:50]}... - Brak transkryptu w wybranych językach. Dostępne: {available_str}")
                
                progress_bar.progress((idx + 1) / len(videos_to_process))
                time.sleep(0.3)  # Rate limiting
            
            progress_bar.empty()
            status_text.empty()
            
            st.success(f"🎉 Pobrano {len(st.session_state.transcripts)} transkryptów!")

# AI ANALYSIS SECTION
if st.session_state.transcripts and gemini_api_key:
    st.markdown("---")
    st.header("🤖 Analiza AI (Gemini)")
    
    st.info(f"📊 Masz {len(st.session_state.transcripts)} transkryptów gotowych do analizy")
    
    # Select transcripts to analyze
    st.subheader("Wybierz transkrypty do analizy")
    
    analyze_all = st.checkbox("Analizuj wszystkie transkrypty", value=True)
    
    selected_indices = []
    if not analyze_all:
        st.write("Wybierz konkretne transkrypty:")
        for idx, t in enumerate(st.session_state.transcripts):
            if st.checkbox(f"{t['title'][:60]}... [{t['lang']}]", key=f"select_{idx}"):
                selected_indices.append(idx)
    else:
        selected_indices = list(range(len(st.session_state.transcripts)))
    
    if selected_indices:
        st.info(f"Wybrano {len(selected_indices)} transkrypt(ów) do analizy")
        
        if st.button("🚀 Analizuj przez Gemini AI", type="primary", use_container_width=True):
            selected_transcripts = [st.session_state.transcripts[i] for i in selected_indices]
            
            with st.spinner(f"Analizowanie {len(selected_transcripts)} transkryptów przez Gemini AI... To może potrwać kilka minut."):
                result = analyze_transcripts_with_gemini(gemini_api_key, selected_transcripts)
                
                if result['success']:
                    st.session_state.analysis_result = result['data']
                    st.success("✅ Analiza zakończona pomyślnie!")
                else:
                    st.error(f"❌ {result['error']}")
                    if result.get('raw_response'):
                        with st.expander("🔍 Zobacz surową odpowiedź"):
                            st.text(result['raw_response'])
    else:
        st.warning("⚠️ Nie wybrano żadnych transkryptów do analizy")

# Display AI Analysis Results
if st.session_state.analysis_result:
    st.markdown("---")
    st.header("📊 Wyniki analizy AI")
    
    analysis = st.session_state.analysis_result
    
    # Overall Summary
    st.subheader("📝 Ogólne podsumowanie")
    st.write(analysis.get('overall_summary', 'Brak podsumowania'))
    
    # Main Topics
    st.subheader("🎯 Główne tematy")
    topics = analysis.get('main_topics', [])
    if topics:
        cols = st.columns(min(3, len(topics)))
        for idx, topic in enumerate(topics):
            with cols[idx % 3]:
                st.info(f"🔹 {topic}")
    
    # Videos Analysis
    st.subheader("🎬 Analiza poszczególnych wideo")
    for video_analysis in analysis.get('videos_analysis', []):
        with st.expander(f"📹 {video_analysis.get('title', 'Brak tytułu')}"):
            col1, col2 = st.columns([2, 1])
            
            with col1:
                st.write(f"**Video ID:** `{video_analysis.get('video_id', 'N/A')}`")
                st.write(f"**Link:** https://youtube.com/watch?v={video_analysis.get('video_id', '')}")
                st.write(f"**Poziom trudności:** {video_analysis.get('difficulty_level', 'N/A')}")
            
            with col2:
                tags = video_analysis.get('tags', [])
                if tags:
                    st.write("**Tagi:**")
                    for tag in tags:
                        st.markdown(f"`{tag}`")
            
            st.markdown("---")
            st.write("**Podsumowanie:**")
            st.write(video_analysis.get('summary', 'Brak podsumowania'))
            
            # Key Points
            key_points = video_analysis.get('key_points', [])
            if key_points:
                st.write("**Kluczowe punkty:**")
                for point in key_points:
                    st.markdown(f"• {point}")
            
            # Topics
            video_topics = video_analysis.get('topics', [])
            if video_topics:
                st.write("**Tematy:**")
                st.write(", ".join(video_topics))
            
            # Entities
            entities = video_analysis.get('entities', {})
            if entities:
                st.write("**Wymienione elementy:**")
                
                entity_col1, entity_col2 = st.columns(2)
                
                with entity_col1:
                    if entities.get('tools'):
                        st.write("🔧 **Narzędzia:**")
                        for tool in entities['tools']:
                            st.markdown(f"• `{tool}`")
                    
                    if entities.get('technologies'):
                        st.write("💻 **Technologie:**")
                        for tech in entities['technologies']:
                            st.markdown(f"• `{tech}`")
                
                with entity_col2:
                    if entities.get('companies'):
                        st.write("🏢 **Firmy:**")
                        for company in entities['companies']:
                            st.markdown(f"• {company}")
                    
                    if entities.get('people'):
                        st.write("👤 **Osoby:**")
                        for person in entities['people']:
                            st.markdown(f"• {person}")
            
            # Use Cases
            use_cases = video_analysis.get('use_cases', [])
            if use_cases:
                st.write("**💡 Przypadki użycia:**")
                for idx, uc in enumerate(use_cases, 1):
                    st.markdown(f"**{idx}. Problem:** {uc.get('problem', 'N/A')}")
                    st.markdown(f"   **Rozwiązanie:** {uc.get('solution', 'N/A')}")
                    if uc.get('tools_used'):
                        st.markdown(f"   **Użyte narzędzia:** {', '.join(uc['tools_used'])}")
                    st.markdown("")
            
            # Actionable Insights
            insights = video_analysis.get('actionable_insights', [])
            if insights:
                st.write("**✨ Praktyczne wnioski:**")
                for insight in insights:
                    st.markdown(f"✅ {insight}")
    
    # Common Patterns
    st.subheader("🔄 Wspólne wzorce")
    patterns = analysis.get('common_patterns', {})
    
    pattern_col1, pattern_col2, pattern_col3 = st.columns(3)
    
    with pattern_col1:
        recurring_tools = patterns.get('recurring_tools', [])
        if recurring_tools:
            st.write("**🔧 Powtarzające się narzędzia:**")
            for tool in recurring_tools:
                st.markdown(f"• `{tool}`")
    
    with pattern_col2:
        recurring_concepts = patterns.get('recurring_concepts', [])
        if recurring_concepts:
            st.write("**💡 Powtarzające się koncepcje:**")
            for concept in recurring_concepts:
                st.markdown(f"• {concept}")
    
    with pattern_col3:
        trends = patterns.get('trends', [])
        if trends:
            st.write("**📈 Trendy:**")
            for trend in trends:
                st.markdown(f"• {trend}")
    
    # Metadata
    st.subheader("ℹ️ Metadane analizy")
    metadata = analysis.get('metadata', {})
    
    meta_col1, meta_col2, meta_col3, meta_col4 = st.columns(4)
    
    with meta_col1:
        st.metric("📹 Liczba wideo", metadata.get('total_videos', 0))
    with meta_col2:
        st.metric("📝 Liczba słów", f"{metadata.get('total_words', 0):,}")
    with meta_col3:
        st.metric("📅 Data analizy", metadata.get('analysis_date', 'N/A'))
    with meta_col4:
        st.metric("🌐 Język", metadata.get('language', 'N/A'))
    
    # Download Analysis Results
    st.markdown("---")
    st.subheader("📥 Pobierz wyniki analizy")
    
    analysis_json = json.dumps(analysis, ensure_ascii=False, indent=2)
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.download_button(
            "📥 Pobierz analizę (JSON)",
            analysis_json,
            file_name=f"ai_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            mime="application/json",
            use_container_width=True
        )
    
    with col2:
        # Create a formatted text version
        text_report = f"""RAPORT ANALIZY AI - YouTube Transcripts
Data: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
{'='*80}

OGÓLNE PODSUMOWANIE
{analysis.get('overall_summary', 'Brak')}

GŁÓWNE TEMATY
{chr(10).join([f"• {topic}" for topic in analysis.get('main_topics', [])])}

{'='*80}

ANALIZA WIDEO
"""
        for video in analysis.get('videos_analysis', []):
            text_report += f"""
{'='*80}
TYTUŁ: {video.get('title', 'N/A')}
VIDEO ID: {video.get('video_id', 'N/A')}
POZIOM: {video.get('difficulty_level', 'N/A')}
TAGI: {', '.join(video.get('tags', []))}

PODSUMOWANIE:
{video.get('summary', 'Brak')}

KLUCZOWE PUNKTY:
{chr(10).join([f"• {point}" for point in video.get('key_points', [])])}

"""
            if video.get('use_cases'):
                text_report += "PRZYPADKI UŻYCIA:\n"
                for idx, uc in enumerate(video['use_cases'], 1):
                    text_report += f"{idx}. Problem: {uc.get('problem', 'N/A')}\n"
                    text_report += f"   Rozwiązanie: {uc.get('solution', 'N/A')}\n"
                text_report += "\n"
        
        text_report += f"""
{'='*80}

WSPÓLNE WZORCE

Powtarzające się narzędzia:
{chr(10).join([f"• {tool}" for tool in patterns.get('recurring_tools', [])])}

Powtarzające się koncepcje:
{chr(10).join([f"• {concept}" for concept in patterns.get('recurring_concepts', [])])}

Trendy:
{chr(10).join([f"• {trend}" for trend in patterns.get('trends', [])])}

{'='*80}
Koniec raportu
"""
        
        st.download_button(
            "📥 Pobierz raport (TXT)",
            text_report,
            file_name=f"ai_analysis_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
            mime="text/plain",
            use_container_width=True
        )

# Display transcripts (original section)
if st.session_state.transcripts:
    st.markdown("---")
    st.header("📄 Pobrane transkrypty")
    
    # Download all transcripts
    st.subheader("📦 Pobierz wszystkie transkrypty")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        # As JSON (all in one file)
        json_data = json.dumps(st.session_state.transcripts, ensure_ascii=False, indent=2)
        st.download_button(
            "📥 Jeden JSON",
            json_data,
            file_name="transcripts_all.json",
            mime="application/json",
            use_container_width=True,
            help="Wszystkie transkrypty w jednym pliku JSON"
        )
    
    with col2:
        # As TXT (all in one file)
        txt_data = ""
        for t in st.session_state.transcripts:
            txt_data += f"{'='*80}\n"
            txt_data += f"Video ID: {t['video_id']}\n"
            txt_data += f"Tytuł: {t['title']}\n"
            txt_data += f"Język: {t['lang']}\n"
            txt_data += f"{'='*80}\n\n"
            
            # Convert to string if it's a list
            transcript_content = t['transcript']
            if isinstance(transcript_content, list):
                transcript_content = '\n'.join([str(item) for item in transcript_content])
            
            txt_data += f"{transcript_content}\n\n\n"
        
        st.download_button(
            "📥 Jeden TXT",
            txt_data,
            file_name="transcripts_all.txt",
            mime="text/plain",
            use_container_width=True,
            help="Wszystkie transkrypty w jednym pliku TXT"
        )
    
    with col3:
        # As ZIP with individual TXT files
        zip_txt = create_transcripts_zip(st.session_state.transcripts, format='txt')
        st.download_button(
            "📥 ZIP (TXT)",
            zip_txt,
            file_name="transcripts_txt.zip",
            mime="application/zip",
            use_container_width=True,
            help="Każdy transkrypt jako osobny plik TXT w archiwum ZIP"
        )
    
    with col4:
        # As ZIP with individual JSON files
        zip_json = create_transcripts_zip(st.session_state.transcripts, format='json')
        st.download_button(
            "📥 ZIP (JSON)",
            zip_json,
            file_name="transcripts_json.zip",
            mime="application/zip",
            use_container_width=True,
            help="Każdy transkrypt jako osobny plik JSON w archiwum ZIP"
        )
    
    # Display individual transcripts
    st.markdown("### 📋 Podgląd transkryptów")
    
    for transcript in st.session_state.transcripts:
        with st.expander(f"🎬 {transcript['title']} [{transcript['lang']}]"):
            st.write(f"**Video ID:** {transcript['video_id']}")
            st.write(f"**Język:** {transcript['lang']}")
            st.write(f"**Dostępne języki:** {', '.join(transcript['all_langs'])}")
            st.write(f"**Link:** https://youtube.com/watch?v={transcript['video_id']}")
            
            st.markdown("**Transkrypt:**")
            
            # Convert to string if it's a list
            display_transcript = transcript['transcript']
            if isinstance(display_transcript, list):
                display_transcript = '\n'.join([str(item) for item in display_transcript])
            
            st.text_area(
                "Transkrypt",
                display_transcript,
                height=300,
                key=f"transcript_{transcript['video_id']}",
                label_visibility="collapsed"
            )
            
            # Download buttons in columns
            col1, col2 = st.columns(2)
            
            # Sanitize title for filename
            safe_title = sanitize_filename(transcript['title'])
            
            with col1:
                # Individual download as TXT
                transcript_text = transcript['transcript']
                if isinstance(transcript_text, list):
                    transcript_text = '\n'.join([str(item) for item in transcript_text])
                
                st.download_button(
                    "📥 Pobierz jako TXT",
                    str(transcript_text),
                    file_name=f"{safe_title}_transcript_{transcript['lang']}.txt",
                    mime="text/plain",
                    key=f"download_txt_{transcript['video_id']}",
                    use_container_width=True
                )
            
            with col2:
                # Individual download as JSON
                individual_json = json.dumps({
                    'video_id': transcript['video_id'],
                    'title': transcript['title'],
                    'lang': transcript['lang'],
                    'all_langs': transcript['all_langs'],
                    'transcript': transcript['transcript'],
                    'url': f"https://youtube.com/watch?v={transcript['video_id']}"
                }, ensure_ascii=False, indent=2)
                
                st.download_button(
                    "📥 Pobierz jako JSON",
                    individual_json,
                    file_name=f"{safe_title}_transcript_{transcript['lang']}.json",
                    mime="application/json",
                    key=f"download_json_{transcript['video_id']}",
                    use_container_width=True
                )

else:
    st.info("👆 Najpierw pobierz listę filmików, a następnie kliknij 'Pobierz transkrypty'")
