"""Thông tin giới thiệu Studio566 và nhật ký thay đổi (hiện một lần sau khi cập nhật)."""
from __future__ import annotations

# hiện một lần sau khi cập nhật (Trang chủ, js/onboard.js): mới nhất trước, viết cho người dùng, không phải cho lập trình viên
CHANGES = [
    {"version": "1.1.1", "date": "11/2026", "items": [
        "Trước khi dùng AI qua MCP, app hiện thông báo và chờ bạn bấm Bắt đầu, không tự hết giờ khi bạn chưa kịp mở AI để nhắn. Bấm Bỏ qua để dịch bằng cách dự phòng. Mỗi video chỉ bấm một lần.",
        "Ô Nhân vật có lời (phần Dịch): ghi tên và là ai (VD Bà (nữ), Tang Bưu (chó, giọng nam)) để AI chia câu cho đúng nhân vật. AI trả thừa nhân vật thì app gộp về đúng số đã chọn.",
        "Dịch hay hơn: mỗi câu kèm tên người nói và các câu tiếp theo, AI được dặn dịch theo ý và theo cảnh, không dịch sát chữ, không cắt câu thành mẩu cụt.",
        "Soát lại bản dịch: dịch xong, AI đọc lại cả bản dịch một lượt để sửa câu sai nghĩa, xưng hô lệch (bật sẵn, tắt được trong phần Dịch).",
        "Sửa câu bị cắt đôi và đọc sớm khi một chữ bị nghe kéo dài bất thường.",
    ]},
    {"version": "1.1.0", "date": "11/2026", "items": [
        "Chia nhân vật bằng AI đọc kịch bản: khi bật Phân tích video trước khi dịch, AI đọc cả lời thoại và cho biết từng câu là của nhân vật nào (Bà, bé, ông chủ quán...). Mỗi nhân vật có tên thật và đúng một giọng xuyên suốt video, không còn đổi giọng giữa chừng hay gộp nhầm hai nhân vật giọng giống nhau.",
        "Nghe giọng gốc vẫn dùng làm gợi ý phụ, và vẫn là cách chia khi dịch bằng Google hoặc dịch offline.",
        "Sửa tay: trong Studio, ô người nói ở mỗi câu hiện tên nhân vật, chọn lại là giọng đổi theo.",
    ]},
    {"version": "1.0.2", "date": "11/2026", "items": [
        "Hết lồng tiếng và phụ đề chạy trước hình: chữ đầu câu bị nghe sai giờ (sớm cả chục giây) được đưa về đúng chỗ.",
        "Hết câu cụt một hai chữ vô nghĩa: mẩu lời lẻ được nhập vào đúng câu, logo trên video không còn cắt ngang câu.",
        "Giọng nhân vật ổn định hơn: câu ngắn, câu la hét, câu chìm trong nhạc giữ giọng của câu bên cạnh thay vì nhảy sang giọng khác. Có thêm ô Số nhân vật có lời (Giọng đọc): chọn đúng số nhân vật thì mỗi nhân vật đúng một giọng.",
        "Nhân vật nam không còn bị lồng giọng nữ ở phim nhiều cảnh la hét (lấy từ iContent 0.6.3).",
        "Video làm bằng bản cũ: thêm lại từ Video mới là app tự ghép câu lại theo cách mới, không phải xóa gì.",
    ]},
    {"version": "1.0.1", "date": "11/2026", "items": [
        "Không còn biến logo kênh in trên video (chữ ngắn hiện lặp lại nhiều lần) thành câu thoại.",
        "Câu app chưa chắc chắn được tô vàng trong Studio: chỉ có chữ trên màn hình mà không nghe ra tiếng, hoặc chỉ nghe ra tiếng mà không có phụ đề. Bấm Cần xem để lọc, soát xong bấm vào nhãn vàng để bỏ đánh dấu.",
    ]},
    {"version": "1.0.0", "date": "11/2026", "items": [
        "Dịch video chia 3 bước rõ ràng: chọn video, chọn kiểu, bắt đầu. Tùy chọn chi tiết gập vào Tùy chỉnh nâng cao.",
        "Studio có chế độ Đơn giản (mặc định): video bên trái, danh sách câu bên phải, chữ to dễ sửa. Chuyển sang Chuyên nghiệp để có đủ timeline.",
        "Thẻ video đang làm báo ngay điều cần biết: đang chờ AI qua MCP (kèm nút chép câu nhắn), đoạn nghi thiếu lời do nhạc to, câu chưa đọc được, câu đọc chậm hơn hình.",
    ]},
    {"version": "0.9.1", "date": "11/2026", "items": [
        "AI qua MCP dùng cổng chung của Studio566: chỉ cần bấm Kết nối, không cần tài khoản hay API token Cloudflare.",
        "Mỗi máy một kênh riêng có mật khẩu riêng; đổi địa chỉ hoặc ngắt kết nối bất cứ lúc nào.",
        "Nhận kết quả từ AI nhanh hơn và ít lượt gọi hơn (cổng giữ kết nối chờ sẵn).",
    ]},
    {"version": "0.9.0", "date": "11/2026", "items": [
        "AI qua MCP: dùng Claude, ChatGPT hoặc Grok bạn đang trả phí để dịch, rút gọn câu, phân tích video, viết kịch bản. Không cần API key.",
        "Cổng MCP đặt trên Cloudflare (tài khoản của bạn, gói miễn phí): dán API token là Studio566 tự cài. Máy bạn không mở cổng nào ra Internet.",
        "Chờ AI nhận việc 5 phút (chỉnh được), quá thời gian thì tự dịch bằng dịch offline hoặc Google.",
        "Bật tắt được bước phân tích video trước khi dịch (xưng hô, tiêu đề, hashtag).",
    ]},
    {"version": "0.8.0", "date": "11/2026", "items": [
        "Giao diện mới: màu cam san hô theo logo, chữ to và dễ đọc hơn, nút bo tròn.",
        "Thanh bên chia nhóm Tạo video, Công cụ, Của tôi, tên mục dễ hiểu hơn. Cửa sổ hẹp thì tự thu gọn còn biểu tượng.",
        "Trang chủ có ô dán link to: dán link, bấm Bắt đầu là sang ngay bước dịch.",
    ]},
    {"version": "0.7.0", "date": "11/2026", "items": [
        "Tên mới: Studio566, có logo mới.",
        "Không còn mất lời thoại ở đoạn nhạc nền to: đoạn dài chưa nghe ra lời thì máy tự nghe lại trên tiếng gốc; video có sub Trung in sẵn thì lấy chữ sub làm câu.",
        "Câu đọc bị lỗi được đọc lại tự động tối đa 2 lần, không còn chỗ có phụ đề mà im tiếng.",
        "Câu dịch quá dài được rút gọn thêm một lần nữa, giọng đọc ít bị lệch dần so với hình. Nhật ký ghi rõ các mốc còn lệch để sửa tay.",
        "Câu cụt như \"Con…\", \"Hả?!\" được làm sạch trước khi đọc nên đọc tự nhiên hơn, ít lỗi hơn.",
        "Bộ cài mới có thanh tiến trình, không còn cửa sổ đen khi tải thư viện.",
        "Tự báo khi có bản Studio566 mới và tự cập nhật bộ tải video.",
    ]},
    {"version": "0.6.2", "date": "11/2026", "items": [
        "Tách nhạc nền chạy được ngay, không phải cài thêm gì: chọn Tách nhạc nền: Bật không còn báo lỗi chưa cài audio-separator. Studio566 tự tải bộ tách UVR MDX-Net (67 MB, chỉ lần đầu) và chạy trên máy, giọng gốc được bỏ sạch, nhạc nền giữ nguyên dưới giọng lồng.",
        "Tách nhạc nền Tự động: tách cho video tới 10 phút (mất khoảng 0,6–0,8 lần thời lượng video). Video dài hơn thì bỏ qua cho nhanh, muốn tách thì chọn Bật.",
        "Cookie Douyin hết hạn: thông báo lỗi có ngay nút Làm mới cookie. Bấm là Studio566 mở douyin.com, khách chỉ cần lướt 1–2 video rồi bấm Export trong tiện ích; Studio566 tự nhận file và tự thử lại video.",
    ]},
    {"version": "0.6.1", "date": "11/2026", "items": [
        "Cài xong mà Studio566 không mở được: biểu tượng Studio566 tự mở cửa sổ Sửa lỗi, nói rõ vì sao (thư viện cài chưa xong, thiếu ffmpeg, thiếu bộ chạy Microsoft, cổng bị chiếm, phần mềm diệt virus chặn, mạng bị chặn...) và có nút sửa ngay.",
        "Có biểu tượng Sửa lỗi Studio566 trong menu Start: mở được cả khi Studio566 hỏng hẳn. Kiểm tra máy, cài lại thư viện (chỉ tải phần thiếu), tắt Studio566 bị treo, làm mới cửa sổ Studio566.",
        "Tạo gói báo lỗi: một nút là có file zip trên màn hình nền gồm nhật ký và kết quả kiểm tra máy để gửi người hỗ trợ. Đã tự bỏ key, cookie, email, tên người dùng và tên máy.",
        "Cài đặt có thêm Kiểm tra máy và Tạo gói báo lỗi; thẻ lỗi chưa có cách sửa sẵn cũng có nút Tạo gói báo lỗi.",
        "Cookie Douyin dễ hơn: bấm Export trong tiện ích là Studio566 tự nhận file trong thư mục Tải về rồi tự thử lại video, không phải kéo thả. Xuất nhầm trang khác (đang đứng ở tab khác) thì báo rõ.",
        "Cookie Douyin đã nạp mà vẫn lỗi: hướng dẫn xử lý ô kéo xác minh, hộp đăng nhập, và có nút Cập nhật bộ tải video ngay trên thẻ lỗi.",
    ]},
    {"version": "0.6.0", "date": "11/2026", "items": [
        "Ưu tiên miễn phí: mục Chi phí mới trong Cài đặt. Đang tắt (mặc định) thì Studio566 chỉ dùng cách miễn phí, nút tính tiền bị khóa, không lo bấm nhầm mất tiền. Muốn dùng bản trả phí thì bật, mỗi lần tốn tiền vẫn báo giá và hỏi trước.",
        "AI viết kịch bản ngay trên máy, không cần key: có Mô-đun AI miễn phí (Dịch offline và Vẽ ảnh offline) là bấm AI viết từ ý tưởng được. Gemini quá tải giữa chừng thì tự viết tiếp bằng AI trên máy.",
        "Nguồn ảnh Tự chọn dùng Vẽ trên máy và Cloudflare miễn phí trước, nguồn trả phí sau.",
        "Kể chuyện có video nền quay thật, miễn phí: bấm Tìm video nền cho mọi cảnh, Studio566 tự nghĩ từ khóa, tìm trong kho Pexels, Pixabay, Wikimedia Commons, chọn clip đúng chủ đề, đúng khung, đủ dài, không trùng nhau rồi tải về. Cảnh có nhân vật của bạn được giữ để vẽ (không chèn người lạ). Muốn tự chọn thì bấm Video nền ở từng cảnh.",
        "Chỉ lấy video có giấy phép dùng thương mại. Nguồn từng clip được ghi vào file .nguon.txt cạnh video và vào mô tả của bộ đăng bài (tác giả, giấy phép), làm bằng chứng khi bị khiếu nại.",
        "AI làm clip: biến ảnh từng cảnh thành clip chuyển động 3 đến 15 giây bằng Google Gemini Omni, giữ đúng nhân vật đã vẽ. Cần key Gemini đã bật thanh toán, khoảng 0,07 USD mỗi giây ở 720p; Studio566 báo giá và hỏi trước khi làm.",
        "Quy trình có 2 mẫu mới: Tổng đạo diễn AI (miễn phí: ý tưởng → kịch bản → video quay thật cho cảnh không người → vẽ cảnh có nhân vật → giọng → nhạc → dựng → đăng) và Truyện có chuyển động bằng clip AI (trả phí, tùy chọn).",
        "Wikimedia Commons dùng được ngay không cần key. Key Pexels, Pixabay miễn phí (đăng ký một phút) cho nhiều video dọc đẹp hơn: dán ở Cài đặt, mục Video nền miễn phí và clip AI.",
    ]},
    {"version": "0.5.0", "date": "11/2026", "items": [
        "Làm video cho thị trường nước ngoài: chọn Lồng tiếng sang ngay ở ô dán link. 22 thứ tiếng: Anh, Indonesia, Thái, Philippines, Malaysia, Tây Ban Nha, Bồ Đào Nha, Nhật, Hàn, Hindi, Ả Rập, Pháp, Đức, Nga, Ý, Thổ Nhĩ Kỳ...",
        "Giọng đọc nhiều thứ tiếng chạy trên máy (Mô-đun AI miễn phí, 2,9 GB): mỗi thứ tiếng 4 giọng nam, nữ, giọng giữ nguyên suốt video, không cần mạng, không bị chặn. Chưa tải thì dùng giọng Microsoft qua mạng.",
        "Dịch theo thị trường: độ dài câu tính theo tốc độ nói của từng thứ tiếng, tên riêng và con số viết theo cách người nước đó đọc; tiêu đề, hashtag cũng theo ngôn ngữ đó. Dịch offline hỗ trợ đủ các thứ tiếng này.",
        "Phụ đề và ảnh bìa hiện đúng chữ Thái, Ả Rập, Hindi, Nhật, Hàn, Khmer, Myanmar (chữ Ả Rập đúng chiều phải sang trái).",
        "Kể chuyện, Đọc văn bản: chọn ngôn ngữ lời dẫn; AI viết kịch bản thẳng bằng ngôn ngữ đó. Giọng của tôi cũng đọc được thứ tiếng khác.",
    ]},
    {"version": "0.4.0", "date": "11/2026", "items": [
        "Mô-đun AI miễn phí (Cài đặt): bấm Tải là có Dịch offline và Vẽ ảnh offline chạy ngay trên máy, không cần key, không cần mạng, không tốn tiền, không phải cài Ollama.",
        "Gemini quá tải, hết lượt trong ngày hay sai key giữa chừng: Studio566 tự dịch tiếp các câu còn lại bằng Dịch offline (rồi Google), video không còn dừng ở bước dịch.",
        "Kể chuyện, Quy trình: thêm nguồn ảnh Vẽ trên máy (miễn phí, không giới hạn số ảnh), giữ nhân vật giống nhau bằng 2 ảnh mẫu.",
        "Tải mô-đun có thanh tiến độ, tốc độ, thời gian còn lại; rớt mạng thì bấm Tải tiếp, không tải lại từ đầu. Tải xong tự chạy thử ngay trên máy.",
        "Đã dùng dịch offline qua Ollama ở bản cũ: Studio566 dùng lại mô hình đó, không phải tải lại 1,1 GB.",
    ]},
    {"version": "0.3.2", "date": "11/2026", "items": [
        "Hết lỗi \"Không kết nối được Studio566\" khi để cửa sổ lâu, thu nhỏ, hoặc lúc đang ở màn Kích hoạt chờ key: Studio566 không còn tự tắt nhầm khi cửa sổ vẫn mở.",
        "Studio566 bị dừng bất thường (thiếu RAM, phần mềm khác tắt ngang) thì tự chạy lại, cửa sổ tự kết nối lại và tải lại trang.",
        "Gemini quá tải không còn làm video đứng 5-6 phút ở bước Phân tích: quá hơn một phút thì bỏ qua bước phụ này và dịch luôn.",
        "Gặp lỗi là có khung Cách khắc phục: nói rõ vì sao, làm gì, kèm nút sửa ngay (thêm cookie, tải lại mô hình, cập nhật bộ tải video, thử lại).",
        "Douyin: nạp cookie bằng cách kéo thả file theo 4 bước có hướng dẫn, không phải sửa file cấu hình. Nạp xong tự thử lại video.",
        "Link Bilibili có /vi/, /en/ hoặc mã theo dõi (?trackid=) giờ tải được bình thường.",
        "Sửa lỗi giọng đọc VieNeu không chạy trên máy bật Developer Mode (báo ONNXRuntimeError, External data path).",
        "Bilibili báo bận (lỗi 503) thì tự chờ rồi lấy link tải mới, thử lại vài lần trước khi báo lỗi.",
        "Video lỗi ngay bước tải giờ cũng có nút Thử lại; nút Chép thông tin lỗi để gửi người hỗ trợ (đã bỏ tên máy).",
    ]},
    {"version": "0.3.1", "date": "11/2026", "items": [
        "Có file cài đặt .exe: bấm đúp, bấm Tiếp là xong; không phải giải nén, không phải cài Python.",
        "Cập nhật bản mới bằng file cài: tự tắt Studio566 đang mở, cài đè đúng thư mục cũ, giữ nguyên video và cấu hình.",
        "Gỡ cài đặt trong Cài đặt Windows > Ứng dụng, có hỏi giữ lại video và cấu hình hay không.",
        "Máy không có winget vẫn tự tải được ffmpeg.",
    ]},
    {"version": "0.3.0", "date": "11/2026", "items": [
        "Không còn lỗi dừng ở bước nhận giọng với một số video (thư viện nhận giọng không gióng được giờ từng từ ở cuối video).",
        "Bỏ câu \"cảm ơn đã xem\" mà máy tự nghe nhầm sau khi video đã hết tiếng.",
        "Dán nhầm key AI thì báo rõ key không đúng và cách chép lại, thay vì mã lỗi khó hiểu.",
    ]},
    {"version": "0.2.0", "date": "11/2026", "items": [
        "Trang chủ mới: chọn việc cần làm, xem việc đang chạy, mọi thứ vừa làm và máy đã sẵn sàng chưa.",
        "Quy trình kéo thả: nối các khối ý tưởng, viết, vẽ, đọc, dựng, thumbnail thành video chỉ với một nút Chạy.",
        "Thumbnail: trình thiết kế ảnh bìa có mẫu sẵn, chữ viền, mũi tên, AI gợi ý chữ, xem thử cỡ điện thoại.",
        "Giọng của tôi: thu 10 giây giọng của bạn để đọc văn bản, kể chuyện bằng chính giọng đó.",
        "Kể chuyện: chỉnh thời lượng từng cảnh, chuyển cảnh, mở đầu và kết thúc; mở câu chuyện trong Trình dựng.",
        "Thư viện gộp: mọi sản phẩm một chỗ, biết món nào nặng, xóa nhiều món một lần, dọn file tạm an toàn.",
        "Có key Gemini là tự dịch bằng Gemini; tự đổi sang model mới khi Google ngừng model cũ.",
        "Báo ở góc màn hình khi video xong hoặc lỗi.",
    ]},
]


def about() -> dict:
    return {"changes": CHANGES}


def cli_line() -> str:
    return "Studio566: dịch và lồng tiếng video, chạy ngay trên máy của bạn."
