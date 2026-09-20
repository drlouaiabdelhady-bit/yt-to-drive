import streamlit as st
import subprocess
import glob
import os
import shutil
import urllib.request
import zipfile
import time
import random
import re
from io import BytesIO
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

st.set_page_config(page_title="YouTube MKV Archiver & Drive", layout="centered")

st.title("أرشفة يوتيوب إلى Matroska (MKV) والرفع السحابي المنظم")
st.caption("بروفايل أرشفة متكامل: أعلى دقة | فصول | ترجمات | غلاف | استئناف قياسي بملف video_archive.txt")

# ---------------------------------------------------------------
# إعدادات عامة محسّنة ومستقرة
# ---------------------------------------------------------------
OUTPUT_DIR = "downloads"
ARCHIVE_FILENAME = "video_archive.txt"

# حصر المشغلات على web_embedded مع تجربة الكوكيز وبدونها كاحتياط
CLIENT_ATTEMPTS = [
    {"profile": "youtube:player_client=android_vr", "use_cookies": False},
    {"profile": "youtube:player_client=android_vr", "use_cookies": True},
]

MAX_ATTEMPTS = len(CLIENT_ATTEMPTS)
MAX_CONSECUTIVE_FAILS = 2   # توقف كامل بعد فشل مقطعين متتاليين لحماية الـ IP

# 1. تجهيز محرك Deno السحابي تلقائياً لحل تحديات التشفير (n-challenge)
@st.cache_resource
def prepare_js_engine():
    deno_bin = os.path.join(os.getcwd(), "deno")
    if not shutil.which("deno") and not os.path.exists(deno_bin):
        try:
            url = "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-unknown-linux-gnu.zip"
            zip_path = os.path.join(os.getcwd(), "deno.zip")
            urllib.request.urlretrieve(url, zip_path)
            with zipfile.ZipFile(zip_path, "r") as z:
                z.extractall(os.getcwd())
            if os.path.exists(zip_path):
                os.remove(zip_path)
            os.chmod(deno_bin, 0o755)
        except Exception:
            pass

    if os.path.exists(deno_bin):
        if os.getcwd() not in os.environ.get("PATH", ""):
            os.environ["PATH"] = f"{os.getcwd()}:{os.environ.get('PATH', '')}"

prepare_js_engine()

# 2. حقن الكوكيز تلقائياً من Streamlit Secrets
cookie_path = os.path.join(os.getcwd(), "session_cookies.txt")
if "YOUTUBE_COOKIES" in st.secrets and st.secrets["YOUTUBE_COOKIES"].strip():
    with open(cookie_path, "w", encoding="utf-8") as f:
        f.write(st.secrets["YOUTUBE_COOKIES"].strip())

# 3. دوال Google Drive الرسمية (v3) عبر OAuth 2.0 الشخصي
def get_gdrive_service():
    client_id = st.secrets["GDRIVE_CLIENT_ID"]
    client_secret = st.secrets["GDRIVE_CLIENT_SECRET"]
    refresh_token = st.secrets["GDRIVE_REFRESH_TOKEN"]

    creds = Credentials(
        None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=["https://www.googleapis.com/auth/drive"]
    )
    return build('drive', 'v3', credentials=creds)

def get_or_create_folder(drive_service, folder_name, parent_id):
    safe_name = folder_name.replace("'", "\\'")
    query = f"name = '{safe_name}' and '{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"

    response = drive_service.files().list(
        q=query,
        spaces='drive',
        fields='files(id, name)',
        supportsAllDrives=True,
        includeItemsFromAllDrives=True
    ).execute()

    files = response.get('files', [])
    if files:
        return files[0]['id']
    else:
        folder_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [parent_id]
        }
        folder = drive_service.files().create(
            body=folder_metadata,
            fields='id',
            supportsAllDrives=True
        ).execute()
        return folder.get('id')

# 4. منظومة إدارة ملف الأرشفة القياسي (video_archive.txt)
def load_archive_from_gdrive(drive_service, root_folder_id):
    query = f"name = '{ARCHIVE_FILENAME}' and '{root_folder_id}' in parents and trashed = false"
    res = drive_service.files().list(
        q=query,
        spaces='drive',
        fields='files(id, name, modifiedTime)',
        orderBy='modifiedTime desc',
        supportsAllDrives=True,
        includeItemsFromAllDrives=True
    ).execute()
    files = res.get('files', [])

    archived_ids = set()
    drive_archive_id = None

    if files:
        drive_archive_id = files[0]['id']
        request = drive_service.files().get_media(fileId=drive_archive_id)
        fh = BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        fh.seek(0)
        content = fh.read().decode('utf-8-sig', errors='ignore')
        with open(ARCHIVE_FILENAME, "w", encoding="utf-8") as f:
            f.write(content)
        for line in content.splitlines():
            clean_line = line.strip().lstrip('\ufeff')
            match = re.search(r'youtube\s+([a-zA-Z0-9_-]{11})', clean_line)
            if match:
                archived_ids.add(match.group(1))
            elif len(clean_line) == 11:
                archived_ids.add(clean_line)
    else:
        with open(ARCHIVE_FILENAME, "w", encoding="utf-8") as f:
            f.write("")

    return archived_ids, drive_archive_id

def append_and_sync_archive(vid_id, drive_service, root_folder_id, drive_archive_id):
    with open(ARCHIVE_FILENAME, "a", encoding="utf-8") as f:
        f.write(f"youtube {vid_id}\n")

    media = MediaFileUpload(ARCHIVE_FILENAME, mimetype='text/plain', resumable=False)
    if drive_archive_id:
        drive_service.files().update(
            fileId=drive_archive_id,
            media_body=media,
            supportsAllDrives=True
        ).execute()
        return drive_archive_id
    else:
        file_metadata = {
            'name': ARCHIVE_FILENAME,
            'parents': [root_folder_id]
        }
        res = drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id',
            supportsAllDrives=True
        ).execute()
        return res.get('id')

def upload_to_organized_gdrive(drive_service, file_path, playlist_folder_id):
    try:
        file_name = os.path.basename(file_path)
        st.info(f"جاري رفع `{file_name}` بحسابك الشخصي إلى Google Drive...")

        file_metadata = {
            'name': file_name,
            'parents': [playlist_folder_id]
        }

        media = MediaFileUpload(
            file_path,
            mimetype='video/x-matroska',
            resumable=True,
            chunksize=10 * 1024 * 1024
        )

        drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id',
            supportsAllDrives=True
        ).execute()

        return True
    except Exception as e:
        st.error(f"حدث خطأ أثناء الرفع إلى Google Drive: {e}")
        return False

# 5. دوال التحميل والتنظيف
def build_cmd(target_url, client_profile, use_cookies=True):
    cmd = [
        "yt-dlp", "--force-ipv4",
        "--remote-components", "ejs:github",
        "--extractor-args", client_profile,
        "--no-playlist",
        "-f", "bv*+ba[language^=ar]/bv*+ba/b",
        "--merge-output-format", "mkv",
        "--embed-metadata", "--embed-chapters", "--embed-thumbnail",
        "--embed-subs", "--sub-langs", "ar,en", "--sub-format", "srt/ass/best",
        "--windows-filenames", "--trim-filenames", "200",
        "--clean-info-json",
        "--limit-rate", "8M",
        "--retries", "3",
        "--fragment-retries", "2",
        "--retry-sleep", "fragment:exp=1:8",
        "--socket-timeout", "30",
        "-o", f"{OUTPUT_DIR}/%(title)s.%(ext)s",
    ]
    if use_cookies and os.path.exists(cookie_path) and os.path.getsize(cookie_path) > 0:
        cmd.extend(["--cookies", cookie_path])
        
    cmd.append(target_url)
    return cmd

def clean_downloads():
    for leftover in glob.glob(f"{OUTPUT_DIR}/*"):
        try:
            if os.path.isfile(leftover) or os.path.islink(leftover):
                os.remove(leftover)
            elif os.path.isdir(leftover):
                shutil.rmtree(leftover)
        except Exception:
            pass

# ---------------------------------------------------------------
# واجهة المستخدم
# ---------------------------------------------------------------
col_url, col_limit = st.columns([3, 1])
with col_url:
    url = st.text_input("رابط الفيديو أو قائمة التشغيل:", placeholder="https://www.youtube.com/watch?v=...")
with col_limit:
    max_new_allowed = st.number_input("الحد الأقصى للمقاطع الجديدة:", min_value=1, max_value=50, value=15)

if st.button("بدء الأرشفة المتسلسلة والرفع المنظم", type="primary"):
    if not url.strip():
        st.warning("يرجى إدخال رابط صالح.")
    else:
        os.makedirs(OUTPUT_DIR, exist_ok=True)

        st.info("جاري فحص الرابط ومزامنة أرشيف Google Drive...")

        drive_service = get_gdrive_service()
        root_folder_id = st.secrets["GDRIVE_FOLDER_ID"]

        # تحميل المعرفات المعتمدة من video_archive.txt
        archived_ids, drive_archive_id = load_archive_from_gdrive(drive_service, root_folder_id)

        # استخراج بيانات القائمة
        list_cmd = [
            "yt-dlp",
            "--force-ipv4",
            "--flat-playlist",
            "--print", "%(id)s|||%(channel)s|||%(playlist_title)s|||%(title)s"
        ]
        if os.path.exists(cookie_path) and os.path.getsize(cookie_path) > 0:
            list_cmd.extend(["--cookies", cookie_path])
        list_cmd.append(url.strip())

        video_items = []
        channel_name = "قناة عامة"
        playlist_name = "فيديوهات فردية"

        try:
            res = subprocess.run(list_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
            lines = [l.strip() for l in res.stdout.split("\n") if l.strip()]

            for line in lines:
                parts = line.split("|||")
                if len(parts) >= 1:
                    vid_id = parts[0].strip()
                    if vid_id and len(vid_id) == 11:
                        v_title = parts[3].strip() if len(parts) >= 4 else ""
                        video_items.append({"id": vid_id, "title": v_title})
                    if len(parts) >= 2 and parts[1].strip() and channel_name == "قناة عامة":
                        channel_name = parts[1].strip()
                    if len(parts) >= 3 and parts[2].strip() and parts[2].strip() != "NA" and playlist_name == "فيديوهات فردية":
                        playlist_name = parts[2].strip()

            if not video_items:
                video_items = [{"id": url.strip(), "title": ""}]
        except Exception:
            video_items = [{"id": url.strip(), "title": ""}]

        channel_name = "".join(c for c in channel_name if c.isalnum() or c in (' ', '-', '_')).strip()
        playlist_name = "".join(c for c in playlist_name if c.isalnum() or c in (' ', '-', '_')).strip()

        # تجهيز المجلدات في Google Drive
        channel_folder_id = get_or_create_folder(drive_service, channel_name, root_folder_id)
        playlist_folder_id = get_or_create_folder(drive_service, playlist_name, channel_folder_id)

        total_videos = len(video_items)
        st.success(f"تم فحص القائمة ({total_videos} مقطع). الأرشيف يحتوي على {len(archived_ids)} مقطع مؤكد.")

        progress_bar = st.progress(0)
        status_text = st.empty()
        terminal_box = st.empty()

        consecutive_fails = 0
        new_done = 0
        stopped_early = False

        for idx, item in enumerate(video_items):
            vid = item["id"]
            title_hint = item["title"]
            target_url = f"https://www.youtube.com/watch?v={vid}" if len(vid) == 11 else vid
            current_num = idx + 1

            # تخطي فوري للحلقات المسجلة في video_archive.txt
            if vid in archived_ids:
                status_text.markdown(f"⏭️ **({current_num}/{total_videos})** `{title_hint or vid}` مؤكد في الأرشيف، تم التخطي.")
                progress_bar.progress(current_num / total_videos)
                continue

            if new_done >= max_new_allowed:
                st.warning(f"تم بلوغ حد {max_new_allowed} مقاطع في هذا التشغيل. أعد التشغيل لاحقاً لإكمال الباقي (الأرشيف يحفظ ما تم).")
                stopped_early = True
                break

            downloaded = False
            for attempt_idx, config in enumerate(CLIENT_ATTEMPTS):
                clean_downloads()
                profile = config["profile"]
                use_cookies = config["use_cookies"]
                
                cookie_status = "مع الكوكيز" if use_cookies else "بدون كوكيز"
                status_text.markdown(f"⬇️ **({current_num}/{total_videos})** `{target_url}` — المحاولة {attempt_idx + 1}/{MAX_ATTEMPTS} ({cookie_status})")

                process = subprocess.Popen(
                    build_cmd(target_url, profile, use_cookies=use_cookies),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace"
                )
                log_window = []
                for line in process.stdout:
                    log_window.append(line)
                    terminal_box.code("".join(log_window[-8:]), language="bash")
                process.wait()

                if process.returncode == 0 and glob.glob(f"{OUTPUT_DIR}/*.mkv"):
                    downloaded = True
                    break

                if attempt_idx < MAX_ATTEMPTS - 1:
                    wait = random.randint(40, 75) * (attempt_idx + 1)
                    status_text.markdown(f"⚠️ فشلت المحاولة {attempt_idx + 1}. انتظار {wait} ثانية ثم إعادة المحاولة بالبروفايل البديل...")
                    time.sleep(wait)

            uploaded_ok = False
            if downloaded:
                for f in glob.glob(f"{OUTPUT_DIR}/*.mkv"):
                    if upload_to_organized_gdrive(drive_service, f, playlist_folder_id):
                        st.success(f"تم رفع `{os.path.basename(f)}` بنجاح إلى Drive!")
                        archived_ids.add(vid)
                        drive_archive_id = append_and_sync_archive(vid, drive_service, root_folder_id, drive_archive_id)
                        os.remove(f)
                        uploaded_ok = True

            if uploaded_ok:
                consecutive_fails = 0
                new_done += 1
            else:
                clean_downloads()
                consecutive_fails += 1
                st.error(f"تعذر تحميل/رفع المقطع رقم {current_num}. راجع السجل أعلاه.")
                if consecutive_fails >= MAX_CONSECUTIVE_FAILS:
                    st.error("توقف تلقائي: فشل متتالٍ يعني أن الـ IP أو الجلسة محظورة مؤقتاً. أعد التشغيل بعد فترة.")
                    stopped_early = True
                    break

            progress_bar.progress(current_num / total_videos)

            # فاصل أمان زمني ذكي بين كل مقطع وآخر (بين 35 و 65 ثانية)
            time.sleep(random.randint(35, 65))

        if not stopped_early:
            st.success("تم الانتهاء من أرشفة كامل المحتوى بنجاح!")
