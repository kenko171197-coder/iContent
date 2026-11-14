# Studio566

Dán link Douyin / Bilibili / Xiaohongshu / Weibo... → tool tự **tải video → nhận dạng tiếng Trung (ghép với sub gốc in trên video) → dịch sang tiếng Việt có ngữ cảnh → lồng tiếng giọng nam/nữ khớp timeline → xóa hẳn sub gốc, burn phụ đề kiểu TikTok → xuất video nhiều khung + ảnh bìa + tiêu đề/caption/hashtag**. Có giao diện web để sửa từng câu, nghe thử và xuất lại.

```
link ─► download ─► audio ─► separate ─► hardsub ─► asr ──────► translate ──────► tts ─────────► render ─► output/
        yt-dlp      ffmpeg   UVR/MDX     OCR dò    whisper     phân tích ngữ    chọn giọng      ffmpeg     .mp4 .srt
        (+lệnh                (tùy chọn)  vùng sub  + ghép OCR  cảnh + xưng hô   nam/nữ, VieNeu  che sub,   .txt (caption)
         ngoài)                                     theo sub    → Claude/...     + căn giờ       ducking
```

Mỗi bước lưu kết quả vào `workspace/<job>/`, nên chạy lại sẽ bỏ qua bước đã xong và chỉ làm lại phần thay đổi.

**Studio566 miễn phí.** Chỉ dùng với video bạn có quyền sử dụng hoặc đã được phép đăng lại.

## Điểm nổi bật

- **Khám phá video và đề tài hot bên Trung Quốc:** hơn 500 video Bilibili đang thịnh hành, chia chuyên mục, chấm điểm "đáng làm" (lượt xem mỗi giờ, tương tác, độ dài, mức hợp lồng tiếng). Từ khóa hot của Douyin, Weibo, Baidu, Toutiao, Zhihu, Bilibili. Tiêu đề được dịch sang tiếng Việt. Gõ từ khóa tiếng Việt để tìm, chọn nhiều video rồi bấm một nút là làm.
- **Dựng ngay trong Studio, không phá file gốc:** cắt đoạn bằng cách kéo trên sóng âm, tự cắt khoảng lặng, xuất một đoạn thành clip riêng, chữ và ảnh trên video kéo thả trực tiếp, 10 bộ màu và nạp được file LUT `.cube`, mờ dần, mở đầu và kết thúc. Timeline có vạch chuyển cảnh, kéo chọn tự hít vào đầu câu và điểm chuyển cảnh. Tất cả chỉ mã hóa một lần nên không giảm chất lượng.
- **Khung hình đi theo nhân vật:** đổi video ngang sang 9:16 mà không mất người nói. Dò khuôn mặt và điểm chuyển cảnh rồi đi khung như người quay phim: đứng yên khi nhân vật còn ở giữa, chỉ lia khi nhân vật rời đi hẳn. Thấy ngay phần giữ lại trên video khi xem trước, kéo khung để tự đặt cho từng cảnh. Chạy trên máy, không cần mạng và GPU.
- **Gợi ý đoạn hay để cắt clip:** tìm các đoạn đáng làm clip ngắn dựa trên độ to của giọng, mật độ lời, nhịp chuyển cảnh và câu mở đầu, luôn cắt đúng ranh giới câu, và nói rõ vì sao chọn đoạn đó. Đây là tính toán trên số đo, không phải AI hiểu nội dung, nên vẫn cần nghe lại.
- **Kiểm định thành phẩm:** đo trên chính file đã xuất: màn hình đen, đứng hình, đoạn câm, độ to (LUFS), vỡ tiếng, hình và tiếng lệch độ dài, phụ đề che mặt, còn sót chữ Trung. Mỗi lỗi có mốc thời gian để bấm tới xem. Tự chạy sau mỗi lần dựng.
- **Xuất theo nền tảng và gói đăng bài:** chọn TikTok, Reels, Shorts, YouTube, Bảng tin. Nền tảng cùng khung dùng chung một lần dựng. Một nút gom video, ảnh bìa, phụ đề, tiêu đề, mô tả, hashtag vào một thư mục. Trên trình phát có thể bật vùng dễ bị nút của ứng dụng che (ước lượng, các nguồn cho số khác nhau).
- **Làm sạch giọng tự thu:** lọc tiếng ù, giảm ồn, hạ nền ở khoảng nghỉ, cân âm lượng, giữ đúng nhịp với hình.
- **Như một phần mềm riêng:** cửa sổ riêng có biểu tượng, không thanh địa chỉ, không cửa sổ dòng lệnh; đóng cửa sổ là tự tắt, còn video đang xử lý thì làm xong mới tắt.
- **Ghép video:** nhiều video và ảnh thành một, khác khung hình vẫn ghép được, có chuyển cảnh, cắt đầu cuối từng đoạn.
- **Video kể chuyện từ ảnh:** dán kịch bản hoặc nhờ AI viết từ một ý tưởng, mỗi cảnh một ảnh (ảnh tự có, ảnh trong thư viện, hoặc Gemini vẽ), lời dẫn và phụ đề tự khớp, máy quay zoom và lia nhẹ, chuyển cảnh, nhạc nền tự nhỏ đi khi có lời. Có sẵn một loạt ảnh thì chọn cùng lúc, mỗi ảnh thành một cảnh.
- **Nhân vật nhất quán:** mỗi nhân vật lưu 1 đến 4 ảnh mẫu (tải lên hoặc AI vẽ từ mô tả), AI vẽ mọi cảnh giữ đúng mặt, tóc, quần áo. Nguồn vẽ: Google Gemini, OpenAI (ChatGPT), Meta Muse Image, Cloudflare (có hạn mức miễn phí), hoặc chép lời nhắn sang ChatGPT, Copilot trên web rồi dán ảnh về.
- **Đọc văn bản:** dán chữ, chọn giọng (VieNeu chạy trên máy hoặc Edge), ra file MP3 kèm phụ đề SRT khớp từng câu.
- **Trình dựng tự do kiểu CapCut:** nhiều track hình và tiếng, keyframe, chuyển cảnh, hiệu ứng, chỉnh màu, chữ chuyển động, giao diện tiếng Việt. Từ Studio bấm một nút là mở video đã xóa sub và lồng tiếng, phụ đề nằm trên track riêng sửa được; dựng xong gửi về Studio566 để kiểm định và đóng gói đăng. Dựa trên [FreeCut](https://github.com/walterlow/freecut) (giấy phép MIT).
- **Sửa ảnh:** trình sửa ảnh đầy đủ (lớp, chữ, hiệu ứng, cắt, tẩy) nhúng sẵn, giao diện tiếng Việt, mở thẳng khung hình đã xóa sub, lưu làm ảnh bìa hoặc sticker. Dựa trên [miniPaint](https://github.com/viliusle/miniPaint) (giấy phép MIT).
- **Lồng tiếng từng câu:** thu giọng của bạn bằng micro hoặc tải file âm thanh cho đúng câu đó, đọc thử bản đang sửa, dịch lại một câu.
- **Studio như phần mềm dựng phim:**
  - **timeline nhiều track** (sóng âm gốc, sóng âm giọng lồng, khối phụ đề): kéo để dời câu, kéo mép để đổi thời lượng, Ctrl + lăn chuột để phóng to
  - **xem trước tức thì**: phụ đề, sub đã xóa và giọng lồng hiện ngay trên video gốc, không cần dựng lại; kéo phụ đề để đổi vị trí
  - **so sánh trước/sau** bằng thanh kéo trên cùng khung hình
  - sửa từng câu, tách/gộp câu, tìm và thay thế, hoàn tác (Ctrl+Z), phím tắt, bảng lệnh nhanh (Ctrl+K)
  - nút **Cập nhật video** chỉ làm lại đúng phần đã đổi
- **Xóa hẳn sub Trung, không làm mờ:** quét mặt nạ nét chữ cho từng câu rồi vá hình, chỉ đụng vào đúng nét chữ và viền chữ; khung không có sub giữ nguyên. Video 2:19 mất khoảng 40 giây trên CPU. Vẫn có chế độ làm mờ và dải tối.
- **Đọc sub gốc bằng OCR:** tự dò dải phụ đề, **ngắt câu theo đúng sub gốc** (mỗi câu thường là một lượt lời), và đưa chữ trên màn hình cho bước dịch để sửa lỗi nhận dạng tên riêng, con số.
- **Dịch có ngữ cảnh:** LLM đọc cả video trước để thống nhất **xưng hô** (anh/em/tôi/mình...) và tên riêng Hán-Việt; cùng lượt đó viết sẵn **tiêu đề, mô tả, hashtag**.
- **Mỗi người một giọng:** tự nghe ra video có mấy người nói, câu nào của ai, và cho mỗi người một giọng cố định. Câu nhận dạng gộp lời 2 người được tách đôi ngay chỗ đổi người. Trong Studio đặt tên, đổi giọng từng người, sửa người nói từng câu; mỗi người một màu trên timeline. Video một người đóng nhiều vai vẫn dùng một giọng.
- **Mô-đun AI miễn phí chạy trên máy:** Cài đặt > Mô-đun AI miễn phí, bấm Tải là có **Dịch offline** (1,1 GB) và **Vẽ ảnh offline** (5,3 GB). Không cần key, không cần mạng khi chạy, không phải cài Ollama; tải tiếp được khi rớt mạng, mọi file ghim phiên bản và kiểm SHA-256. Xem mục [Mô-đun AI miễn phí](#mô-đun-ai-miễn-phí).
- **Làm video cho thị trường nước ngoài:** chọn **Lồng tiếng sang** ngay ở ô dán link: 22 thứ tiếng (Anh, Indonesia, Thái, Philippines, Malaysia, Tây Ban Nha, Bồ Đào Nha, Nhật, Hàn, Hindi, Ả Rập, Pháp, Đức, Nga...). Dịch, phụ đề, giọng đọc, tiêu đề và hashtag đều theo thứ tiếng đó. Xem [Thị trường nước ngoài](#thị-trường-nước-ngoài).
- **Dịch không bao giờ dừng giữa chừng:** Gemini quá tải, hết lượt, sai key hay Google chặn thì Studio566 dịch tiếp đúng các câu còn thiếu bằng dịch offline (nếu đã tải), rồi Google. Hết cách thì khung Cách khắc phục có nút Tải Dịch offline.
- **Dịch offline:** không cần API key, không cần mạng khi dịch. Nhanh, nhưng chưa bằng AI lớn (xem bảng bên dưới). Tên riêng còn để pinyin (`Li Shimin`) được đối chiếu với câu gốc rồi đổi về Hán-Việt (`Lý Thế Dân`); thương hiệu quen thuộc như Xiaomi, Huawei giữ nguyên.
- **Giọng lồng:** tự chọn nam/nữ theo cao độ giọng gốc. **Từ điển phát âm** sửa cách đọc mà không đổi phụ đề (`TikTok` → `Tíc Tốc`). Chế độ `clone` bắt chước âm sắc người nói gốc (thử nghiệm).
- **Phụ đề 6 kiểu** có xem trước: `classic`, `cinema` (viền mỏng, bóng mềm như phụ đề phim), `box`, `tiktok` (nhấn từng âm tiết), `karaoke`, `pop` (chữ hoa, phóng to theo lời). Đổi được font (chỉ liệt kê font có đủ dấu tiếng Việt), cỡ, màu, viền, vị trí.
- **Ảnh bìa tự động:** chấm điểm khung hình (nét, đủ sáng, có người), xóa sub gốc, đặt tiêu đề lớn, 3 kiểu, 3 khung.
- **Kiểm tra trước khi đăng:** chấm điểm và chỉ đúng câu có vấn đề (chưa dịch, sót chữ Hán, đọc quá nhanh, chưa lồng tiếng, video chưa cập nhật, thiếu ảnh bìa...).
- **Công thức:** lưu bộ tùy chọn theo kênh để dùng lại; có sẵn TikTok dọc, Review sôi động, Phim ngắn, YouTube ngang, Chỉ phụ đề.
- **Dễ dùng cho người không biết kỹ thuật:** kéo thả file video, dán API key ngay trong Cài đặt và bấm Dịch thử, chưa có key thì tự dùng dịch offline nếu đã cài, không thì Google miễn phí, lỗi báo bằng tiếng Việt kèm cách xử lý, tiến độ tải model lần đầu, GPU tự nhận.
- **Âm thanh & hình:** tự hạ tiếng nền khi có lời, nhạc nền riêng (tự bỏ đoạn mở đầu quá nhỏ), chuẩn hóa -14 LUFS; lật, zoom, chỉnh màu, logo, watermark, tăng tốc.

## Cài đặt (Windows)

Giải nén file zip, rồi bấm đúp file **`Cai dat Studio566.cmd`**. Cần mạng Internet, lần đầu mất khoảng 5 đến 15 phút.

Bộ cài tự tìm Python 3.11 đến 3.13 (chưa có thì cài Python 3.13 qua `winget`), môi trường cũ bị hỏng thì tự tạo lại, tạo `.venv`, cài thư viện, kiểm tra ffmpeg (chưa có thì cài qua `winget`), tạo `config.yaml`, chạy `doctor`, đặt biểu tượng **Studio566** lên màn hình nền rồi mở phần mềm. Lỗi mạng giữa chừng thì chạy lại, phần đã tải không phải tải lại. Thư mục cài có dấu tiếng Việt hay dấu nháy đều được. Tạo lại biểu tượng bất cứ lúc nào bằng `.\icontent.cmd shortcut`.

Bộ cài dừng sớm, báo đúng một câu dễ hiểu, khi gặp lỗi hay gặp: bấm đúp ngay trong cửa sổ xem file zip (chưa giải nén), đặt trong Program Files (không ghi được), ổ còn dưới 4 GB, Windows 32-bit. Thư mục nằm trong OneDrive thì nhắc chuyển ra ngoài. Bản phát hành có `constraints.txt`: thư viện được cài đúng phiên bản đã chạy qua bộ test; không cài được thì tự thử lại với phiên bản mới nhất.

**Cập nhật bản mới:** giải nén đè lên đúng thư mục cũ rồi bấm đúp `Cai dat Studio566.cmd` lần nữa. Video, cấu hình, key, giọng đã thu được giữ nguyên. Lần mở đầu sau khi cập nhật, Trang chủ hiện **Có gì mới**.

### Cài xong mà không mở được: Sửa lỗi Studio566

Biểu tượng **Studio566** của bản cài .exe chạy `icontent/start.py` bằng Python kèm trong gói (`runtime\python`), không chạy thẳng `.venv`. Studio566 không lên được (thoát với lỗi, hoặc chưa có `.venv`) thì nó mở cửa sổ **Sửa lỗi Studio566**; màn hình chờ đang mở cũng tự chuyển sang trang đó. Menu Start có thêm biểu tượng **Sửa lỗi Studio566**, và trang cuối của trình cài có ô mở nó khi phần cài thư viện chưa xong.

Công cụ (`icontent/support.py`) chỉ dùng thư viện chuẩn của Python, nên chạy được cả khi thư viện của Studio566 hỏng. Nó là một trang web nhỏ ở `127.0.0.1:8766` và kiểm tra:

- lỗi lần mở gần nhất (`workspace/start-error.txt`, do `cli.py` ghi lại);
- file của Studio566 bị xóa (thường do phần mềm diệt virus);
- thư mục cài: ghi được không, còn bao nhiêu chỗ, có nằm trong OneDrive không;
- Windows, RAM, bộ chạy Visual C++ (`msvcp140.dll`);
- nạp thử thư viện trong `.venv`: lỗi "DLL load failed" được tách khỏi lỗi thiếu thư viện;
- ffmpeg, Edge/Chrome;
- cổng 8765: Studio566 cũ bị treo hay chương trình khác giữ;
- mạng tới pypi, GitHub, Hugging Face, Bilibili, Douyin, Gemini, giọng Microsoft (phân biệt lỗi chứng chỉ do phần mềm diệt virus quét HTTPS);
- cookie Douyin.

Nút sửa: **Cài lại thư viện** (chạy lại `setup.ps1`, chỉ tải phần thiếu), **Cài bộ chạy Microsoft** (bộ cài chính thức `vc_redist.x64.exe`, Windows hỏi quyền), **Tắt Studio566 bị treo**, **Làm mới cửa sổ Studio566**, **Mở Studio566**.

**Tạo gói báo lỗi** lưu `Studio566-goi-bao-loi-<ngày>.zip` ra màn hình nền. Gói gồm kết quả kiểm tra, card đồ họa, `studio.log`, nhật ký trình cài (`%TEMP%\Setup Log*.txt`), `config.yaml`, danh sách thư viện và danh sách thư mục. Key (cả giá trị thật trong `keys.json`), token, cookie, email, đường dẫn thư mục người dùng, tên người dùng và tên máy đều bị thay trước khi ghi. Trong Studio566: **Cài đặt → Sửa lỗi nhanh** có **Kiểm tra máy**, **Tạo gói báo lỗi**, **Mở công cụ Sửa lỗi**; thẻ lỗi chưa có cách sửa sẵn có nút **Tạo gói báo lỗi**. Dòng lệnh: `python -m icontent.support --check` hoặc `--report`.

Để dịch hay nhất, vào **Cài đặt → Kết nối AI**, chọn nhà cung cấp, dán API key, bấm **Dịch thử** (người mới thì làm ngay ở bước 1 của hướng dẫn lần đầu):

| Nhà cung cấp | Ghi chú |
|---|---|
| Claude | Dịch tự nhiên nhất, hiểu ngữ cảnh |
| Gemini | Có gói miễn phí |
| DeepSeek | Rẻ, giỏi tiếng Trung |
| Dịch offline | Không cần key, không cần mạng khi dịch: Cài đặt > Mô-đun AI miễn phí, tải gói Dịch offline (bộ chạy llama.cpp 38 MB + model Hy-MT2 của Tencent 1,1 GB, Apache-2.0; máy đã tải model này qua Ollama thì dùng lại). 20 câu khoảng 6 giây, cần 1,3 GB VRAM. Dịch từng câu nên **chưa có xưng hô theo ngữ cảnh**, tên món và tiếng lóng có thể sai (tên người và địa danh còn để pinyin được tự đổi về Hán-Việt), bản dịch dài hơn nên giọng đọc nhanh hơn, không gợi ý tiêu đề và hashtag. Nên đọc lại trong Studio |
| Ollama | Tự chọn model AI chạy trên máy (đi qua luồng dịch có ngữ cảnh) |
| Google dịch | Miễn phí, không cần key. Là đường dự phòng khi chưa kết nối AI: dịch sát chữ, không có xưng hô theo ngữ cảnh, và bị Google chặn tạm khi dùng nhiều |

Key lưu ở `keys.json` trên máy (không commit, chỉ gửi tới chính nhà cung cấp đó). Dùng `setx ANTHROPIC_API_KEY ...` cũng được và được ưu tiên.

Lần đầu chạy, tool tải model nhận dạng (`large-v3-turbo` khoảng 1,6 GB), VieNeu-TTS (khoảng 1 GB) và model nhận diện người nói (28 MB) về `~/.cache/huggingface`, có hiện tiến độ. Model OCR (~15MB) có sẵn trong gói `rapidocr`.

**Tách nhạc nền** để lồng tiếng sạch mà vẫn giữ BGM: có sẵn, không phải cài thêm. `separate.py` chạy mô hình UVR-MDX-NET-Inst_HQ_3 bằng ONNX Runtime (tự tải 67 MB lần đầu, kiểm SHA-256), STFT và ghép đoạn chồng 25 % viết lại bằng numpy theo đúng cách audio-separator làm. Đo trên máy này (CPU): 139 s âm thanh mất 92 s; trộn giọng nói với nhạc rồi tách lại được giọng 19,2 dB, nhạc 16,1 dB SDR. Chế độ `auto` chỉ tách video tới 10 phút, `on` luôn tách. Máy đã tự cài `audio-separator[gpu]` thì dùng nó (nhanh hơn trên GPU).

## Studio566 (giao diện)

Bấm đúp biểu tượng **Studio566** hoặc file **`Studio566.cmd`**: phần mềm mở thành cửa sổ riêng (dùng Edge hoặc Chrome có sẵn trên máy, hồ sơ riêng, không đụng tới trình duyệt của bạn). Đóng cửa sổ thì khoảng 3 phút sau phần mềm tự tắt; còn video đang xử lý, hoặc còn tab trình duyệt đang mở Studio566, thì chưa tắt. Nhật ký nằm ở `workspace/studio.log`.

Muốn xem nhật ký trên dòng lệnh, hoặc dùng trình duyệt thường: `.\icontent.cmd ui` rồi mở http://127.0.0.1:8765.

| Trang | Làm gì |
|---|---|
| **Tạo video** | Dán link, đoạn chia sẻ, hoặc kéo thả file video. Chọn công thức (có thể lưu công thức riêng) rồi bấm Bắt đầu. Hàng đợi hiện từng bước, % tiến độ, nhật ký, nút Hủy. Có chuông báo khi xong |
| **Khám phá** | Video thịnh hành, đề tài hot, tìm theo từ khóa, xem trước ngay trong trang, lưu để làm sau, chọn nhiều video rồi làm một lượt |
| **Thư viện** | Mọi thứ đã làm (video dịch, câu chuyện, quy trình, video ghép, giọng đọc), dung lượng từng món, xóa nhiều món một lần, dọn file tạm an toàn |
| **Ghép video** | Sắp thứ tự, cắt đầu cuối từng đoạn, chọn khung hình và chuyển cảnh. Bản ghép có thể đưa tiếp vào quy trình dịch và lồng tiếng |
| **Sửa ảnh** | Trình sửa ảnh nhiều lớp. Mở từ tệp, từ khung hình video (đã xóa sub), từ ảnh bìa; lưu làm ảnh bìa, vào thư viện ảnh hoặc tải về |
| **Studio** | Trái: danh sách câu. Giữa: trình phát (Xem trước / Thành phẩm / So sánh). Phải: thuộc tính (Phụ đề, Giọng, Hình ảnh, Âm thanh, Đăng bài, Kiểm tra). Dưới: timeline. Đổi tùy chọn là tự lưu cho video đó; bấm **Cập nhật video** để làm lại đúng phần đã đổi |
| **Cài đặt** | Kết nối AI dịch, tình trạng máy, tùy chọn mặc định cho video mới |
| **Giới thiệu** | Thông tin ứng dụng, lưu ý bản quyền, ghi công thư viện |

Trong Studio, tab **Dựng** gom các công cụ dựng. Kéo trên sóng âm ở timeline để chọn đoạn, bấm **Cắt đoạn** hoặc phím `Delete`; phím `I` và `O` đặt điểm đầu, điểm cuối tại kim phát; bấm đúp đoạn đã cắt để khôi phục. Di chuột vào một câu để thấy các nút đọc thử, dịch lại, thu giọng.

Trong tab **Hình**, chọn khung 9:16 hoặc 1:1 rồi cách đưa hình vào khung là **Theo mặt**: ở chế độ Xem trước sẽ thấy khung sáng là phần được giữ lại; kéo khung để đặt tay cho cảnh đang xem, bấm đúp để trả cảnh đó về cho máy. Tab **Đăng** để chọn nền tảng và tạo gói đăng bài, tab **Kiểm tra** để xem kết quả kiểm định, phím `[` và `]` để nhảy giữa các điểm chuyển cảnh.

Bấm `?` trong Studio để xem phím tắt, `Ctrl+K` ở mọi trang để mở bảng lệnh nhanh.

Cài đặt ở trang này được lưu vào `config.yaml` (bản cũ lưu ở `config.yaml.bak`). Tùy chọn riêng của từng video lưu trong `workspace/<job>/options.json`.

## Trang chủ

Mở Studio566 là vào **Trang chủ**:

- **Bạn muốn làm gì:** 8 việc thường làm (dịch và lồng tiếng video, truyện AI từ ý tưởng, video từ ảnh của tôi, kể chuyện từng cảnh, đọc văn bản, thumbnail, dựng tự do, tìm video thịnh hành). Bấm là vào thẳng, hai việc làm video từ ý tưởng, từ ảnh mở sẵn quy trình mẫu.
- **Đang chạy:** video đang dịch, đang dựng, quy trình đang chạy, kèm tiến độ.
- **Gần đây:** mọi thứ vừa làm ở một chỗ (video dịch, câu chuyện, quy trình, giọng đọc), lọc theo loại, bấm là mở lại.
- **Máy đã sẵn sàng chưa:** FFmpeg, card đồ họa, mô hình AI trên máy, AI dịch và viết kịch bản, AI vẽ ảnh, giọng của tôi, trình dựng, ổ đĩa còn trống. Mục nào thiếu có nút sửa ngay. Trạng thái key vẽ ảnh lấy từ lần vẽ thật gần nhất: key Gemini gói miễn phí có key nhưng không vẽ được ảnh nào, Studio566 nói rõ điều đó thay vì báo "sẵn sàng".

Video xong hay lỗi trong lúc bạn đang ở cửa sổ khác thì Windows hiện thông báo ở góc màn hình, bấm vào là mở đúng video (lần bấm đầu tiên trong Studio566 sẽ hỏi cho phép thông báo).

Có key Gemini mà AI dịch đang chọn (Claude, OpenAI...) chưa có key thì Studio566 tự dịch bằng Gemini, không phải dịch offline.

### Hướng dẫn lần đầu

Người mới mở Studio566 (chưa có video, câu chuyện nào) thì hướng dẫn 3 bước tự bật; ai cũng mở lại được bằng nút **Hướng dẫn 3 bước** ở Trang chủ hoặc `Ctrl+K`:

1. **Kết nối AI miễn phí:** nút mở trang lấy key Gemini, chỉ cách bấm, một ô dán key. Studio566 dịch thử một câu bằng chính key đó; đúng thì mới lưu và từ đó dịch bằng Gemini (trừ khi đang dùng Claude, DeepSeek có key), sai thì không lưu gì và nói lý do.
2. **Chuẩn bị máy:** **Tải trước** mô hình AI còn thiếu (nhận giọng, giọng đọc VieNeu, nhận diện người nói) qua hàng đợi chung, có tiến độ, hủy được, để video đầu tiên chạy ngay. Thu **Giọng của tôi**. Cho biết có card NVIDIA không.
3. **Làm video đầu tiên:** ba việc kèm cách làm một dòng: dịch video từ link, truyện AI từ ý tưởng, đọc văn bản.

Nút **Tải trước** cũng có ở mục Mô hình AI trên máy của Trang chủ.

## Thư viện

Mọi thứ đã làm ở một chỗ: video dịch, câu chuyện, quy trình, video ghép, giọng đọc. Lọc theo loại, tìm không cần gõ dấu, xếp theo mới nhất, cũ nhất, nặng nhất, tên. Mỗi mục ghi dung lượng (thư mục làm việc cộng video đã xuất) và có menu mở, xem, làm thumbnail, mở thư mục, xóa.

- **Chọn nhiều** rồi xóa một lần. Mặc định giữ video, phụ đề, ảnh bìa đã xuất trong thư mục output; muốn giải phóng hết thì đánh dấu **Xóa luôn video đã xuất**. Mục đang chạy không xóa được.
- **Dung lượng:** thanh màu cho biết ổ đĩa đang dùng cho video dịch, kể chuyện, quy trình, video đã xuất, mô hình AI.
- **Dọn dẹp** chỉ xóa thứ Studio566 tự tạo lại được, không mất video nào:
  - bản xuất thêm còn sót trong thư mục làm việc (bản cũ quên xóa sau khi đã chép sang output; chỉ xóa khi output có bản cùng cỡ);
  - bản nền cho Trình dựng (mở lại sẽ tự dựng; dự án đã mở trong Trình dựng giữ bản riêng);
  - ảnh khung hình xem trước, giọng nghe thử, file dựng dở.
  
  Video, câu chuyện đang chạy hoặc đang đóng gói thì bỏ qua. Trên máy thử, một video 2 phút 19 giây có 583 MB thư mục làm việc, dọn được khoảng 300 MB.

## Bản quyền

Studio566 **không cần kích hoạt**: không cần key, mở là dùng. Giấy phép mã nguồn: xem `LICENSE`.

## Phát hành bản mới (cho người phát triển)

```
.\icontent.cmd release            (bản cần icontent\license_pubkey.txt)
.\icontent.cmd release --free     (bản không khoá)
```

ra `dist\Studio566-<phiên bản>.zip` (khoảng 95 MB) và file `.sha256`. Gói gồm mã nguồn, giao diện, Trình dựng đã build, bộ cài, `HUONG DAN.txt` cho người dùng, và `constraints.txt` (đúng phiên bản thư viện của máy đóng gói). Không bao giờ có `keys.json`, `config.yaml`, thư mục làm việc, output, giọng đã thu. Trước khi nén, lệnh dò lại toàn bộ: file nào chứa đúng một key đang có trên máy, hay mã của Studio566 có chuỗi giống API key, là dừng. File `.cmd`, `.ps1` luôn được ghi xuống dòng kiểu Windows. Nhớ tăng `__version__` trong `icontent/__init__.py` và thêm dòng vào `CHANGES` trong `icontent/about.py` (người dùng thấy ở **Có gì mới**).

## Quy trình kéo thả

**Quy trình** (thanh bên trái): ghép các khối thành dây chuyền làm video, bấm **Chạy** một lần là ra video kèm thumbnail và thư mục đăng bài.

- **Mẫu có sẵn:** Truyện AI từ ý tưởng, Video từ ảnh của tôi (miễn phí, không cần AI), Kịch bản có sẵn để AI vẽ, Tổng đạo diễn AI (miễn phí: video quay thật cho cảnh không có nhân vật, cảnh có nhân vật thì vẽ), Truyện có chuyển động bằng clip AI (trả phí, cần bật ở mục Chi phí), hoặc Trống để tự ghép.
- **Các khối:** Ý tưởng, Kịch bản có sẵn, Ảnh của tôi; AI viết kịch bản, Chia cảnh; Ảnh mẫu nhân vật, Vẽ ảnh từng cảnh, Video nền miễn phí, AI làm clip từ ảnh; Giọng đọc (có Giọng của tôi), Nhạc nền; Dựng video; Thumbnail, Mở Trình dựng, Xuất bộ đăng bài.
- **Thao tác:** kéo khối từ bảng trái vào (bấm vào khối thì nó tự nối tiếp khối đang chọn). Nối dây bằng cách kéo từ chấm bên phải khối này sang chấm cùng màu bên trái khối kia; mỗi màu là một loại dữ liệu (chữ, ảnh, câu chuyện, video, thumbnail), sai loại thì không nối được. Bấm khối để chỉnh thiết lập, phím Delete để xóa khối hoặc dây. Kéo nền để di chuyển, lăn chuột để phóng to.
- **Khi chạy:** từng khối sáng lên, xong thì hiện kết quả ngay trên khối (ảnh cảnh, video, thumbnail, nút mở thư mục xuất). Câu chuyện tạo ra nằm trong Kể chuyện để sửa tay. Chạy lại không tốn thêm: AI không viết lại khi đầu vào không đổi, cảnh đã có ảnh không vẽ lại, video không dựng lại khi câu chuyện không đổi.
- **Khối có dấu $** gọi AI trả phí (vẽ ảnh, làm clip). Trước khi chạy, Studio566 hỏi lại kèm số ảnh, số clip ước tính và giá.
- **Xuất bộ đăng bài:** thư mục `output\dang_bai\<tên>` gồm video, `thumbnail.jpg` và `mo_ta.txt` (có video nền thì kèm tên tác giả, giấy phép, và file `nguon_video.txt`).

## Thumbnail

**Thumbnail** (thanh bên trái, thay cho trang Sửa ảnh): thiết kế ảnh thumbnail cho video vừa làm, của Kể chuyện hoặc của Studio.

- **Nền:** ảnh từng cảnh của câu chuyện, hoặc 8 khung hình đẹp nhất của video (nét, đủ sáng, có người, đã xóa sub gốc), hoặc kéo thanh để lấy khung bất kỳ, hoặc ảnh từ máy. Kéo trên ảnh để dời, lăn chuột để phóng to; chỉnh sáng, tương phản, màu, làm mờ, tối viền, tối phía dưới.
- **6 mẫu** xem trước ngay trên ảnh của video: Vàng nổi bật, Hai màu, Nhãn đỏ, Hộp đen, Tối giản, Gây chú ý. Bấm là áp, sửa tiếp được.
- **Lớp:** chữ (phông Be Vietnam Pro đủ dấu và phông của máy, viền, bóng, chuyển màu, hộp nền, xoay), mũi tên, vòng tròn, khung, emoji, logo. Kéo để dời, ô vuông ở góc để phóng to, chấm tròn phía trên để xoay. Ctrl+Z hoàn tác, Ctrl+D nhân đôi, Ctrl+S lưu.
- **AI gợi ý chữ:** AI đọc lời trong video, gợi ý 6 câu ngắn gây tò mò kèm nhãn phụ, bấm là dùng.
- **Khung 16:9, 9:16, 1:1**, có xem thử ở cỡ hiện trên điện thoại và vùng bị nút, mô tả của nền tảng che.
- **Lưu thumbnail:** JPEG dưới 2 MB, đặt cạnh video cùng tên (và làm ảnh bìa của video Studio). Bản thiết kế được lưu kèm, mở lại sửa tiếp được.

Trang Sửa ảnh cũ (miniPaint) vẫn dùng để thiết kế lớp ảnh phủ trong video, mở từ Studio.

## Kể chuyện và Đọc văn bản

**Kể chuyện** (thanh bên trái): bấm **Câu chuyện mới**, chọn một trong ba cách:

1. **AI viết từ ý tưởng:** viết một câu ý tưởng, chọn độ dài. AI viết lời dẫn tiếng Việt, chia cảnh, mô tả hình từng cảnh và lập danh sách nhân vật. Dùng AI đang kết nối trong Cài đặt (Claude, DeepSeek...), không có thì dùng Gemini nếu đã có key (gói miễn phí của Gemini viết kịch bản được). Studio566 tự chọn model Gemini Flash mới nhất đang trả lời nhanh, vì Google cho model cũ nghỉ hưu và model mới ra có lúc quá tải.
2. **Tôi có kịch bản:** dán kịch bản. Mỗi đoạn văn ít nhất một cảnh, đoạn dài chia theo câu. Có AI thì tick để AI chia cảnh và gợi ý hình, giữ nguyên lời.
3. **Từ ảnh của tôi:** chọn nhiều ảnh cùng lúc, mỗi ảnh thành một cảnh theo đúng thứ tự, thêm lời dẫn sau nếu muốn. Cảnh không có lời dài 3 giây.

Trong câu chuyện:
- **Nhân vật:** thêm tên, mô tả ngoại hình, rồi tải ảnh mẫu hoặc bấm **AI vẽ ảnh mẫu**. Bật nhân vật trong từng cảnh, Gemini sẽ vẽ cảnh đó giữ đúng nhân vật (gửi kèm tối đa 4 ảnh mẫu mỗi lần).
- **Ảnh từng cảnh:** **AI vẽ**, **Tải ảnh**, hoặc chọn từ Thư viện ảnh. Vẽ lại vẫn giữ các bản cũ, bấm vào ảnh để chọn lại bản trước. **Vẽ N ảnh còn thiếu** vẽ một lượt các cảnh chưa có ảnh.
- **Từng cảnh:** chọn chuyển động máy quay, kiểu chuyển cảnh vào cảnh đó (để trống là theo kiểu chung) và thời lượng. Cảnh có lời: thời lượng là tối thiểu, lời dài hơn thì cảnh tự dài theo, lời không bao giờ bị cắt. Cảnh im lặng: đúng thời lượng đặt, để trống là 3 giây.
- **Chuyển cảnh, mở đầu, kết thúc** (bảng bên phải): kiểu chuyển cảnh chung (mờ chồng, trượt, quét, mở tròn, cắt thẳng...) và độ dài chuyển. Bật **Cảnh mở đầu** để có tiêu đề lớn trên ảnh cảnh đầu làm mờ (trống thì lấy tên câu chuyện, thêm dòng phụ như "Tập 1"), bật **Cảnh kết thúc** để có lời kêu gọi và tên kênh trên ảnh cảnh cuối.
- **Dựng video:** đọc lời dẫn, ghép ảnh với chuyển động máy quay, chuyển cảnh, phụ đề, nhạc nền (tự nhỏ đi khi có lời). File ra trong thư mục `output`, tên bắt đầu bằng `kechuyen_`, kèm `.srt`.
- **Trình dựng:** mở câu chuyện trong trình dựng tự do để tự sắp xếp như CapCut. Mỗi cảnh là một clip riêng ở V1, lời dẫn của cảnh đó ở A1 (kéo đổi chỗ cảnh thì lời đi theo), phụ đề từng cảnh ở V2, chữ mở đầu và kết thúc là lớp chữ sửa được ở V3, nhạc nền ở A2 tự nhỏ đi khi có lời. Các cảnh nối thẳng, chuyển cảnh thêm trong trình dựng. Lần đầu Studio566 đọc lời và dựng từng cảnh (vài giây mỗi cảnh); sửa câu chuyện rồi mở lại thì cảnh nào không đổi được dùng lại. Xuất xong bấm **Gửi về Studio566**: file `kechuyen_..._dung.mp4` nằm trong `output` và hiện ở mục **Kết quả** của câu chuyện.

Nguồn vẽ ảnh, chọn ở đầu trang câu chuyện (key nhập trong Cài đặt, mục **Tạo ảnh AI**; giá theo trang của từng hãng, 11/2026):

| Nguồn | Giá | Giữ nhân vật bằng ảnh mẫu |
|---|---|---|
| Google Gemini (Nano Banana 2.1) | khoảng 0,034 USD/ảnh, không có gói miễn phí | tối đa 4 ảnh, giữ tốt nhất |
| OpenAI (ảnh của ChatGPT qua API) | theo bảng giá OpenAI, API tính tiền riêng với gói ChatGPT | có |
| Meta Muse Image | 0,01 USD/ảnh | có |
| Cloudflare Workers AI, FLUX.1 schnell | miễn phí trong hạn mức hằng ngày | không, chỉ giữ bằng mô tả |
| ChatGPT, Copilot bản miễn phí trên web | miễn phí | tự đính kèm ảnh mẫu khi dán lời nhắn |

ChatGPT và Copilot bản miễn phí không có API, Studio566 không tự động hóa trang web của họ (trái điều khoản, và hỏng mỗi khi họ đổi giao diện). Ở từng cảnh bấm **Chép lời nhắn** (đã kèm mô tả nhân vật), dán sang đó để vẽ, chép ảnh vẽ xong rồi bấm **Dán ảnh** (hoặc bấm vào cảnh và nhấn Ctrl+V). Trước khi vẽ hàng loạt, Studio566 hỏi lại kèm giá; một cảnh đang vẽ thì không bấm vẽ lần nữa được, để không bị tính tiền hai lần. Ảnh do Gemini vẽ có watermark ẩn SynthID của Google.

### Chi phí: ưu tiên miễn phí

Cài đặt, mục **Chi phí**: công tắc **Cho phép tính năng trả phí**. Tắt thì Studio566 chỉ dùng cách miễn phí: vẽ trên máy hoặc Cloudflare, video nền từ kho miễn phí, AI viết bằng Gemini gói miễn phí hoặc AI trên máy, giọng đọc trên máy. Nút và khối tính tiền (vẽ bằng Gemini, OpenAI, Meta Muse; AI làm clip) bị khóa, Quy trình báo ngay ở khối đó trước khi chạy. Chưa bật tắt lần nào: máy đã từng vẽ được bằng nguồn trả phí thì coi như bật, không thì tắt. Bật rồi vẫn vậy: **Tự chọn** luôn dùng nguồn miễn phí trước, mỗi lần tốn tiền đều báo giá và hỏi lại. Dịch bằng Claude, DeepSeek do người dùng tự dán key ở Kết nối AI, không thuộc công tắc này.

**AI viết kịch bản trên máy:** không có key AI nào mà đã tải Dịch offline và Vẽ ảnh offline thì AI viết từ ý tưởng bằng Qwen3 4B (chính là bộ đọc lời nhắn của gói Vẽ ảnh), chạy bằng bộ chạy llama.cpp của gói Dịch. AI có key bị lỗi giữa chừng (Gemini quá tải) cũng tự viết tiếp bằng AI trên máy. Đo trên máy này: kịch bản 3 đến 5 cảnh khoảng 11 giây, bật bộ chạy lần đầu 17 giây. Viết tiếng Việt tự nhiên, đôi khi mô tả hình bằng tiếng Việt (bộ vẽ trên máy tự dịch sang tiếng Anh).

Đo trên máy này, không key nào: mẫu **Tổng đạo diễn AI (miễn phí)** từ một câu ý tưởng ra video 33 giây (3 cảnh vẽ trên máy, giọng VieNeu) kèm thumbnail và bộ đăng bài trong 157 giây.

### Video nền miễn phí và clip AI

Cảnh có clip thì video dùng clip thay ảnh (cắt đầy khung, hoặc nền mờ nếu chọn giữ cả ảnh). Ảnh vẫn giữ làm ảnh bìa, cảnh mở đầu, kết thúc và thumbnail; cảnh chỉ có clip thì Studio566 lấy một khung của clip làm ảnh.

- **Video nền** (ở từng cảnh): tìm video quay thật trong kho miễn phí, rê chuột để xem, bấm để dùng. Từ khóa tiếng Anh nằm trong ô dưới mô tả hình; AI viết kịch bản đã điền sẵn, để trống thì AI (hoặc Studio566 tự rút từ mô tả hình) nghĩ giúp.
- **Tìm video nền cho mọi cảnh** (bảng bên phải): làm một lượt các cảnh chưa có clip. Cảnh có nhân vật của câu chuyện được giữ để vẽ: video quay thật không có nhân vật đó, chèn người lạ vào là lệch truyện (muốn vẫn dùng thì bấm Video nền ở cảnh đó). Chỉ nhận clip có tên hoặc nhãn chứa từ khóa (đo thật: kho trả về cả video phỏng vấn khi tìm "ruộng lúa"). Chọn clip đúng chiều khung, đủ dài, nét, trong mười kết quả liên quan nhất, không dùng một clip cho hai cảnh. Clip dài (phim tư liệu) thì bỏ phần mở đầu, viền đen sẵn trong clip được cắt bỏ. Clip ngắn hơn cảnh tới 30% thì chậm lại cho vừa, ngắn hơn nữa thì lặp lại.
- **AI làm clip:** Google Gemini Omni Flash biến ảnh cảnh thành clip chuyển động 3 đến 15 giây, đúng độ dài cảnh, giữ nhân vật như trong ảnh (cảnh chưa có ảnh thì tạo từ mô tả kèm ảnh mẫu nhân vật). Clip không lời, không chữ; tiếng của clip được tắt, lời dẫn là chính. Chọn độ nét ở bảng bên phải. Trước khi làm, Studio566 báo giá; cảnh lỗi không tính tiền.
- **Chọn lại:** bấm vào ảnh cảnh để chọn giữa các clip và ảnh đã có, hoặc **Dùng ảnh** để quay lại ảnh có máy quay chuyển động. **Nguồn clip** cho xem và chép danh sách nguồn.

| Nguồn | Giá | Ghi chú |
|---|---|---|
| Pexels | miễn phí, key miễn phí | nhiều video dọc; giấy phép Pexels cho dùng thương mại, không bắt buộc ghi nguồn |
| Pixabay | miễn phí, key miễn phí | giấy phép nội dung Pixabay như trên; kết quả tìm được lưu 24 giờ theo yêu cầu của Pixabay |
| Wikimedia Commons | miễn phí, không cần key | chỉ lấy phạm vi công cộng, CC0, CC BY (bỏ CC BY-SA, NC, ND); ít video dọc, chất lượng không đều |
| Google Gemini Omni Flash | 360p ~0,023, 720p ~0,07, 1080p ~0,104 USD/giây (11/2026) | không có gói miễn phí: key Gemini phải bật thanh toán |

Nguồn từng clip (tác giả, giấy phép, trang gốc) được ghi vào `<video>.nguon.txt` cạnh video và vào `mo_ta.txt`, `nguon_video.txt` của bộ đăng bài. Studio566 không lấy video YouTube, Douyin, TikTok làm nguồn: "video free" trên đó không phải miễn phí bản quyền. Google tắt Veo 3.1 bản thử trong Gemini API ngày 22/10/2026, Gemini Omni Flash là model video thay thế. Meta Muse Video chưa có API chính thức (11/2026); các dịch vụ "Muse API" hiện có đều tự điều khiển trang muse.ai, trái điều khoản, nên không cắm vào.

Đo trên máy này (11/2026): tìm và tải 3 clip Wikimedia mất 20 đến 90 giây (tùy độ dài file gốc), dựng 3 cảnh clip thành video 1080x1920 dài 18 giây mất 4,4 giây (NVENC). Mẫu **Video tư liệu từ kho miễn phí** từ một câu ý tưởng ra video 29 giây kèm thumbnail và bộ đăng bài trong khoảng 6 phút, phần lớn là chờ giọng Edge qua mạng. Key Gemini gói miễn phí gọi Omni thì Google từ chối ngay (chạy nền báo RESOURCE_EXHAUSTED, chạy trực tiếp báo "limit: 0 ... Free Tier"), không tính tiền.

**Đọc văn bản** (thanh bên trái): dán chữ (tối đa 30.000 ký tự một lần), chọn bộ giọng, giọng, tốc độ, bấm **Tạo giọng đọc**. File MP3 và phụ đề SRT nằm trong `output\giong_doc`. VieNeu chạy trên máy, đọc bao nhiêu cũng được; Edge cần mạng và đôi khi bị Microsoft giới hạn nếu đọc quá nhiều.

**Giọng của tôi:** bấm nút micro cạnh ô chọn giọng (Đọc văn bản, Kể chuyện, phần Giọng đọc của Studio). Bấm **Thu âm** rồi đọc to đoạn gợi ý 10 đến 20 giây ở chỗ yên tĩnh, hoặc **Tải file ghi âm** (mp3, m4a, wav, cả video). Studio566 tự lấy 8 giây có tiếng nói rõ nhất, cắt ở chỗ lặng, chỉnh âm lượng, rồi báo nếu mẫu ngắn, ồn hoặc rè. Giọng đó hiện trong nhóm **Giọng của tôi** ở mọi ô chọn giọng VieNeu: đọc văn bản, lời dẫn kể chuyện, lồng tiếng video đều dùng được, chạy hẳn trên máy. Mẫu nằm trong `assets\voices` (không đưa lên git). Chỉ dùng giọng của chính mình, hoặc của người đã đồng ý.

Đo trên máy này: VieNeu đọc một đoạn hai câu tiếng Việt bằng giọng nhại trong 7 đến 14 giây (lần đầu với mỗi mẫu lâu hơn). Độ giống với mẫu đo bằng mô hình nhận diện người nói (1 là giống hệt): khoảng 0,85 với mẫu giọng nữ tiếng Việt, khoảng 0,7 với mẫu người thật nói tiếng Trung có nhạc nền; các giọng có sẵn của VieNeu chỉ được 0,02 đến 0,58 so với cùng mẫu. Nhận dạng lời lại bằng Whisper đúng khoảng 85% số từ, ngang các giọng có sẵn.

## Trình dựng tự do

Mở từ mục **Trình dựng** trên thanh bên, nút **Trình dựng** ở Studio để dựng tiếp một video đã làm, hoặc nút **Trình dựng** trong một câu chuyện của Kể chuyện (xem phần trên). Trình dựng chạy ở cửa sổ riêng, ngay trên máy, không tải video lên đâu.

1. **Lần đầu** trình dựng hỏi một thư mục để lưu dự án: tạo một thư mục mới (ví dụ `D:\Studio566 Editor`) rồi bấm Cho phép. Trình duyệt không cho chọn thư mục hệ thống hay `AppData`. Dự án và tư liệu nằm trong thư mục đó dưới dạng file thường. Đóng hẳn rồi mở lại, trình dựng có thể hỏi lại quyền: bấm **Kết nối lại**.
2. **Video mở ra** đã xóa sub, đã cắt, đổi khung và lồng tiếng theo đúng những gì đã chỉnh trong Studio, vì Studio566 dựng một bản không ghi phụ đề (`editor_base.mp4`). Phụ đề tiếng Việt nằm trên một track riêng, đúng cỡ chữ và vị trí đã chọn. Phần hình và tiếng này đã được ghép sẵn, nên muốn sửa giọng lồng từng câu thì sửa bên Studio rồi mở lại và chọn tạo dự án mới.
3. **Dựng xong** bấm **Xuất**, rồi **Gửi về Studio566**. File nằm trong thư mục `output` với đuôi `_dung`, hiện ở Studio tab **Đăng**, phần **Bản từ trình dựng**, kiểm định được, và gói đăng bài tự kèm bản mới nhất (`video_da_dung`).

Cần Edge hoặc Chrome đời mới và card đồ họa dùng được WebGPU; trang Trình dựng tự kiểm tra và báo trước nếu máy không đủ. Các tính năng AI có sẵn trong trình dựng (chép lời, giọng đọc, tạo nhạc) tải model riêng từ Hugging Face khi bấm dùng, không ảnh hưởng tới phần dựng. Phông chữ lấy từ Google Fonts khi có mạng, không có mạng thì dùng phông của máy.

Sửa trình dựng hoặc lên bản FreeCut mới: xem `third_party/freecut/build.py` (cần git và Node 22 trở lên). Người dùng Studio566 không cần gì trong số này, bản đã build nằm sẵn ở `icontent/web/editor`.

## Dòng lệnh

```powershell
.\icontent.cmd run https://www.bilibili.com/video/BV1jcxX6CEyK
.\icontent.cmd run "7.43 复制打开抖音，看看【...】 https://v.douyin.com/xxxx/"   # dán nguyên đoạn chia sẻ
.\icontent.cmd run D:\clip.mp4 --style tiktok --aspect 9:16                    # file có sẵn
.\icontent.cmd run -f links.txt --encoder h264_nvenc                            # nhiều link, mỗi dòng 1 link
```

| Tùy chọn | Ý nghĩa |
|---|---|
| `--style tiktok` | kiểu phụ đề: `classic`, `box`, `tiktok`, `karaoke` |
| `--voice-mode per_line` | `auto` (mặc định): chọn nam/nữ theo giọng gốc. `per_line`: từng câu. `fixed`: một giọng. `clone`: bắt chước giọng gốc |
| `--vieneu-voice "Thiện Minh"` | một giọng cố định. Danh sách: `.\icontent.cmd voices` |
| `--ref-audio mau.wav` | VieNeu clone giọng từ file mẫu 3–8 giây |
| `--tts edge --voice vi-VN-NamMinhNeural` | dùng edge-tts (online; Microsoft giới hạn tần suất) |
| `--no-dub` | chỉ làm phụ đề tiếng Việt, giữ tiếng gốc |
| `--hardsub-box 0.05,0.635,0.9,0.06` | che sub gốc ở vùng x,y,rộng,cao (tỉ lệ 0–1) thay vì tự dò |
| `--no-hardsub` | không dò và không che sub gốc |
| `--watermark "@kenh"`, `--music nhac.mp3` | chữ mờ góc video; nhạc nền thêm vào |
| `--aspect 9:16`, `--flip`, `--speed 1.1` | đổi khung (nền mờ), lật ngang, tăng tốc |
| `--encoder h264_nvenc` | render bằng GPU NVIDIA |
| `--asr-model large-v3` | nhận dạng kỹ hơn một chút, model nặng gấp đôi (3 GB) |
| `--provider openai --model deepseek-chat` | dịch bằng DeepSeek (khai báo `base_url`, `api_key_env` trong config) |
| `--from tts` | chạy lại từ một bước: `download, audio, separate, hardsub, asr, translate, tts, render` |

Tùy chọn truyền trên dòng lệnh được lưu vào `options.json` của video đó, nên lần chạy sau (kể cả từ Studio) vẫn giữ.

## Sửa tay ngoài Studio

Trong `workspace/<job>/`:

| File | Sửa gì | Sau đó chạy |
|---|---|---|
| `subs.vi.srt` | câu dịch, thời gian (Subtitle Edit / Aegisub) | `run workspace\<job>`: tool tự nhận file sửa và chỉ đọc lại câu đã đổi |
| `segments.json` → `text` | câu tiếng Trung nhận dạng sai | `run workspace\<job> --from translate` |
| `segments.json` → `voice` | giọng riêng cho từng câu | `run workspace\<job>` |
| `options.json` / `config.yaml` → `edit.*` | sub, logo, khung hình... | `run workspace\<job> --from render` |

Sản phẩm phụ để kéo vào CapCut hoặc Premiere chỉnh tiếp:
- `dub.wav`: chỉ giọng lồng
- `bgm.wav`: nhạc nền, nếu đã tách
- `final.srt`
- `context.json`: tóm tắt, xưng hô, thuật ngữ

## Cách hoạt động

**Sub gốc (OCR).**
1. Lấy 16 khung hình rải đều video, OCR rồi gom các dòng chữ Hán theo vị trí dọc.
2. Dải phụ đề là dải xuất hiện ở nhiều khung và có chữ thay đổi giữa các khung. Tên kênh hay watermark đứng yên thì bị loại.
3. Sau đó ffmpeg cắt sẵn dải đó ở 4 khung/giây. OCR chỉ chạy khi chữ sáng trong dải thay đổi, nên một video 2 phút mất khoảng 20 giây.
4. Mỗi lần sub đổi được tính là một câu. Từng từ của Whisper được gán vào câu sub đang hiện, rồi ranh giới được dời ±4 từ cho khớp chữ trên màn hình (sub thường hiện sớm hoặc muộn hơn lời nói một chút).

**Dịch.**
1. Lượt phân tích đọc toàn bộ lời thoại, gồm cả chữ trên màn hình.
2. Kết quả trả về: tóm tắt, người nói, quy tắc xưng hô, bảng tên riêng, tiêu đề/caption/hashtag.
3. Lượt dịch dùng các thông tin đó trong prompt. Mỗi câu kèm giới hạn **số âm tiết tối đa** (≈ 5 âm tiết/giây × độ dài khe), để bản dịch vừa đủ đọc kịp.

**Dịch offline.** Hy-MT2 1.8B dịch từng câu bằng llama-server do Studio566 tự bật khi cần và tắt sau 2 phút rảnh (máy đã cài Ollama với model khác thì đi qua Ollama). Có chữ OCR gần giống lời nhận dạng thì dịch chữ OCR, nhờ đó sửa được lỗi đồng âm (智力 → 智利). Từ điển thuật ngữ chỉ đưa vào prompt khi câu có từ đó, câu chỉ có một từ gọi nhau (老板) thì tra bảng, và đơn vị vạn được đổi về cách nói quen (mười vạn → một trăm nghìn). Câu đọc không kịp được dịch lại theo kiểu ngắn gọn, chỉ nhận khi thật sự ngắn hơn.

**Nhận diện người nói** (trước khi dịch).
1. Lời được cắt thành các cụm theo thời gian từng từ của Whisper.
2. Mỗi cụm lấy "dấu giọng" bằng CAM++ (3D-Speaker, 28 MB, chạy CPU), rồi gom nhóm theo độ giống nhau. Nhóm quá ít lời được nhập vào nhóm gần nhất.
3. Câu có hai người được tách ở chỗ đổi người, lượt lời dưới 0,5 giây thì không tách.
4. Video đã dịch sẵn chỉ gắn nhãn, không tách câu, để giữ bản dịch đã sửa tay.

**Chọn giọng.**
- Cao độ (F0) được ước lượng bằng tự tương quan trên từng khung 40ms, cho từng người.
- Trung vị dưới 175 Hz thì dùng giọng nam, trên thì dùng giọng nữ. Mỗi người một giọng không trùng nhau (mặc định Thiện Minh, Hải Đăng, Quang Sơn... và Trúc Ly, Mai Anh, Ngọc Huyền...).
- Khi cao độ lưng chừng, tool dùng giới tính mà LLM đoán từ nội dung nếu có, không thì chọn bên gần hơn.
- Đây chỉ là đoán: giọng nam rất cao có thể bị nhận thành nữ. Giọng đặt tay cho từng người và từng câu luôn được ưu tiên. Edge TTS chỉ có một giọng Việt mỗi giới tính nên người thứ hai cùng giới sẽ dùng chung.

**Khớp timeline.** Mỗi câu có một khe thời gian, từ lúc câu bắt đầu tới lúc câu kế tiếp bắt đầu.
1. Câu nào đọc dài hơn khe × `max_speed` (1.35) sẽ được gửi lại LLM để **rút gọn**, rồi đọc lại.
2. Phần dư còn lại xử lý bằng `atempo` (giữ cao độ), tổng mức tăng tốc không vượt `hard_max_speed` (1.6).
3. Nếu vẫn tràn, câu sau được lùi lại một chút. Khoảng lặng phía sau sẽ hút lại độ trễ này.
4. Phụ đề và hiệu ứng chữ chạy theo đúng thời điểm của giọng lồng.

**Âm thanh.**
- Nền là tiếng gốc ở mức 0.15, hoặc nhạc đã tách.
- Nền đi qua `sidechaincompress` theo giọng lồng: hạ khoảng 15 dB khi nền còn giọng Trung, khoảng 9 dB khi nền chỉ là nhạc.
- Cuối cùng chuẩn hóa `loudnorm` về -14 LUFS.

## Mô-đun AI miễn phí

Cài đặt > **Mô-đun AI miễn phí (chạy trên máy)**. Mỗi gói một thẻ: Tải về (có tiến độ, tốc độ, thời gian còn lại), Dừng, Tải tiếp, Dịch thử / Vẽ thử, Xóa. Tải xong Studio566 tự chạy thử ngay trên máy đó.

| Gói | Tải về | Gồm | Dùng ở |
|---|---|---|---|
| Dịch offline | 1,1 GB | bộ chạy [llama.cpp](https://github.com/ggml-org/llama.cpp) (MIT) bản Vulkan + Hy-MT2 1.8B (Tencent, Apache-2.0) | dịch video, dự phòng khi AI lỗi, dịch tiêu đề ở Khám phá, dịch lời nhắn vẽ ảnh sang tiếng Anh |
| Giọng đọc nhiều thứ tiếng | 2,9 GB | bộ chạy [CrispASR](https://github.com/CrispStrobe/CrispASR) (MIT) bản Vulkan + VoxCPM2 Q8_0 (OpenBMB, Apache-2.0) | lồng tiếng 30 thứ tiếng, Đọc văn bản; Studio566 có sẵn 4 giọng mỗi thị trường |
| Vẽ ảnh offline | 5,3 GB | bộ chạy [stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp) (MIT) bản Vulkan + FLUX.2 klein 4B (Black Forest Labs, Apache-2.0) + Qwen3 4B đọc lời nhắn (Apache-2.0) + bộ giải mã ảnh FLUX.2 | nguồn ảnh **Vẽ trên máy (miễn phí)** ở Kể chuyện và Quy trình, nhận 2 ảnh mẫu để giữ nhân vật |

- Bản Vulkan chạy trên card NVIDIA, AMD, Intel; không có card thì tự chạy bằng CPU (chậm). Bộ chạy tự chia mô hình vừa với bộ nhớ card còn trống.
- File nằm trong thư mục `ai/` cạnh Studio566. Ghim đúng bản phát hành GitHub và commit Hugging Face, kiểm SHA-256 sau khi tải; file bị sửa hay thiếu thì coi như chưa tải. Cập nhật Studio566 không xóa thư mục này.
- Bộ chạy là tiến trình con gắn Job Object của Windows: Studio566 tắt (kể cả bị tắt ngang) thì bộ chạy tắt theo, không giữ card đồ họa. Bộ dịch tắt sau 2 phút rảnh và trước khi vẽ ảnh để nhường bộ nhớ card.
- Lời nhắn vẽ ảnh đi qua file UTF-8 (`--prompt-file`) và đường dẫn có dấu được đổi sang tên ngắn 8.3: bộ chạy đọc dòng lệnh theo bảng mã ANSI nên tiếng Việt sẽ hỏng.
- Dòng "No text..." của lời nhắn bị bỏ khi vẽ trên máy: FLUX hiểu câu khẳng định, nhắc tới chữ lại làm hiện chữ.

## Thị trường nước ngoài

Chọn **Lồng tiếng sang** ở ô dán link (hoặc Tùy chỉnh > Dịch > Thị trường, Cài đặt cho mặc định). Bảng ngôn ngữ duy nhất ở `icontent/langs.py`.

| Phần | Cách làm |
|---|---|
| Dịch | AI (Gemini, Claude...) nhận lời nhắn theo thị trường: tên riêng Trung viết pinyin không dấu (Nhật: chữ Hán; Hàn: Hangul theo âm Hán-Hàn), con số và giá đọc theo cách người nước đó. Dịch offline (Hy-MT2) hỗ trợ 21 thứ tiếng trong bảng; Google dịch tất cả |
| Độ dài câu | Đếm theo đơn vị của từng thứ tiếng: âm tiết (Việt), từ (Anh, Indonesia...), ký tự (Thái, Nhật, Hàn, Khmer, Myanmar). Tốc độ nói đo trên 56 câu VoxCPM2 của 14 thứ tiếng, lấy 90% cho an toàn |
| Giọng đọc | Tiếng Việt: VieNeu. Thứ tiếng khác: Giọng đọc nhiều thứ tiếng (Mô-đun AI) nếu đã tải, không thì giọng Microsoft qua mạng. Mỗi thị trường 4 giọng (2 nam, 2 nữ); nhiều người nói thì mỗi người một giọng |
| Phụ đề | libass tự lấy phông Windows có chữ đó: Thái, Hindi, Ả Rập (phải sang trái), Nhật, Hàn, Khmer, Myanmar hiện đúng |
| Ảnh bìa | Chữ cần ghép nét hoặc chữ vuông vẽ bằng libass (Pillow ở đây không có raqm nên vẽ sai); chữ không có dấu cách được ngắt dòng bằng tay |
| Kiểm định | Video tiếng Nhật không bị báo nhầm là "còn chữ Trung" |
| Kể chuyện, Đọc văn bản | Chọn ngôn ngữ lời dẫn; AI viết kịch bản bằng ngôn ngữ đó (mô tả hình vẫn tiếng Anh cho bộ vẽ) |

**Giữ giọng.** Chỉ tả giọng bằng lời thì mỗi câu VoxCPM2 đọc ra một người khác (CAM++ giữa các câu 0,3-0,8). Vì vậy mỗi giọng có một đoạn mẫu
(`icontent/data/voices/<id>.mp3` + `.txt`) tạo sẵn bằng mô tả giọng; mỗi giọng thử 3 seed, Whisper nghe lại chọn bản đúng lời nhất, đủ dài và khác các giọng
còn lại. Mọi câu bắt chước đúng đoạn mẫu: độ giống giữa các câu 0,68-0,93. Đoạn mẫu là giọng tổng hợp, không phải người thật.

**Ghi nhãn AI.** CrispASR luôn gắn dấu nước AI không nghe thấy và chứng chỉ C2PA. Studio566 xin bỏ câu thông báo đọc thành tiếng ở đầu mỗi câu
(giọng mẫu là giọng tổng hợp) và nhận trách nhiệm ghi nhãn: khi đăng nên bật nhãn nội dung AI của TikTok, YouTube.

## Douyin

Douyin hiện ký mọi request (a_bogus) và chặn client không có cookie, nên **yt-dlp cần cookie "tươi"** (không cần đăng nhập):

1. Mở https://www.douyin.com bằng trình duyệt, xem 1 video.
2. Dùng extension **Get cookies.txt LOCALLY** để xuất cookie (nút Export).
3. Trong Studio: bấm **Thêm cookie Douyin** ở thẻ lỗi (hoặc Cài đặt → Cookie tải video). Khi hộp hướng dẫn đang mở, bấm Export trong tiện ích là Studio566 tự nhận file mới trong thư mục Tải về (chỉ file tên có chữ `cookie`, sửa sau lúc mở hộp); không tự nhận thì kéo file vào. File là cookie của trang khác (bấm Export khi đang ở tab khác) thì Studio566 nói rõ là trang nào. Studio566 chỉ giữ cookie của douyin.com, lưu ở `cookies/douyin.txt`, rồi tự thử lại video. Dòng lệnh: `--cookies cookies.txt`, hoặc `download.cookies_file` trong `config.yaml` (file trong `cookies/` được ưu tiên).

Đọc cookie thẳng từ trình duyệt (`cookies_from_browser`) không dùng được với Edge, Chrome, Brave trên Windows: đo trên máy này, yt-dlp 2026.10.26 báo "Failed to decrypt with DPAPI" hoặc "Could not copy Chrome cookie database" (Chrome và Edge mã hóa cookie gắn với chính trình duyệt). Chỉ Firefox đọc được, nên Studio566 vẫn dùng tiện ích xuất file. Cookie hết hạn thì xuất lại. Nếu extractor Douyin của yt-dlp hỏng, bấm **Cập nhật bộ tải video** (Cài đặt → Sửa lỗi nhanh), tương đương `.\.venv\Scripts\pip install -U yt-dlp`. Cách khác là cấu hình một trình tải ngoài qua `download.external` (xem dưới), hoặc tải tay rồi chạy `run file.mp4`.

Gặp lỗi thì thẻ trong hàng đợi hiện khung **Cách khắc phục** (`icontent/fixes.py` nhận ra lỗi quen: Douyin cần cookie, link không phải trang video, máy chủ bận, mô hình hỏng hoặc lưu dạng symlink, mất mạng, ổ đầy...), kèm nút sửa ngay và nút **Chép thông tin lỗi** (đã bỏ tên người dùng Windows) để gửi tác giả.

## Nền tảng hỗ trợ

| Nền tảng | Backend | Ghi chú |
|---|---|---|
| Bilibili | yt-dlp | đã kiểm tra 1080p không cần đăng nhập; cần cookie cho 4K/hội viên |
| Douyin | yt-dlp + cookie | xem mục trên |
| Xiaohongshu, Weibo, Ixigua, Toutiao, iQiyi, Youku, AcFun, Huya, Douyu, Zhihu | yt-dlp | có extractor trong yt-dlp |
| Kuaishou | `download.external` | yt-dlp chưa có extractor → dùng [lux](https://github.com/iawia002/lux) hoặc công cụ khác |

Ví dụ khai báo lệnh ngoài (`{url}`, `{dir}`, `{cookies}` sẽ được thay vào):

```yaml
download:
  external:
    kuaishou: 'lux -o "{dir}" "{url}"'
```

## Khảo sát GitHub — vì sao thiết kế thế này

| Dự án | Làm gì | Dùng/học được gì |
|---|---|---|
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | trình tải đa nền tảng, có extractor Bilibili, Douyin, XiaoHongShu, Weibo... | backend tải chính |
| [Evil0ctal/Douyin_TikTok_Download_API](https://github.com/Evil0ctal/Douyin_TikTok_Download_API) | dịch vụ API Douyin/TikTok/Bilibili | có thể self-host bằng Docker làm backend Douyin |
| [Johnserf-Seed/f2](https://github.com/Johnserf-Seed/f2) | thư viện + CLI tải Douyin/TikTok/Weibo | thay thế khi yt-dlp hỏng |
| [jiji262/douyin-downloader](https://github.com/jiji262/douyin-downloader) | tải hàng loạt Douyin, cần cookie | README cho biết Douyin đang chặn CLI tải lẻ, khớp với kết quả test |
| [nilaoda/BBDown](https://github.com/nilaoda/BBDown) | tải Bilibili (C#), 8K/HDR/Dolby | dùng khi cần chất lượng cao nhất |
| [pyVideoTrans](https://github.com/jianchang512/pyvideotrans) | pipeline dịch + lồng tiếng đầy đủ (GPL-3) | mô hình chia bước STT → dịch → TTS → ghép |
| [VideoLingo](https://github.com/Huanshere/VideoLingo) | phụ đề chất lượng Netflix + lồng tiếng (Apache-2) | ý tưởng giới hạn độ dài bản dịch theo thời lượng, rút gọn câu |
| [KrillinAI](https://github.com/krillinai/KrillinAI) | tải → dịch → lồng tiếng → đổi khung dọc (Go) | luồng dành cho video ngắn |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | Whisper bằng CTranslate2, nhanh, nhẹ VRAM | ASR local, chạy được trên GTX 1660 6GB |
| [RapidOCR](https://github.com/RapidAI/RapidOCR) | PaddleOCR chạy bằng ONNX Runtime | đọc sub Trung in sẵn, chạy CPU |
| [VieNeu-TTS](https://github.com/pnnbao97/VieNeu-TTS) | TTS tiếng Việt local (ONNX, Apache-2.0), 25 giọng, clone giọng | engine mặc định: chạy offline, không bị giới hạn tần suất |
| [edge-tts](https://github.com/rany2/edge-tts) | TTS Microsoft miễn phí, có giọng vi-VN | engine phụ (khi test bị giới hạn tần suất sau vài trăm câu) |
| [python-audio-separator](https://github.com/nomadkaraoke/python-audio-separator) | các model UVR (MDX/Roformer) | tách giọng gốc, giữ nhạc nền |

Thay vì cài nguyên một bộ lớn như pyVideoTrans/VideoLingo (nặng, khó chỉnh theo quy trình riêng), Studio566 là một pipeline gọn. Mỗi bước là một module nhỏ trong `icontent/`, nên dễ thay engine:
- ASR: thêm FunASR / SenseVoice / Qwen3-ASR (tốt hơn Whisper với tiếng Trung).
- TTS: thêm F5-TTS, CosyVoice hoặc GPT-SoVITS.
- Tải: gọi thêm API Douyin self-host.

## Đã kiểm tra trên máy này (GTX 1660 Super 6GB)

Video thử: Bilibili BV1oU4M6dErj, 139 giây, 1080x1920, có sub Trung in sẵn.

| Bước | Kết quả |
|---|---|
| Tải | 1080x1920 H.264, không cần đăng nhập |
| Dò sub gốc (OCR, 16 khung) | thấy ở 14/16 khung, vùng y 0.62–0.71, khoảng 10 giây |
| Quét sub gốc suốt video | 109 câu sub, khoảng 23 giây |
| Nhận dạng `large-v3-turbo` (CUDA) + ghép OCR | 107 câu, mỗi câu là một lượt lời và có chữ trên màn hình. Không ghép thì chỉ có 89 câu, nhiều câu gộp lời hai người |
| Chọn giọng | giọng thuyết minh gốc có cao độ khoảng 239 Hz nên chọn giọng nữ (Trúc Ly) |
| Lồng tiếng VieNeu (CPU) | khoảng 1,5 phút cho 89 câu; tăng tốc trung bình 1.01x, tối đa 1.33x, trôi tối đa 0.02s |
| Xóa sub gốc (CPU) | khoảng 40 giây, vá 4.046/4.165 khung; khung không có sub giữ nguyên |
| Render NVENC, phụ đề TikTok, ducking | khoảng 16 giây; bitrate 5,6 Mbps (nguồn 4,2 Mbps) |
| Studio: sửa 1 câu → Cập nhật video | khoảng 20 giây, kể cả render |
| Khách mới: kéo thả file 20 giây trên trình duyệt sạch | tới hết nhận dạng 32 giây; sau khi có bản dịch: lồng tiếng 17 giây, xóa sub 7 giây, dựng 3 giây |

Giọng đọc nhiều thứ tiếng (đo 11/2026, GTX 1660 Super 6 GB, Vulkan, VoxCPM2 Q8_0 qua máy chủ CrispASR):

| Phép thử | Kết quả |
|---|---|
| 56 câu, 14 thứ tiếng, chỉ tả giọng bằng lời | 302 giây âm thanh trong 430 giây; Whisper nghe lại sai 0-5% ký tự ở hầu hết câu, 3/56 câu thêm hoặc bớt vài chữ; giọng đổi giữa các câu |
| Thư viện giọng: 21 thứ tiếng × 4 giọng × 3 seed | 19 thứ tiếng đạt (Whisper nghe lại sai 0-4%), 76 giọng, 4 MB. Khmer, Myanmar: Whisper nghe ra chữ vô nghĩa, không kiểm chứng được nên dùng giọng Microsoft |
| Video Trung 139 giây → tiếng Anh, dịch Gemini, giọng trên máy | 8,7 phút cả lượt; giọng đọc nhanh trung bình 1,09 lần, 20/89 câu phải rút gọn, tràn 0,6 giây; Whisper nghe lại khớp 93% số từ |
| Cùng video, dịch offline (Hy-MT2) → tiếng Anh / Indonesia | 15 phút; câu dài hơn khung nên đọc nhanh 1,35-1,38 lần, tràn 5-9 giây. Tiếng nước ngoài nên dịch bằng AI |
| 48 câu, 8 thứ tiếng, bắt chước đoạn mẫu | mỗi giây âm thanh 1,5-2,2 giây; sai 0-10% (phần lớn do Whisper viết số kiểu khác: "$5", "Rp50.000"); độ giống giọng giữa các câu 0,68-0,93 |

Mô-đun AI miễn phí (đo 11/2026, GTX 1660 Super 6 GB, Vulkan, bản 0.4.0):

| Phép thử | Kết quả |
|---|---|
| Dịch offline bằng bộ chạy llama.cpp, 20 câu thật | 6 giây (bật bộ chạy lần đầu 7 giây). So với Ollama cùng model, nhiệt độ 0: 5/8 câu giống hệt, 3 câu khác một chữ |
| Vẽ ảnh FLUX.2 klein 4B, 4 bước | 512x512: 10 giây; 720x1280 (ảnh dọc của video): 35 giây; 1280x720: 35 giây |
| Vẽ theo ảnh mẫu nhân vật (1 ảnh mẫu, 720x1280) | 65 giây, giữ đúng mặt, tóc, quần áo |
| Lời nhắn tiếng Việt (Kể chuyện không có AI viết lời nhắn) | dịch sang tiếng Anh bằng Hy-MT2 rồi vẽ: 38 giây, đúng nội dung |
CPU_ROW
Dịch offline và nhận diện người nói:

| Phép thử | Kết quả |
|---|---|
| Video thử ở trên, chạy trọn từ đầu bằng dịch offline | khoảng 4,7 phút; 107 câu, nghe ra 1 người (đúng là một giọng lồng cả hai vai), không tách nhầm câu nào. Giọng đọc phải nhanh hơn bản dịch tay: trung bình 1,18x, 30/107 câu trên 1,3x |
| Chất lượng dịch offline | đọc 47 câu đầu khi dịch từ lời nhận dạng: khoảng 1/5 có lỗi, gồm cả lỗi nhận dạng mà chữ OCR sửa được |
| Hội thoại 3 giọng tổng hợp, 10 câu gộp lời 2 người | tách lại đúng 20 câu, đúng người 20/20; giữ đúng 3 người khi có nhạc nền -15 dB và -8 dB |
| Giọng người thật, mẫu 4 người của sherpa-onnx | nghe ra đúng 4 người |
| Video 70 giây, 3 người, trình duyệt sạch | 68 giây, VRAM cao nhất 4,4/6 GB (Whisper và model dịch cùng nạp) |
| Đổi giọng một người → Cập nhật video | chỉ đọc lại 8 câu của người đó, 25 câu dùng lại, 15 giây |
| Đoán nam/nữ trên 14 giọng tiếng Trung biết trước | đúng 13/14 (giọng sai là giọng nam kiểu trẻ con, 286 Hz) |

Khám phá, dựng và ghép:

| Phép thử | Kết quả |
|---|---|
| Lấy danh sách thịnh hành | 650 video, tuổi trung vị 1,5 ngày, khoảng 9 giây (giãn cách để không gọi dồn dập) |
| Bấm Làm video trên một phim ngắn thịnh hành 2:18 | chạy trọn 222 giây, không lỗi |
| 17 kiểu dựng trên video mẫu (cắt giữa, cắt đầu, cắt đuôi, đổi tốc độ, đổi khung, 6 bộ màu, lớp phủ, mở đầu ảnh + kết thúc video) | độ dài lệch dưới 0,05 giây, hình sau điểm cắt đúng thời điểm gốc, ảnh dán đúng khoảng thời gian |
| Ghép 4 đoạn khác độ phân giải, tốc độ khung, có và không có tiếng, có ảnh | đúng thời lượng, đúng màu từng đoạn, 6 kiểu chuyển cảnh đều chạy |
| Xuất đoạn 10 giây thành clip | đúng 10,0 giây, kèm phụ đề riêng |
| Thu giọng cho 1 câu bằng micro giả lập của trình duyệt, tải file cho câu khác | âm thanh nằm đúng vị trí câu đó trong bản lồng |

Khung theo nhân vật, kiểm định, gợi ý đoạn (đo trên video thật, hai video ngang thịnh hành và video thử ở trên):

| Phép thử | Kết quả |
|---|---|
| Dò mặt và chuyển cảnh, video 3 phút | khoảng 5 giây dò mặt (4 khung/giây), 2-4 giây dò cảnh, chỉ dùng CPU, lần sau dùng lại kết quả đã lưu |
| Video nói chuyện cận mặt 3:15 sang 9:16 | 2,8 lần lia mỗi phút, mặt chính nằm trong khung 99,3% (bản đầu lia 10 lần mỗi phút vì đuổi theo cả cái lắc đầu) |
| Video khoa học nhiều cảnh, nhiều người 2:55 sang 9:16 | mặt chính trong khung 79,4%, cắt giữa cố định chỉ 56,2%. Cảnh nhiều người xa nhau thì một khung dọc không thể giữ hết, kéo tay để chọn |
| Video dọc 2:19 sang 16:9 | mặt chính trong khung 99,1%, cắt giữa cố định chỉ 37,5% |
| Dựng 9:16 theo nhân vật, video 3 phút bằng NVENC | khoảng 10 giây |
| Xem trước so với bản dựng, so điểm ảnh ở 5 mốc (theo nhân vật, cắt cố định, vuông, có và không có lật + phóng) | độ giống 0,85 đến 0,99, phần chênh là do nén và co giãn ảnh |
| Cài trong thư mục có dấu tiếng Việt và dấu nháy (`D:\Công cụ làm phim's\`) | dò mặt, đọc khung hình, dò cảnh, kiểm định đều chạy |
| Xuất TikTok + Shorts + Reels khi bản chính đã đúng khung | 1,1 giây, chỉ chép file |
| Kiểm định đầy đủ, video 2:19 | 13 giây. Bắt đúng logo chữ Trung còn sót trên video thử. Video cố tình có đoạn đen, đứng hình, câm, tiếng nhỏ: bắt đủ, đúng chỗ. Video lành: không báo oan |
| Làm sạch giọng, giọng thật có thêm tiếng ù và ồn | tỉ lệ giọng/nền từ 14,4 dB lên 26,4 dB, phổ phần có giọng vẫn giống gốc 0,988. Bản đầu chỉ tăng 2 dB, và bộ lọc giảm ồn làm trễ 25 ms nên đã phải bù |

Tên riêng khi dịch offline, đo trên model thật:

| Phép thử | Kết quả |
|---|---|
| 30 câu mới, không dùng lúc viết thuật toán | đúng Hán-Việt từ 3/30 lên 24/30 ở lần đo đầu, 25/30 sau khi bổ sung bảng và siết quy tắc. Phần còn lại chủ yếu do model nghe sai ngay từ đầu (`成都` ra "Đài Châu"), hậu xử lý không cứu được |
| 15 câu không có tên riêng, và 13 câu tiếng Việt thường từng bị đổi nhầm ở bản đầu (`Xin chào` với `新潮`, `Cái này` với `才`) | 0 câu bị đổi nhầm. Từ có dấu chỉ khớp khi đúng từng dấu, một âm tiết chỉ đổi khi là họ và có ngữ cảnh gọi người (`ông Zhao`, `赵总`) |
| Bảng âm đọc | 1.966 chữ viết tay. Trường `kVietnamese` của Unihan lẫn âm Nôm (`徐` ra "chờ", `强` ra "càng") nên không dùng. Chữ ngoài bảng thì giữ nguyên cả tên |

Cài như khách, trên máy này (đã có sẵn Python và ffmpeg):

| Phép thử | Kết quả |
|---|---|
| Bấm `Cai dat Studio566.cmd` trong thư mục mới `Công cụ làm phim's` | cài xong khoảng 8,5 phút khi phải tải hết, khoảng 3 phút khi pip đã có sẵn gói tải về |
| Cài trên môi trường không có lệnh `py`, chỉ có `python` | chạy được |
| Làm hỏng `.venv` (trỏ tới Python không tồn tại) rồi bấm cài lại | tự nhận ra, tạo lại, cài xong |
| Một video thật 70 giây bằng đúng bản cài đó, dịch offline, khung 9:16 theo nhân vật | chạy trọn 192 giây, 53/53 câu có dịch và có giọng, điểm kiểm định 100/100 |
| Đóng cửa sổ bằng nút X | trình duyệt thoát sau 5 giây, phần mềm tự tắt sau 192 giây |

Kể chuyện và Đọc văn bản (Gemini thay bằng máy chủ giả trả ảnh đúng dạng tài liệu, vì máy này chưa có key Gemini):

| Bước | Kết quả |
|---|---|
| Đọc văn bản 4 đoạn bằng VieNeu | 19 giây cho 15 giây lời, phụ đề khớp từng đoạn |
| Dựng câu chuyện 4 cảnh từ ảnh thật, giọng VieNeu | video 1080x1920 22 giây, mất 26 giây |
| Độ mượt chuyển động máy quay | chênh lệch chuyển động giữa hai khung liền nhau tối đa 0,19 điểm ảnh ở cỡ 270x480 (dưới 1 điểm ảnh ở 1080p), mắt không thấy giật |
| Tạo câu chuyện trên giao diện: ảnh mẫu nhân vật, vẽ các cảnh còn thiếu, thêm nhiều ảnh, dựng | chạy trọn, mỗi lần vẽ gửi kèm đúng ảnh mẫu của nhân vật có trong cảnh, gõ chữ trong lúc AI vẽ không mất con trỏ |
| Gemini báo chưa bật thanh toán, key sai, từ chối vẽ, quá tải | báo lỗi tiếng Việt rõ ràng; lỗi của key không thử lại, quá tải thì chờ rồi thử lại |

Trình dựng tự do, cùng video thử 139 giây, Edge 156:

| Bước | Kết quả |
|---|---|
| Dựng bản không phụ đề cho trình dựng | 19 giây khi bản chính còn mới; 135 giây khi phải cập nhật cả bản chính |
| Mở dự án từ Studio, thư mục làm việc thật có tên tiếng Việt trên ổ D | vào trình dựng sau 11 giây: 3 track (phụ đề, hình, tiếng), 89 câu phụ đề đúng dấu, đúng cỡ chữ và vị trí như Studio566 |
| Cắt clip, lưu, tải lại trang | phụ đề đi theo clip, mở lại vẫn đủ |
| Xuất MP4 1080x1920 trong trình duyệt (H.264 bằng card đồ họa) | 17 đến 20 giây |
| So bản xuất với bản nền | tiếng lệch 0 ms, tương quan 1,0000; hình đúng từng khung (giống nhất ở đúng thời điểm, không lệch 1 khung) |
| Gửi về Studio566 | dưới 1 giây, đã tối ưu phát ngay khi tải, gửi lần sau không ghi đè lần trước, gói đăng bài kèm `video_da_dung.mp4` |
| Hủy giữa lúc dựng bản nền rồi bấm Thử lại | báo đã hủy, không để lại file dở, thử lại chạy tiếp được |
| Build lại trình dựng từ mã gốc + bản vá | 71 giây, ra đúng bản đang dùng |

Đã thử và **không đưa vào**: khung tự chuyển theo người đang nói, dựa trên cử động miệng. Đối chiếu với nhãn người nói nghe từ tiếng trên 2 video thật, tỉ lệ khớp 55% và 67%, trong khi chọn ngẫu nhiên cũng được 65% đến 66%, tức là không hơn đoán bừa. Vì vậy cảnh có hai người xa nhau vẫn cần kéo khung bằng tay.

Về giới hạn của nền tảng: các nguồn tra cứu (11/2026) lệch nhau và nền tảng không công bố số chính thức cho bài đăng thường, nên vùng dễ bị nút che chỉ là ước lượng ở mức an toàn nhất, và chỉ cảnh báo độ dài với Shorts và Reels (3 phút). Nên xem lại trong ứng dụng trước khi đăng.

Giới hạn cần biết về Khám phá:
- API tìm kiếm và chi tiết video của Bilibili từ chối truy cập (HTTP 412), tool không tìm cách lách. Vì vậy tìm kiếm là tìm trong kho khoảng 2.000 video đã tải, kèm nút mở trang tìm kiếm của từng nền tảng.
- Bảng xếp hạng theo chuyên mục của Bilibili đã dừng cập nhật từ khoảng 3/2025. Tool vẫn dùng làm mục **Kinh điển** và ghi rõ; chuyên mục "đang hot" được chia từ danh sách thịnh hành sống.
- Douyin, Weibo, Baidu, Toutiao, Zhihu chỉ có từ khóa hot, không có danh sách video. Bấm từ khóa để mở nền tảng, chép link video rồi dán vào tool. Tải video Douyin vẫn cần cookie.

Chưa kiểm tra được:
- tạo ảnh bằng Gemini, OpenAI, Meta Muse, Cloudflare thật (máy này chưa có key nào): mới thử với máy chủ giả đúng dạng tài liệu của từng hãng. Lần đầu dùng key thật nên thử vài ảnh trước khi vẽ cả câu chuyện; AI viết kịch bản cũng cần key nên chưa chạy thật
- trình dựng trên máy yếu hoặc card đồ họa không có WebGPU (trang Trình dựng báo trước, nhưng chưa có máy như vậy để thử), và các tính năng AI có sẵn trong trình dựng (chép lời, giọng đọc, tạo nhạc)
- thu giọng bằng micro thật (mới thử micro giả lập của trình duyệt). Làm sạch giọng mới đo bằng số, chưa nghe bằng tai
- khung theo nhân vật trên phim ngắn nhiều người thay nhau nói: chọn mặt theo độ lớn và độ gần, chưa biết ai đang nói
- dịch và phân tích ngữ cảnh bằng Claude, DeepSeek (máy chưa có key). Gemini thì đã chạy thật: dịch có xưng hô, phân tích ngữ cảnh, gợi ý tiêu đề, viết kịch bản
- bộ cài trên máy hoàn toàn trắng: máy này không có Windows Sandbox, nên đã thử bằng bản zip phát hành giải nén vào thư mục mới có dấu và khoảng trắng, môi trường Python mới, không có key nào (11/2026, bản 0.2.0). Cài lần đầu 4 phút (thư viện lấy từ bộ nhớ đệm của pip), đúng phiên bản như máy đóng gói; hướng dẫn lần đầu tự bật; key sai bị từ chối mà không lưu, key thật dịch thử được trong 7 giây; mọi trang không lỗi; video Trung 30 giây đầu tiên ra video tiếng Việt trong khoảng 2 phút, kiểm định 92 điểm; giải nén bản mới đè lên rồi cài lại mất 9 giây, giữ nguyên key, cấu hình, video. Lần thử này bắt được một lỗi của faster-whisper 1.2.1 (sập khi không gióng được giờ từng từ của một đoạn, đã vá trong `asr.py`). Máy này có sẵn Python và ffmpeg nên nhánh tự cài hai thứ đó qua `winget` vẫn chưa được chạy, và mô hình AI dùng chung bộ nhớ đệm có sẵn nên chưa đo thời gian tải 2,6 GB
- số người nói trong video một người diễn nhiều giọng: clip 70 giây thử nghe ra 3 người trong khi hình chỉ có một người. Có thể đúng là diễn nhiều vai, cũng có thể tách thừa, chưa nghe bằng tai để kết luận
- Vẽ ảnh offline trên card AMD, Intel và card dưới 4 GB: máy này chỉ có GTX 1660 Super 6 GB
- nhận diện người nói trên phim ngắn nhiều nhân vật thật có nhạc nền to: mới thử giọng tổng hợp có nhạc và một mẫu giọng người thật
- Google dịch trên máy này: IP đang bị Google chặn tạm, nên chỉ kiểm tra được thông báo lỗi và đường thay thế (tự điền bản dịch trong Studio)
- Douyin (cần cookie)
- tách nhạc nền bằng UVR MDX-Net (ONNX, có sẵn)
- chất lượng nghe của chế độ `clone`

## Cấu trúc

```
icontent/
  download.py   link → source.mp4 (yt-dlp / lệnh ngoài / file local), chuẩn hóa link chia sẻ, tiến độ tải
  hardsub.py    OCR: tự dò vùng sub gốc, quét sub theo thời gian
  clean.py      xóa hẳn sub gốc: mặt nạ nét chữ theo từng câu + vá hình → clean_band.mp4
  cover.py      ảnh bìa: chấm điểm khung hình, đặt tiêu đề
  keys.py       API key lưu cục bộ, kiểm tra kết nối AI
  about.py      trang Giới thiệu, nhật ký thay đổi
  asr.py        faster-whisper (giữ model trong RAM/VRAM), thời gian từng từ, ngắt câu
  align.py      ghép từ ASR với câu sub gốc, dời ranh giới theo độ khớp chữ
  translate.py  phân tích ngữ cảnh + dịch: Claude (structured JSON) / OpenAI-compatible / offline / Google; rút gọn
  trends.py     khám phá: video thịnh hành, đề tài hot, chấm điểm, tìm kiếm, dịch tiêu đề, cache
  editing.py    dựng không phá gốc: đoạn cắt, ánh xạ thời gian, lớp phủ, bộ màu, gợi ý khoảng lặng, làm sạch giọng
  vision.py     dò chuyển cảnh, dò mặt (YuNet), đường đi của khung cắt khi đổi tỉ lệ khung hình
  highlights.py gợi ý đoạn hay từ độ to, mật độ lời, nhịp cảnh, câu mở đầu; tìm chỗ nhạc nền thật sự vào
  qc.py         kiểm định thành phẩm, đo trên file đã xuất
  hanviet.py    đổi tên riêng còn để pinyin sang Hán-Việt, đối chiếu với câu gốc
  profiles.py   hồ sơ xuất theo nền tảng, vùng dễ bị nút che
  bundle.py     gói đăng bài
  speech.py     đọc văn bản: chia đoạn, đọc từng đoạn, ghép, phụ đề khớp từng đoạn
  myvoice.py    giọng của tôi: mẫu giọng tự thu, chọn 8 giây rõ nhất, VieNeu đọc bằng giọng đó
  workflow.py   quy trình kéo thả: các khối, kiểm tra dây, chạy lần lượt, dùng lại phần đã làm, hỏi phí trước khi vẽ ảnh
  thumbs.py     thumbnail: nguồn video, ảnh nền đề cử, lưu cạnh video, AI gợi ý chữ, thumbnail tự động
  library.py    thư viện: dung lượng từng món, file đã xuất của từng món, dọn file tạm tạo lại được
  onboard.py    bắt đầu lần đầu: kết nối Gemini một ô dán key, tải trước mô hình AI qua hàng đợi
  release.py    đóng gói bản phát hành: zip sạch dữ liệu riêng, dò key, khóa phiên bản thư viện, nhúng khoá công khai bản quyền
  license.py    bản quyền: mã máy, kiểm key Ed25519 do iKey_bot cấp, hạn dùng, khoá app khi chưa kích hoạt (_ed25519.py: Ed25519 thuần Python)
  imagegen.py   tạo ảnh (Gemini, OpenAI, Meta Muse, Cloudflare), ảnh mẫu nhân vật, lỗi dễ hiểu
  story.py      video kể chuyện: lưu câu chuyện, chia cảnh, AI viết kịch bản, vẽ ảnh, lời dẫn, chuyển cảnh, mở đầu, kết thúc, dựng có chuyển động máy quay, gói từng cảnh cho trình dựng
  editor.py     trình dựng tự do: phục vụ FreeCut ở editor.localhost, bản không phụ đề, nhận video gửi về
  appwin.py     cửa sổ riêng, chạy không cần dòng lệnh, tự tắt, biểu tượng màn hình nền
  montage.py    ghép nhiều video và ảnh, chuyển cảnh
  langs.py      thị trường: tên, đơn vị đếm độ dài câu, tốc độ nói, mã Google, tên cho Hy-MT2, giọng Microsoft, câu nghe thử
  voxtts.py     giọng đọc nhiều thứ tiếng: máy chủ CrispASR (VoxCPM2), thư viện giọng mẫu, đọc từng câu, giữ giọng
  localai.py    Mô-đun AI miễn phí: tải (tiếp tục được, kiểm SHA-256), bộ chạy llama.cpp / stable-diffusion.cpp (Vulkan), vẽ ảnh, dịch lời nhắn sang tiếng Anh
  offline.py    dịch offline: Hy-MT2 qua bộ chạy của Studio566 (hoặc Ollama đã cài), mẫu lời nhắn, sửa kết quả
  speakers.py   nhận diện người nói: dấu giọng + gom nhóm, tách câu gộp 2 người, chia giọng từng người
  voice.py      danh sách giọng (giới tính), đo cao độ → nam/nữ, lấy mẫu clone
  tts.py        VieNeu / edge-tts, cắt khoảng lặng, co giãn, đặt vào timeline → dub.wav
  separate.py   tách nhạc nền UVR MDX-Net bằng ONNX (audio-separator nếu đã cài)
  render.py     ffmpeg: ghép dải đã xóa sub / làm mờ, lật, zoom, màu, đổi khung, burn ASS, watermark, logo, ducking, nhạc, loudnorm
  models.py     Segment, SRT, ASS (classic / box / tiktok / karaoke / pop)
  pipeline.py   điều phối + cache + options.json + nhận file sửa tay
  web/          Studio566: server.py (FastAPI, hàng đợi), content_api.py (Kể chuyện, Đọc văn bản) + static/ (giao diện: js/ theo module, không framework, chạy offline) + editor/ (FreeCut đã build)
  data/         model dò mặt YuNet (232 KB), bảng Hán-Việt, giấy phép
  cli.py        lệnh ui / run / download / voices / doctor / shortcut / release / license
third_party/freecut/  build.py + icontent.patch: dựng lại trình dựng từ mã gốc FreeCut
tests/          test_basic.py, test_studio.py, test_features.py  (chạy: .venv\Scripts\python tests\test_features.py)
```

## Phần mềm bên thứ ba đi kèm

- [miniPaint](https://github.com/viliusle/miniPaint) v4.14.3 của ViliusL, giấy phép MIT: trình sửa ảnh, nằm ở `icontent/web/static/vendor/minipaint/` kèm giấy phép. Dùng nguyên bản dựng sẵn của tác giả, Studio566 chỉ thêm lớp giao diện tiếng Việt và màu sắc ở bên ngoài.
- [FreeCut](https://github.com/walterlow/freecut) của walterlow, giấy phép MIT: trình dựng tự do, bản đã build nằm ở `icontent/web/editor/`. Các chỗ Studio566 sửa (tiếng Việt, cầu nối, bỏ trang giới thiệu) ghi đủ trong `third_party/freecut/icontent.patch`. Giấy phép của FreeCut và các thư viện nằm trong bản build ở `icontent/web/editor/THIRD_PARTY_NOTICES.txt`, không có thư viện GPL hay AGPL, bước build tự dừng nếu gặp.
- [YuNet](https://huggingface.co/opencv/face_detection_yunet) của Shiqi Yu (qua OpenCV), giấy phép MIT: model dò khuôn mặt, nằm ở `icontent/data/` kèm giấy phép.
- Be Vietnam Pro, JetBrains Mono: phông chữ giấy phép SIL OFL.
- Mô-đun AI miễn phí **không đóng gói sẵn**, khách tự tải khi cần (xem [Mô-đun AI miễn phí](#mô-đun-ai-miễn-phí)): llama.cpp, stable-diffusion.cpp, CrispASR (MIT, giấy phép nằm trong thư mục bộ chạy sau khi tải), Hy-MT2 1.8B, FLUX.2 klein 4B, Qwen3 4B, VoxCPM2 (Apache-2.0).
- Thư viện giọng mẫu `icontent/data/voices/`: do Studio566 tạo bằng VoxCPM2 (đầu ra của mô hình Apache-2.0), giọng tổng hợp, không phải người thật.
- Không dùng OmniVoice: mô hình đã huấn luyện theo giấy phép CC-BY-NC (cấm dùng thương mại) do dữ liệu huấn luyện, khách làm video kiếm tiền.
- [Unihan](https://www.unicode.org/charts/unihan.html) của Unicode, giấy phép Unicode License V3: pinyin trong `icontent/data/hanviet.tsv`, kèm giấy phép. Âm Hán-Việt trong file đó do Studio566 tự viết.

### Vì sao không nhúng OpenMontage

Đã đọc kỹ [OpenMontage](https://github.com/calesthio/OpenMontage) (hệ thống sản xuất video chạy bằng AI coding assistant) và học nhiều ý tưởng hay: khung theo khuôn mặt, kiểm định sau khi dựng, nhiều bản theo nền tảng, gói đăng bài. Nhưng Studio566 **tự viết lại các kỹ thuật này, không dùng dòng mã nào của dự án đó**, vì:

- OpenMontage dùng giấy phép **AGPL-3.0**: nhúng mã vào rồi phát cho người dùng thì toàn bộ Studio566 phải theo AGPL và công khai mã nguồn. Đây là quyết định của tác giả Studio566, không nên xảy ra ngầm.
- Nó không có phần điều phối bằng code: cần một AI coding assistant (Claude Code, Cursor...) cầm lái, người dùng Studio566 không có.
- Phần dựng hình dùng Remotion (Node, dùng thương mại miễn phí chỉ cho cá nhân và công ty tới 3 người) và phần tạo video AI cần key trả phí.

Nếu dùng riêng cho mình thì vẫn có thể clone OpenMontage và mở trong Claude Code để làm video giải thích, hoạt hình: đó là việc Studio566 không làm, và hai bên không ảnh hưởng nhau.

## Lưu ý bản quyền

Video trên Douyin/Bilibili thuộc về người tạo. Hãy dùng tool cho nội dung bạn có quyền (video của chính bạn, nội dung được cấp phép), hoặc cho mục đích học tập/nghiên cứu. Đăng lại video của người khác khi chưa được phép có thể vi phạm bản quyền và điều khoản của các nền tảng.
