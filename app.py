import streamlit as st
import subprocess
import glob
import os
import shutil
import urllib.request
import zipfile

st.set_page_config(page_title="YouTube MKV Archiver", layout="centered")

st.title("أرشفة يوتيوب إلى Matroska (MKV)")
st.caption("بروفايل أرشفة متكامل: أعلى دقة صوت وصورة | فصول | ترجمات | غلاف | بيانات وصفية")

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

url = st.text_input("رابط الفيديو أو قائمة التشغيل:", placeholder="https://www.youtube.com/watch?v=...")

if st.button("بدء المعالجة والتنزيل", type="primary"):
    if not url.strip():
        st.warning("يرجى إدخال رابط صالح.")
    else:
        output_dir = "downloads"
        os.makedirs(output_dir, exist_ok=True)

        cmd = [
            "yt-dlp",
            # تفعيل جلب حزم فك التشفير عبر GitHub ومحرك Deno
            "--remote-components", "ejs:github",
            # أولوية أعلى دقة فيديو + مسار الصوت العربي (أو أفضل صوت متاح كبديل)
            "-f", "bv*+ba[language^=ar]/bv*+ba/b",
            # التغليف النهائي داخل حاوية Matroska (MKV)
            "--merge-output-format", "mkv",
            # الأرشفة والبيانات الوصفية
            "--embed-metadata",
            # دمج الفصول الزمنية لتسهيل التنقل بالريموت
            "--embed-chapters",
            # دمج الغلاف الرسمي كأيقونة
            "--embed-thumbnail",
            # دمج الترجمات العربية والإنجليزية soft-subs وحذف الملفات المؤقتة
            "--embed-subs",
            "--sub-langs", "ar,en",
            "--sub-format", "srt/ass/best",
            # توافقية مسارات نظام ويندوز
            "--windows-filenames",
            "--trim-filenames", "200",
            # تنظيف ملفات الـ JSON المؤقتة
            "--clean-info-json",
            # مسار وتسمية المخرجات
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
                st.write("**الملفات الجاهزة في السيرفر السحابي:**")
                for f in mkv_files:
                    file_size_mb = os.path.getsize(f) / (1024 * 1024)
                    st.write(f"- `{os.path.basename(f)}` ({file_size_mb:.2f} MB)")
        else:
            st.error("حدث خطأ أثناء تنفيذ الأمر عبر yt-dlp.")
