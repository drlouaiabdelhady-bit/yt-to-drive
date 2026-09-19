import streamlit as st
import subprocess
import glob
import os
import shutil
import urllib.request
import zipfile
import json
import time
import random
from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive

st.set_page_config(page_title="YouTube MKV Archiver & Drive", layout="centered")

st.title("أرشفة يوتيوب إلى Matroska (MKV) والرفع السحابي المنظم")
st.caption("بروفايل أرشفة متكامل: أعلى دقة | فصول | ترجمات | غلاف | أرشفة متسلسلة آمنة للقوائم")

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
        except Exception as e:
            pass

    if os.path.exists(deno_bin):
        if os.getcwd() not in os.environ.get("PATH", ""):
            os.environ["PATH"] = f"{os.getcwd()}:{os.environ.get('PATH', '')}"

prepare_js_engine()

# 2. حقن الكوكيز تلقائياً من Streamlit Secrets مع المسار المطلق
cookie_path = os.path.join(os.getcwd(), "session_cookies.txt")
if "YOUTUBE_COOKIES" in st.secrets:
    with open(cookie_path, "w", encoding="utf-8") as f:
        f.write(st.secrets["YOUTUBE_COOKIES"])

# دالة مساعدة للبحث عن مجلد أو إنشائه في Google Drive
def get_or_create_folder(drive, folder_name, parent_id):
    query = f"title='{folder_name}' and '{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
    folder_list = drive.ListFile({'q': query}).GetList()
    if folder_list:
        return folder_list[0]['id']
    else:
        folder_metadata = {
            'title': folder_name,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [{'id': parent_id}]
        }
        folder = drive.CreateFile(folder_metadata)
        folder.Upload()
        return folder['id']

# دالة الرفع المنظم إلى Google Drive بناءً على اسم القناة وقائمة التشغيل
def upload_to_organized_gdrive(file_path, channel_name, playlist_name):
    try:
        if "GDRIVE_KEY" not in st.secrets or "GDRIVE_FOLDER_ID" not in st.secrets:
            st.error("بيانات Google Drive غير مكتملة في Streamlit Secrets.")
            return False

        creds_dict = json.loads(st.secrets["GDRIVE_KEY"])
        temp_creds_path = "temp_service_account.json"
        with open(temp_creds_path, "w", encoding="utf-8") as f:
            json.dump(creds_dict, f)

        root_folder_id = st.secrets["GDRIVE_FOLDER_ID"]

        gauth = GoogleAuth()
        gauth.settings = {
            "client_config_backend": "service",
            "service_config": {
                "client_json_file_path": temp_creds_path,
            }
        }
        gauth.ServiceAuth()
        drive = GoogleDrive(gauth)

        channel_folder_id = get_or_create_folder(drive, channel_name, root_folder_id)
        playlist_folder_id = get_or_create_folder(drive, playlist_name, channel_folder_id)

        file_name = os.path.basename(file_path)
        st.info(f"جاري رفع الملف `{file_name}` إلى مجلد القناة ({channel_name}) -> قائمة ({playlist_name})...")
        
        gfile = drive.CreateFile({
            'title': file_name,
            'parents': [{'id': playlist_folder_id}]
        })
        gfile.SetContentFile(file_path)
        gfile.Upload()

        if os.path.exists(temp_creds_path):
            os.remove(temp_creds_path)

        return True
    except Exception as e:
        st.error(f"حدث خطأ أثناء الرفع المنظم إلى Google Drive: {e}")
        return False

url = st.text_input("رابط الفيديو أو قائمة التشغيل:", placeholder="https://www.youtube.com/watch?v=...")

if st.button("بدء الأرشفة المتسلسلة والرفع المنظم", type="primary"):
    if not url.strip():
        st.warning("يرجى إدخال رابط صالح.")
    else:
        output_dir = "downloads"
        os.makedirs(output_dir, exist_ok=True)

        st.info("جاري استخراج روابط القائمة وترتيبها بأمان...")
        
        list_cmd = ["yt-dlp", "--flat-playlist", "--print", "%(id)s|||%(channel)s|||%(playlist_title)s", "--extractor-args", "youtubetab:skip=authcheck"]
        if os.path.exists(cookie_path) and os.path.getsize(cookie_path) > 0:
            list_cmd.extend(["--cookies", cookie_path])
        list_cmd.append(url.strip())

        video_entries = []
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
                        video_entries.append(vid_id)
                    if len(parts) >= 2 and parts[1].strip() and channel_name == "قناة عامة":
                        channel_name = parts[1].strip()
                    if len(parts) >= 3 and parts[2].strip() and parts[2].strip() != "NA" and playlist_name == "فيديوهات فردية":
                        playlist_name = parts[2].strip()
            
            if not video_entries:
                video_entries = [url.strip()]
        except Exception:
            video_entries = [url.strip()]

        channel_name = "".join(c for c in channel_name if c.isalnum() or c in (' ', '-', '_')).strip()
        playlist_name = "".join(c for c in playlist_name if c.isalnum() or c in (' ', '-', '_')).strip()

        st.success(f"تم العثور على {len(video_entries)} مقطع. سيتم أرشفتها ورفعها على دفعات آمنة...")

        progress_bar = st.progress(0)
        status_text = st.empty()

        for idx, vid in enumerate(video_entries):
            target_url = f"https://www.youtube.com/watch?v={vid}" if len(vid) == 11 else vid
            status_text.text(f"جاري معالجة العنصر {idx + 1} من {len(video_entries)}...")

            cmd = [
                "yt-dlp",
                "--remote-components", "ejs:github",
                "--extractor-args", "youtubetab:skip=authcheck;youtube:player_client=web",
                "--no-playlist",
                "--ignore-errors",
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
                "-o", f"{output_dir}/%(title)s.%(ext)s"
            ]

            if os.path.exists(cookie_path) and os.path.getsize(cookie_path) > 0:
                cmd.extend(["--cookies", cookie_path])

            cmd.append(target_url)

            try:
                subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")

                mkv_files = glob.glob(f"{output_dir}/*.mkv")
                if mkv_files:
                    for f in mkv_files:
                        success = upload_to_organized_gdrive(f, channel_name, playlist_name)
                        if success:
                            os.remove(f)
            except Exception as e:
                st.warning(f"تخطي مؤقت للعنصر بسبب خطأ تقني: {e}")

            progress_bar.progress((idx + 1) / len(video_entries))
            
            sleep_time = random.randint(6, 12)
            time.sleep(sleep_time)

        st.success("تم الانتهاء من أرشفتة ورفع القائمة كاملة إلى Google Drive بنجاح تام!")
        st.info("تم تنظيف السيرفر السحابي بالكامل.")
