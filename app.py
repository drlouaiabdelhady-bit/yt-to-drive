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
st.caption("بروفايل أرشفة متكامل: أعلى دقة | فصول | ترجمات | غلاف | استئناف قياسي بملف الأرشيف ID")

# 1. تجهيز محرك Deno السحابي لحل شفرات التحدي (n-challenge)
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

# 4. منظومة إدارة ملف الأرشيف القياسي (archive.txt) على Google Drive
LOCAL_ARCHIVE_FILE = "archive.txt"

def load_archive_from_gdrive(drive_service, root_folder_id):
    """جلب ملف archive.txt من المجلد الرئيسي في Drive أو إنشاؤه محلياً"""
    query = f"name = 'archive.txt' and '{root_folder_id}' in parents and trashed = false"
    res = drive_service.files().list(
        q=query,
        spaces='drive',
        fields='files(id, name)',
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
        content = fh.read().decode('utf-8', errors='ignore')
        with open(LOCAL_ARCHIVE_FILE, "w", encoding="utf-8") as f:
            f.write(content)
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("youtube "):
                archived_ids.add(line.split()[1].strip())
    else:
        with open(LOCAL_ARCHIVE_FILE, "w", encoding="utf-8") as f:
            f.write("")

    return archived_ids, drive_archive_id

def sync_archive_to_gdrive(drive_service, root_folder_id, drive_archive_id):
    """رفع أو تحديث ملف archive.txt في Google Drive فوراً"""
    media = MediaFileUpload(LOCAL_ARCHIVE_FILE, mimetype='text/plain', resumable=False)
    if drive_archive_id:
        drive_service.files().update(
            fileId=drive_archive_id,
            media_body=media,
            supportsAllDrives=True
        ).execute()
        return drive_archive_id
    else:
        file_metadata = {
            'name': 'archive.txt',
            'parents': [root_folder_id]
        }
        res = drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id',
            supportsAllDrives=True
        ).execute()
        return res.get('id')

def add_to_archive(vid_id, drive_service, root_folder_id, drive_archive_id):
    """إضافة معرف الفيديو إلى الأرشيف ومزامنته سحابياً"""
    with open(LOCAL_ARCHIVE_FILE, "a", encoding="utf-8") as f:
        f.write(f"youtube {vid_id}\n")
    return sync_archive_to_gdrive(drive_service, root_folder_id, drive_archive_id)

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

# واجهة مستخدم موحدة
url = st.text_input("رابط الفيديو أو قائمة التشغيل:", placeholder="https://www.youtube.com/watch?v=...")

if st.button("بدء الأرشفة المتسلسلة والرفع المنظم", type="primary"):
    if not url.strip():
        st.warning("يرجى إدخال رابط صالح.")
    else:
        output_dir = "downloads"
        os.makedirs(output_dir, exist_ok=True)

        st.info("جاري فحص الرابط ومزامنة أرشيف Google Drive...")
        
        drive_service = get_gdrive_service()
        root_folder_id = st.secrets["GDRIVE_FOLDER_ID"]

        # تحميل أرشيف المعرفات من Google Drive
        archived_ids, drive_archive_id = load_archive_from_gdrive(drive_service, root_folder_id)

        # استخراج بيانات القائمة
        list_cmd = [
            "yt-dlp",
            "--force-ipv4",
            "--flat-playlist",
            "--print", "%(id)s|||%(channel)s|||%(playlist_title)s|||%(title)s",
            "--extractor-args", "youtubetab:skip=authcheck"
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

        # التوافق التلقائي الأول: إذا كان الأرشيف جديداً وفيه مقاطع مرفوعة مسبقاً، نسجلها فوراً
        if len(archived_ids) == 0:
            st.info("فحص الملفات المرفوعة مسبقاً لمزامنتها مع ملف الأرشيف الجديد...")
            query = f"'{playlist_folder_id}' in parents and mimeType != 'application/vnd.google-apps.folder' and trashed = false"
            res = drive_service.files().list(q=query, spaces='drive', fields='files(name)').execute()
            existing_names = [f['name'] for f in res.get('files', [])]
            
            for item in video_items:
                v_title = item["title"]
                match = re.search(r'الحلقة\s*(\d+)', v_title)
                ep_num = match.group(1) if match else None
                for en in existing_names:
                    if (ep_num and f"الحلقة {ep_num}" in en) or ("تتر البداية" in v_title and "تتر البداية" in en):
                        archived_ids.add(item["id"])
                        with open(LOCAL_ARCHIVE_FILE, "a", encoding="utf-8") as f:
                            f.write(f"youtube {item['id']}\n")
                        break
            
            drive_archive_id = sync_archive_to_gdrive(drive_service, root_folder_id, drive_archive_id)

        total_videos = len(video_items)
        st.success(f"تم فحص القائمة ({total_videos} مقطع). الأرشيف يحتوي على {len(archived_ids)} مقطع مسجل.")

        progress_bar = st.progress(0)
        status_text = st.empty()
        terminal_box = st.empty()

        for idx, item in enumerate(video_items):
            vid = item["id"]
            title_hint = item["title"]
            target_url = f"https://www.youtube.com/watch?v={vid}" if len(vid) == 11 else vid
            current_num = idx + 1

            # تخطي فوري بنسبة 100% عبر المعرف المسجل
            if vid in archived_ids:
                status_text.markdown(f"⏭️ **المقطع ({current_num} / {total_videos}):** `{title_hint or vid}` مؤرشف مسبقاً، تم التخطي.")
                progress_bar.progress(current_num / total_videos)
                continue

            status_text.markdown(f"⬇️ **معالجة المقطع ({current_num} / {total_videos}):** `{target_url}`")

            cmd = [
                "yt-dlp",
                "--force-ipv4",
                "--remote-components", "ejs:github",
                "--extractor-args", "youtubetab:skip=authcheck;youtube:player_client=tv,mweb",
                "--no-playlist",
                "-f", "bv*+ba[language^=ar]/bv*+ba/b",
                "--merge-output-format", "mkv",
                "--embed-metadata",
                "--embed-chapters",
                "--embed-thumbnail",
                "--embed-subs",
                "--sub-langs", "ar,en",
                "--sub-format", "srt/ass/best",
                "--windows-filenames",
                "--trim-filenames", "200",
                "--clean-info-json",
                "--limit-rate", "12M",
                "--retries", "10",
                "--fragment-retries", "10",
                "--socket-timeout", "30",
                "-o", f"{output_dir}/%(title)s.%(ext)s"
            ]

            if os.path.exists(cookie_path) and os.path.getsize(cookie_path) > 0:
                cmd.extend(["--cookies", cookie_path])

            cmd.append(target_url)

            process = subprocess.Popen(
                cmd,
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

            # رفع المقطع المكتمل وتحديث الأرشيف في Drive
            mkv_files = glob.glob(f"{output_dir}/*.mkv")
            if mkv_files:
                for f in mkv_files:
                    success = upload_to_organized_gdrive(drive_service, f, playlist_folder_id)
                    if success:
                        st.success(f"تم رفع `{os.path.basename(f)}` بنجاح إلى Drive!")
                        # تسجيل المعرف في الأرشيف وتحديث ملف Drive فوراً
                        archived_ids.add(vid)
                        drive_archive_id = add_to_archive(vid, drive_service, root_folder_id, drive_archive_id)
                        os.remove(f)
            else:
                st.error(f"تعذر تحميل المقطع رقم {current_num}. راجع السجل أعلاه.")
                for leftover in glob.glob(f"{output_dir}/*"):
                    try:
                        os.remove(leftover)
                    except Exception:
                        pass

            progress_bar.progress(current_num / total_videos)
            
            # تباعد زمني آمن لتجنب حظر الـ Rate-limit
            sleep_time = random.randint(20, 35)
            time.sleep(sleep_time)

        st.success("تم الانتهاء من أرشفة كامل المحتوى بنجاح!")
