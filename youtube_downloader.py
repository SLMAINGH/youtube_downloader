import streamlit as st
import requests
from datetime import datetime
from typing import List, Dict
import time
import json
import zipfile
import io
import re

st.set_page_config(
    page_title="YouTube Transcript Downloader",
    page_icon="📝",
    layout="wide"
)

# Initialize session state
if 'results' not in st.session_state:
    st.session_state.results = []
if 'transcripts' not in st.session_state:
    st.session_state.transcripts = []

def log_result(message: str):
    """Add message to results"""
    st.session_state.results.append(message)

def clear_results():
    """Clear results"""
    st.session_state.results = []
    st.session_state.transcripts = []

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

# Main App
st.title("📝 YouTube Transcript Downloader")
st.markdown("---")

# API Key input
with st.sidebar:
    st.header("⚙️ Konfiguracja")
    api_key = st.text_input("Supadata API Key", type="password", help="lol xd")
    
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
    1. Wprowadź klucz API
    2. Wybierz języki transkryptów
    3. Wybierz tryb i pobierz filmy
    4. Kliknij "Pobierz transkrypty"
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

# Display transcripts
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

# Footer
st.markdown("---")
