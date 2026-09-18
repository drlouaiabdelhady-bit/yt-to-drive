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

st.title("أرشفة يوتيوب إلى Matroska (MKV) والرفع السحابي المنظم")
st.caption("بروفايل أرشفة متكامل: أعلى دقة | فصول | ترجمات | غلاف | تنظيم تلقائي للمجلدات في Google Drive")

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

        # 1. إنشاء أو جلب مجلد القناة داخل المجلد الرئيسي
        channel_folder_id = get_or_create_folder(drive, channel_name, root_folder_id)

        # 2. إنشاء أو جلب مجلد قائمة التشغيل (Playlist) داخل مجلد القناة
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

if st.button("بدء المعالجة، التحميل والرفع المنظم", type="primary"):
    if not url.strip():
        st.warning("يرجى إدخال رابط صالح.")
    else:
        output_dir = "downloads"
        os.makedirs(output_dir, exist_ok=True)

        # أمر استخراج اسم القناة واسم القائمة أولاً عبر yt-dlp
        st.info("جاري استخراج بيانات القناة وقائمة التشغيل...")
        info_cmd = ["yt-dlp", "--print", "%(channel)s|||%(playlist_title)s", "--no-download"]
        if os.path.exists(cookie_path) and os.path.getsize(cookie_path) > 0:
            info_cmd.extend(["--cookies", cookie_path])
        info_cmd.append(url.strip())

        try:
            res = subprocess.run(info_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
            lines = res.stdout.strip().split("\n")
            meta_parts = lines[0].split("|||") if lines and lines[0] else ["قناة عامة", "فيديوهات فردية"]
            channel_name = meta_parts[0].strip() if len(meta_parts) > 0 and meta_parts[0].strip() else "قناة عامة"
            playlist_name = meta_parts[1].strip() if len(meta_parts) > 1 and meta_parts[1].strip() != "NA" else "فيديوهات فردية"
        except Exception:
            channel_name = "قناة عامة"
            playlist_name = "فيديوهات فردية"

        # تنظيف أسماء المجلدات من الحروف الممنوعة في نظام الملفات
        channel_name = "".join(c for c in channel_name if c.isalnum() or c in (' ', '-', '_')).strip()
        playlist_name = "".join(c for c in playlist_name if c.isalnum() or c in (' ', '-', '_')).strip()

        cmd = [
            "yt-dlp",
            "--remote-components", "ejs:github",
            # استخدام أفضل دقة متاحة كملف واحد أو دمج آمن
            "-f", "bv*+ba/b",
            "--merge-output-format", "mkv",
            # تجاوز قيود HLS القسرية واستخدام بروتوكول الأندرويد المحاكي لتفادي 403
            "--hls-prefer-native",
            "--extractor-args", "youtube:player_client=android",
            # إعدادات المحاولات والمهلات المرتفعة لتفادي أخطاء الأجزاء
            "--retries", "30",
            "--fragment-retries", "30",
            "--retry-sleep", "fragment:exp=1:5",
            "--skip-unavailable-fragments",
            "--socket-timeout", "60",
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

        st.info(f"بدأت معالجة المقطع وسحب المسارات للقناة: [{channel_name}]...")
        
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
                    success = upload_to_organized_gdrive(f, channel_name, playlist_name)
                    if success:
                        st.success(f"تم رفع الملف بنجاح وترتيبه داخل Google Drive تحت: {channel_name} / {playlist_name}!")
                        os.remove(f)
                        st.info("تم تنظيف السيرفر السحابي وحذف النسخة المحلية بنجاح.")
        else:
            st.error("حدث خطأ أثناء تنفيذ الأمر عبر yt-dlp.")
