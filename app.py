import streamlit as st
import subprocess
import glob
import os
import shutil
import urllib.request
import zipfile
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

st.set_page_config(page_title="YouTube MKV Archiver & Drive", layout="centered")

st.title("أرشفة يوتيوب إلى Matroska (MKV) والرفع السحابي")
st.caption("بروفايل أرشفة متكامل: أعلى دقة | فصول | ترجمات | غلاف | رفع تلقائي لـ Google Drive")

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

# 2. حقن الكوكيز تلقائياً من Streamlit Secrets
cookie_path = "session_cookies.txt"
if "YOUTUBE_COOKIES" in st.secrets:
    with open(cookie_path, "w", encoding="utf-8") as f:
        f.write(st.secrets["YOUTUBE_COOKIES"])

# دالة الرفع إلى Google Drive
def upload_to_gdrive(file_path):
    try:
        if "GDRIVE_KEY" not in st.secrets or "GDRIVE_FOLDER_ID" not in st.secrets:
            st.error("بيانات Google Drive غير مكتملة في Streamlit Secrets.")
            return False

        key_info = json.loads(st.secrets["GDRIVE_KEY"])
        folder_id = st.secrets["GDRIVE_FOLDER_ID"]

        creds = service_account.Credentials.from_service_account_info(
            key_info, scopes=['https://www.googleapis.com/auth/drive.file']
        )
        service = build('drive', 'v3', credentials=creds)

        file_name = os.path.basename(file_path)
        body = {
            'name': file_name,
            'parents': [folder_id]
        }
        media = MediaFileUpload(file_path, resumable=True)
        
        st.info(f"جاري رفع الملف `{file_name}` إلى Google Drive...")
        file = service.files().create(body=body, media_body=media, fields='id').execute()
        return True
    except Exception as e:
        st.error(f"حدث خطأ أثناء الرفع إلى Google Drive: {e}")
        return False

url = st.text_input("رابط الفيديو أو قائمة التشغيل:", placeholder="https://www.youtube.com/watch?v=...")

if st.button("بدء المعالجة، التحميل والرفع", type="primary"):
    if not url.strip():
        st.warning("يرجى إدخال رابط صالح.")
    else:
        output_dir = "downloads"
        os.makedirs(output_dir, exist_ok=True)

        cmd = [
            "yt-dlp",
            "--remote-components", "ejs:github",
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

        cmd.append(url.strip())

        st.info("بدأت معالجة المقطع وسحب المسارات...")
        
        terminal_box = st.empty()
        log_lines = []

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace"
        )

        for line in process.stdout:
            log_lines.append(line)
            terminal_box.code("".join(log_lines[-12:]), language="bash")

        process.wait()

        if process.returncode == 0:
            st.success("اكتمل التحميل والدمج وتطبيق بروفايل الأرشفة بنجاح!")
            mkv_files = glob.glob(f"{output_dir}/*.mkv")
            if mkv_files:
                for f in mkv_files:
                    # رفع الملف إلى Google Drive
                    success = upload_to_gdrive(f)
                    if success:
                        st.success(f"تم رفع الملف بنجاح إلى مجلد Google Drive المحدد!")
                        # حذف الملف من السيرفر لتفريغ المساحة
                        os.remove(f)
                        st.info("تم تنظيف السيرفر السحابي وحذف النسخة المحلية بنجاح.")
        else:
            st.error("حدث خطأ أثناء تنفيذ الأمر عبر yt-dlp.")
