import streamlit as st
import subprocess
import glob
import os
import shutil
import urllib.request
import zipfile
import json
from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive

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

# دالة الرفع إلى Google Drive باستخدام PyDrive2
def upload_to_gdrive(file_path):
    try:
        if "GDRIVE_KEY" not in st.secrets or "GDRIVE_FOLDER_ID" not in st.secrets:
            st.error("بيانات Google Drive غير مكتملة في Streamlit Secrets.")
            return False

        creds_dict = json.loads(st.secrets["GDRIVE_KEY"])
        temp_creds_path = "temp_service_account.json"
        with open(temp_creds_path, "w", encoding="utf-8") as f:
            json.dump(creds_dict, f)

        folder_id = st.secrets["GDRIVE_FOLDER_ID"]

        gauth = GoogleAuth()
        gauth.settings = {
            "client_config_backend": "service",
            "service_config": {
                "client_json_file_path": temp_creds_path,
            }
        }
        gauth.ServiceAuth()
        drive = GoogleDrive(gauth)

        file_name = os.path.basename(file_path)
        st.info(f"جاري رفع الملف `{file_name}` إلى Google Drive...")
        
        gfile = drive.CreateFile({
            'title': file_name,
            'parents': [{'id': folder_id}]
        })
        gfile.SetContentFile(file_path)
        gfile.Upload()

        if os.path.exists(temp_creds_path):
            os.remove(temp_creds_path)

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
            # أولوية أعلى دقة فيديو + مسار الصوت العربي
            "-f", "bv*+ba[language^=ar]/bv*+ba/b",
            # التغليف النهائي داخل حاوية Matroska (MKV)
            "--merge-output-format", "mkv",
            # إدارة أخطاء الـ Fragments وإعادة المحاولة لتفادي الحظر المؤقت
            "--retries", "20",
            "--fragment-retries", "20",
            "--retry-sleep", "fragment:exp=1:5",
            "--skip-unavailable-fragments",
            "--socket-timeout", "30",
            # الأرشفة والبيانات الوصفية
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
                    success = upload_to_gdrive(f)
                    if success:
                        st.success("تم رفع الملف بنجاح إلى مجلد Google Drive المحدد!")
                        os.remove(f)
                        st.info("تم تنظيف السيرفر السحابي وحذف النسخة المحلية بنجاح.")
        else:
            st.error("حدث خطأ أثناء تنفيذ الأمر عبر yt-dlp.")
