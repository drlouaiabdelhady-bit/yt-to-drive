import random

        for idx, vid in enumerate(video_entries):
            target_url = f"https://www.youtube.com/watch?v={vid}" if len(vid) == 11 else vid
            status_text.text(f"جاري معالجة العنصر {idx + 1} من {len(video_entries)}...")

            cmd = [
                "yt-dlp",
                "--remote-components", "ejs:github",
                "--extractor-args", "youtubetab:skip=authcheck;youtube:player_client=web",
                "--no-playlist",
                "--ignore-errors",  # لتخطي أي ملف تالف تلقائياً
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
                # تشغيل التحميل مع حماية try-except لضمان عدم توقف السكربت بالكامل
                proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")

                mkv_files = glob.glob(f"{output_dir}/*.mkv")
                if mkv_files:
                    for f in mkv_files:
                        success = upload_to_organized_gdrive(f, channel_name, playlist_name)
                        if success:
                            os.remove(f)
            except Exception as e:
                st.warning(fُتخطي مؤقت للعنصر بسبب خطأ تقني: {e}")

            progress_bar.progress((idx + 1) / len(video_entries))
            
            # فاصل زمني عشوائي ذكي وآمن (بين 6 إلى 12 ثانية) لخداع أنظمة الرصد
            sleep_time = random.randint(6, 12)
            time.sleep(sleep_time)
