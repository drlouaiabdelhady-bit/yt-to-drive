import streamlit as st
import subprocess
import glob
import os

st.set_page_config(page_title="YouTube MKV Archiver", layout="centered")

st.title("أرشفة يوتيوب إلى Matroska (MKV)")
st.caption("بروفايل أرشفة متكامل: أعلى دقة صوت وصورة | فصول | ترجمات | غلاف | بيانات وصفية")

url = st.text_input("رابط الفيديو أو قائمة التشغيل:", placeholder="https://www.youtube.com/watch?v=...")

if st.button("بدء المعالجة والتنزيل", type="primary"):
    if not url.strip():
        st.warning("يرجى إدخال رابط صالح.")
    else:
        output_dir = "downloads"
        os.makedirs(output_dir, exist_ok=True)

        cmd = [
            "yt-dlp",
            "--no-cache-dir",
            # تخطي فحص البوت نهائياً بمحاكاة مشغل التلفاز الذكي
            "--extractor-args", "youtube:player_client=tv,tv_embedded",
            # أولوية أعلى دقة فيديو + مسار الصوت العربي (أو أفضل صوت متاح كبديل)
            "-f", "bv*+ba[language^=ar]/bv*+ba/b",
            # التغليف النهائي داخل حاوية MKV
            "--merge-output-format", "mkv",
            # الأرشفة والبيانات الوصفية
            "--embed-metadata",
            "--embed-chapters",
            "--embed-thumbnail",
            # منظومة الترجمة الذكية
            "--embed-subs",
            "--sub-langs", "ar,en",
            "--sub-format", "srt/ass/best",
            # توافقية مسارات وأسماء نظام ويندوز
            "--windows-filenames",
            "--trim-filenames", "200",
            # تنظيف المخلفات المؤقتة
            "--clean-info-json",
            # مسار وتسمية المخرجات
            "-o", f"{output_dir}/%(title)s.%(ext)s",
            url.strip()
        ]

        st.info("بدأت معالجة المقطع وسحب المسارات عبر مشغل التلفاز الذكي...")
        
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
