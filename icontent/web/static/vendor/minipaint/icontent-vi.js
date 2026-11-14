/* Lớp giao diện tiếng Việt của iContent cho miniPaint. Không sửa mã của miniPaint: chỉ đổi chữ trên giao diện khi nó hiện ra.
 * Không đụng vào <option> không có value, vì khi đó chữ hiển thị chính là giá trị miniPaint đọc lại. */
(function () {
  const VI = {
    // ---- menu chính
    File: 'Tệp', Edit: 'Sửa', Image: 'Ảnh', Layer: 'Lớp', Layers: 'Lớp', Effects: 'Hiệu ứng', Tools: 'Công cụ', View: 'Xem', Help: 'Trợ giúp',
    New: 'Tạo mới', Open: 'Mở', 'Open File': 'Mở tệp', 'Open Directory': 'Mở thư mục', 'Open from Webcam': 'Mở từ webcam', 'Open URL': 'Mở từ đường dẫn', 'Open Data URL': 'Mở từ Data URL',
    'Open Test Template': 'Mở mẫu thử', 'Search Images': 'Tìm ảnh', Export: 'Xuất', 'Save As': 'Lưu thành', 'Save As Data URL': 'Lưu thành Data URL', Print: 'In', 'Quick Save': 'Lưu nhanh', 'Quick Load': 'Mở bản lưu nhanh',
    Undo: 'Hoàn tác', Redo: 'Làm lại', Cut: 'Cắt', Copy: 'Chép', Paste: 'Dán', Delete: 'Xóa', 'Copy to Clipboard': 'Chép vào bộ nhớ', 'Copy Selection': 'Chép vùng chọn', 'Delete Selection': 'Xóa vùng chọn', 'Clear Selection': 'Bỏ vùng chọn', 'Select All': 'Chọn tất cả', 'New from Selection': 'Tạo lớp từ vùng chọn',
    Information: 'Thông tin', 'Layer details': 'Chi tiết lớp', Preview: 'Xem trước', Colors: 'Màu', Settings: 'Cài đặt', 'Keyboard Shortcuts': 'Phím tắt', About: 'Giới thiệu', 'Report Issues': 'Báo lỗi', Language: 'Ngôn ngữ', External: 'Dịch vụ ngoài',
    // ---- ảnh
    'Canvas Size': 'Cỡ khung', 'Color Palette': 'Bảng màu', 'Color Corrections': 'Chỉnh màu', 'Auto Adjust Colors': 'Tự chỉnh màu', 'Decrease Color Depth': 'Giảm độ sâu màu', Flip: 'Lật', Rotate: 'Xoay', Resize: 'Đổi kích thước', Trim: 'Cắt viền thừa', Histogram: 'Biểu đồ màu', Grid: 'Lưới', Zoom: 'Thu phóng', 'Zoom In': 'Phóng to', 'Zoom Out': 'Thu nhỏ', 'Zoom in': 'Phóng to', 'Zoom out': 'Thu nhỏ', 'Original Size': 'Cỡ gốc', 'Fit Window': 'Vừa cửa sổ', 'Fit window': 'Vừa cửa sổ', 'Full Screen': 'Toàn màn hình', Ruler: 'Thước', Guides: 'Đường gióng', 'Insert guides': 'Thêm đường gióng', 'Update guides': 'Sửa đường gióng', 'Guides enabled.': 'Đã bật đường gióng.', 'Grid on/off': 'Bật/tắt lưới', Horizontal: 'Ngang', Vertical: 'Dọc', 'Rotate left': 'Xoay trái', 'Rotate:': 'Xoay:', 'Right angle:': 'Góc vuông:', 'Set Image Size': 'Đặt cỡ ảnh', 'Trim Layers': 'Cắt viền các lớp', 'Trim white color?': 'Cắt cả màu trắng?', 'Trim borders:': 'Cắt viền:', 'Trim layer:': 'Cắt lớp:', 'Resize Boundary': 'Đổi kích thước theo khung', 'Resize Layer': 'Đổi kích thước lớp', 'Resize Layers': 'Đổi kích thước các lớp', 'Resize Text Layer': 'Đổi kích thước lớp chữ', 'Resized as background': 'Đổi kích thước làm nền', 'Resized:': 'Đã đổi:', Portrait: 'Dọc', Landscape: 'Ngang', Square: 'Vuông',
    // ---- lớp
    'New Layer': 'Lớp mới', 'New layer': 'Lớp mới', 'Insert new layer': 'Thêm lớp mới', 'Duplicate': 'Nhân đôi', 'Duplicate Layer': 'Nhân đôi lớp', 'Duplicate layer': 'Nhân đôi lớp', 'Merge Down': 'Gộp xuống', 'Merge Layers': 'Gộp các lớp', 'Flatten Image': 'Gộp hết thành một lớp', Rename: 'Đổi tên', 'Rename Layer': 'Đổi tên lớp', 'Move Layer': 'Di chuyển lớp', 'Move layer down': 'Chuyển lớp xuống', 'Move layer up': 'Chuyển lớp lên', Differences: 'Sai khác', 'Differences Down': 'Sai khác với lớp dưới', Composition: 'Pha trộn', 'Composition:': 'Pha trộn:', 'Change Composition': 'Đổi kiểu pha trộn', 'Change Layer Details': 'Đổi chi tiết lớp', 'Change Opacity': 'Đổi độ mờ', Opacity: 'Độ đục', 'Opacity:': 'Độ đục:', 'Convert layer to raster': 'Chuyển lớp thành ảnh', 'Convert to Raster': 'Chuyển thành ảnh', 'Show / Hide': 'Hiện / ẩn', Show: 'Hiện', Hide: 'Ẩn', 'Translate Layer': 'Di chuyển lớp', 'Rotate Layer': 'Xoay lớp', 'Update Brush Layer': 'Sửa lớp cọ', 'Update Pencil Layer': 'Sửa lớp bút chì', 'New Bezier Layer': 'Lớp đường cong mới', 'New Brush Layer': 'Lớp cọ mới', 'New Ellipse Layer': 'Lớp elip mới', 'New Gradient Layer': 'Lớp chuyển màu mới', 'New Line Layer': 'Lớp đường thẳng mới', 'New Pencil Layer': 'Lớp bút chì mới', 'New Polygon Layer': 'Lớp đa giác mới', 'New Rectangle Layer': 'Lớp chữ nhật mới', 'New Text Layer': 'Lớp chữ mới', 'Select Text Layer': 'Chọn lớp chữ', 'Layer is empty.': 'Lớp đang trống.', 'There are no layers behind.': 'Không có lớp nào phía sau.', 'There is only 1 layer.': 'Chỉ có 1 lớp.', 'Can not find previous layer.': 'Không thấy lớp trước.',
    // ---- công cụ
    Pencil: 'Bút chì', Brush: 'Cọ', Line: 'Đường thẳng', Arrow: 'Mũi tên', Rectangle: 'Chữ nhật', Circle: 'Tròn', Ellipse: 'Elip', Polygon: 'Đa giác', Text: 'Chữ', Fill: 'Tô màu', Gradient: 'Chuyển màu', Shapes: 'Hình khối', 'Shapes (H)': 'Hình khối (H)', Media: 'Ảnh mẫu', 'Fill Tool': 'Công cụ tô màu', 'Crop Tool': 'Cắt ảnh', 'Clone Tool': 'Sao chép vùng ảnh', 'Blur Tool': 'Làm mờ', 'Sharpen Tool': 'Làm nét', 'Erase Tool': 'Tẩy', 'Magic Eraser Tool': 'Tẩy thông minh', 'Desaturate Tool': 'Khử màu', 'Bulge/Pinch Tool': 'Phồng / bóp', 'Selection Tool': 'Chọn vùng', 'Select object tool': 'Chọn đối tượng', Pick: 'Lấy màu', Burn: 'Làm tối', Mosaic: 'Mosaic', Borders: 'Viền', Sprites: 'Sprite', 'Key-Points': 'Điểm đặc trưng', 'Content Fill': 'Tô theo nội dung', 'Color to Alpha': 'Màu thành trong suốt', 'Replace Color': 'Thay màu', 'Replace color': 'Thay màu', 'Restore Alpha': 'Khôi phục trong suốt', 'Color Zoom': 'Thu phóng màu', 'Color zoom': 'Thu phóng màu', 'Effect browser': 'Duyệt hiệu ứng', 'Effects browser': 'Duyệt hiệu ứng', 'Edit text...': 'Sửa chữ...',
    // ---- hiệu ứng
    'Black and White': 'Đen trắng', 'Box Blur': 'Mờ hộp', 'Box blur': 'Mờ hộp', Brightness: 'Độ sáng', 'Brightness:': 'Độ sáng:', Contrast: 'Tương phản', 'Contrast:': 'Tương phản:', Denoise: 'Giảm nhiễu', 'Dither': 'Tạo hạt', 'Dithering:': 'Tạo hạt:', 'Dot Screen': 'Chấm lưới', Edge: 'Đường viền', Emboss: 'Chạm nổi', Enrich: 'Làm giàu màu', 'Gaussian Blur': 'Mờ Gauss', Grains: 'Hạt', Grayscale: 'Thang xám', Heatmap: 'Bản đồ nhiệt', 'Hue Rotate': 'Xoay sắc độ', Hue: 'Sắc độ', 'Hue:': 'Sắc độ:', Negative: 'Âm bản', 'Night Vision': 'Nhìn đêm', Oil: 'Sơn dầu', Pencil2: 'Bút chì', Saturate: 'Bão hòa', Saturation: 'Độ bão hòa', 'Saturation:': 'Độ bão hòa:', Sepia: 'Nâu cổ', Sharpen: 'Làm nét', 'Sharpen:': 'Làm nét:', Shadow: 'Đổ bóng', Solarize: 'Phơi sáng', 'Tilt Shift': 'Thu nhỏ cảnh', Vibrance: 'Sống động', Vignette: 'Tối góc', Vintage: 'Cổ điển', Blueprint: 'Bản vẽ xanh', 'Zoom Blur': 'Mờ phóng', 'Zoom blur': 'Mờ phóng', 'Instagram Filters': 'Bộ lọc Instagram', 'Common Filters': 'Bộ lọc thường dùng', 'Radial': 'Tỏa tròn', 'Radial gradient': 'Chuyển màu tỏa tròn', Luminosity: 'Độ chói', Metrics: 'Theo font', Base: 'Cơ bản', Basic: 'Cơ bản', Advanced: 'Nâng cao', Dynamic: 'Động', Simple: 'Đơn giản', Strict: 'Nghiêm ngặt', Custom: 'Tùy chỉnh',
    // ---- tham số hộp thoại
    Ok: 'Đồng ý', Cancel: 'Hủy', Close: 'Đóng', Reset: 'Đặt lại', Update: 'Cập nhật', None: 'Không', All: 'Tất cả', Error: 'Lỗi', 'Name:': 'Tên:', 'Width:': 'Rộng:', 'Height:': 'Cao:', 'Width (%):': 'Rộng (%):', 'Height (%):': 'Cao (%):', 'Size:': 'Cỡ:', 'Type:': 'Kiểu:', 'Color:': 'Màu:', 'Colors:': 'Số màu:', 'Mode:': 'Chế độ:', 'Power:': 'Độ mạnh:', 'Strength:': 'Độ mạnh:', 'Level:': 'Mức:', 'Levels:': 'Số mức:', 'Radius:': 'Bán kính:', 'Blur Radius:': 'Bán kính mờ:', 'Blur power:': 'Độ mờ:', 'Gradient Radius:': 'Bán kính chuyển màu:', 'H Radius:': 'Bán kính ngang:', 'V Radius:': 'Bán kính dọc:', 'Horizontal blur:': 'Mờ ngang:', 'Vertical blur:': 'Mờ dọc:', 'Horizontal:': 'Ngang:', 'Vertical:': 'Dọc:', 'Direction:': 'Hướng:', 'Degree:': 'Độ:', 'Factor:': 'Hệ số:', 'Gap:': 'Khoảng cách:', 'Range:': 'Khoảng:', 'Percentage:': 'Phần trăm:', 'Exponent:': 'Lũy thừa:', 'Sensitivity:': 'Độ nhạy:', 'Target:': 'Đích:', 'Replacement:': 'Thay bằng:', 'Position:': 'Vị trí:', 'Center:': 'Tâm:', 'Center x:': 'Tâm x:', 'Center y:': 'Tâm y:', 'Offset X:': 'Lệch X:', 'Offset Y:': 'Lệch Y:', 'X position:': 'Vị trí X:', 'Y position:': 'Vị trí Y:', 'X start:': 'X đầu:', 'X end:': 'X cuối:', 'Y start:': 'Y đầu:', 'Y end:': 'Y cuối:', 'In proportion:': 'Giữ tỉ lệ:', 'Bounds:': 'Giới hạn:', 'Channel:': 'Kênh:', 'Red channel:': 'Kênh đỏ:', 'Green channel:': 'Kênh lục:', 'Blue channel:': 'Kênh lam:', 'Red': 'Đỏ', Green: 'Lục', Blue: 'Lam', Gray: 'Xám', 'Alpha': 'Độ trong', 'Alpha:': 'Độ trong:', 'Transparent:': 'Trong suốt:', 'Average:': 'Trung bình:', 'Luminance:': 'Độ chói:', 'Greyscale:': 'Thang xám:', 'Dominant color:': 'Màu chủ đạo:', 'Unique colors:': 'Số màu riêng:', 'Total pixels:': 'Tổng điểm ảnh:', 'Pixels:': 'Điểm ảnh:', 'Resolution:': 'Độ phân giải:', 'Histogram:': 'Biểu đồ:', 'Mouse:': 'Chuột:', 'Layers:': 'Số lớp:', 'Layout:': 'Bố cục:', 'Separated': 'Tách riêng', 'Separated (original types)': 'Tách riêng (giữ kiểu gốc)', Merged: 'Đã gộp', 'Full layers data': 'Đầy đủ dữ liệu lớp', 'Parameter #1:': 'Tham số 1:', 'Parameter #2:': 'Tham số 2:', 'Clone count:': 'Số bản sao:', 'Color #': 'Màu #', 'Current Color Preview': 'Màu đang chọn', Palette: 'Bảng màu', Hex: 'Mã màu', Selected: 'Đang chọn', Current: 'Hiện tại', Active: 'Đang dùng', Previous: 'Trước', Next: 'Sau', Toggle: 'Bật/tắt', Clear: 'Xóa sạch', 'Remove all': 'Xóa hết', Increase: 'Tăng', Decrease: 'Giảm', 'Anti aliasing': 'Làm mịn cạnh', 'Enable autoresize:': 'Tự đổi cỡ khung:', 'Expand edges': 'Mở rộng cạnh', 'Cloned edges': 'Nhân bản cạnh', 'Gif delay:': 'Trễ GIF:', Stream: 'Luồng', 'Stream:': 'Luồng:',
    // ---- chữ
    Font: 'Phông chữ', Left: 'Trái', Right: 'Phải', Center: 'Giữa', Middle: 'Giữa', Top: 'Trên', Bottom: 'Dưới', 'Left to Right': 'Trái sang phải', 'Right to Left': 'Phải sang trái', 'Top to Bottom': 'Trên xuống dưới', 'Bottom to Top': 'Dưới lên trên', 'Horizontal Alignment': 'Căn ngang', 'Vertical Alignment': 'Căn dọc', 'H. Align:': 'Căn ngang:', 'V. Align:': 'Căn dọc:', 'Kerning:': 'Giãn chữ:', 'Auto Kerning': 'Tự giãn chữ', 'Wrap:': 'Xuống dòng:', 'Wrap At:': 'Ngắt tại:', Word: 'Từ', 'Word + Letter': 'Từ và chữ cái', 'Search for Font': 'Tìm phông chữ', 'The quick brown fox jumps over the lazy dog.': 'Con cáo nâu nhanh nhẹn nhảy qua chú chó lười.',
    // ---- tệp, xuất
    'File name:': 'Tên tệp:', 'File size:': 'Dung lượng:', 'Save as type:': 'Định dạng:', 'Save layers:': 'Lưu các lớp:', 'Save as': 'Lưu thành', 'Quality:': 'Chất lượng:', 'Show file size:': 'Hiện dung lượng:', 'Last modified': 'Sửa lần cuối', 'New file': 'Tệp mới', 'New File': 'Tệp mới', 'Open Image': 'Mở ảnh', 'Open JSON File': 'Mở tệp nhiều lớp', 'Open data URL': 'Mở Data URL', 'Open File URL': 'Mở đường dẫn', 'Open File Webcam': 'Mở webcam', 'Open File Data URL': 'Mở Data URL', 'Data URL': 'Data URL', 'Data URL:': 'Data URL:', Webcam: 'Webcam', 'Webcam #': 'Webcam #', 'Portable Network Graphics': 'PNG (có nền trong suốt)', 'JPG/JPEG Format': 'JPG (nhẹ, không trong suốt)', 'Graphics Interchange Format': 'GIF', 'Tag Image File Format': 'TIFF', 'Windows Bitmap': 'BMP', 'Weppy File Format': 'WEBP', 'Can not animate 1 layer.': 'Cần ít nhất 2 lớp để làm ảnh động.',
    Keyword: 'Từ khóa', 'Keyword:': 'Từ khóa:', Search: 'Tìm', 'Search:': 'Tìm:', 'Your search did not match any images.': 'Không tìm thấy ảnh nào.', 'Error connecting to service.': 'Không kết nối được dịch vụ.',
    // ---- thông báo
    'Nothing is selected.': 'Chưa chọn gì.', 'Empty selection': 'Vùng chọn trống', 'Empty selection or type not image.': 'Vùng chọn trống hoặc lớp không phải ảnh.', 'Layer is vector, convert it to raster to apply this tool.': 'Lớp này là hình vẽ, hãy chuyển thành ảnh trước (menu Lớp).', 'This layer must contain an image. Please convert it to raster to apply this tool.': 'Lớp này phải là ảnh. Hãy chuyển thành ảnh trước (menu Lớp).', 'Previous layer must be image, convert it to raster to apply this tool.': 'Lớp bên dưới phải là ảnh. Hãy chuyển thành ảnh trước.', 'Crop on rotated layer is not supported. Convert it to raster to continue.': 'Không cắt được lớp đã xoay. Hãy chuyển thành ảnh trước.', 'Erase on rotate object is disabled. Please rasterize first.': 'Không tẩy được lớp đã xoay. Hãy chuyển thành ảnh trước.', 'Clone tool disabled for resized image. Please rasterize first.': 'Không sao chép được trên ảnh đã đổi cỡ. Hãy chuyển thành ảnh trước.', 'Rotate is not supported on this type of object. Convert to raster?': 'Không xoay được loại lớp này. Chuyển thành ảnh?', 'Can not use this tool on current layer: image already takes all area.': 'Không dùng được: ảnh đã kín cả khung.', 'Layer is not compatible with resize': 'Lớp này không đổi cỡ được', 'Missing at least 1 size parameter.': 'Thiếu ít nhất 1 kích thước.', 'Wrong dimensions': 'Kích thước không hợp lệ', 'Wrong file type, must be image or json.': 'Sai loại tệp, phải là ảnh hoặc json.', 'Sorry, image could not be loaded.': 'Không mở được ảnh này.', 'Sorry, image could not be loaded. Try copy image and paste it.': 'Không mở được ảnh. Hãy thử chép ảnh rồi dán vào.', 'Sorry, image is too big, max 5 MB.': 'Ảnh quá lớn, tối đa 5 MB.', 'Size is too big, max': 'Kích thước quá lớn, tối đa', 'Your browser does not support this format.': 'Trình duyệt không hỗ trợ định dạng này.', 'Use Ctrl+V keyboard shortcut to paste from Clipboard.': 'Bấm Ctrl+V để dán từ bộ nhớ.', 'You can also drag and drop items into browser.': 'Có thể kéo thả ảnh vào đây.', 'Rendering...': 'Đang vẽ...', 'Rendered with errors.': 'Vẽ xong nhưng có lỗi.', 'Skip - layer must be image.': 'Bỏ qua: lớp phải là ảnh.', 'Source coordinates saved.': 'Đã lưu vị trí nguồn.', 'Source is empty, right click on image or use long press to save source position.': 'Chưa có nguồn: bấm chuột phải lên ảnh để chọn vị trí nguồn.', 'Color alpha value can not be zero.': 'Độ trong của màu không được bằng 0.', 'Invalid Hex Code': 'Mã màu không hợp lệ', 'Error loading the list of fonts from Google.': 'Không tải được danh sách phông chữ của Google.',
    // ---- phím, nhãn tiếng Anh thừa
    Pressure: 'Theo lực nhấn', Box: 'Hộp', Selection: 'Chọn vùng', 'Pick color': 'Lấy màu', Erase: 'Tẩy', 'Right triangle': 'Tam giác vuông', Parallelogram: 'Hình bình hành', Trapezoid: 'Hình thang', Human: 'Người', Tear: 'Giọt nước', 'Bezier curve': 'Đường cong', Moon: 'Trăng khuyết', Clone: 'Sao chép vùng ảnh', Crop: 'Cắt ảnh', Desaturate: 'Khử màu', Animation: 'Ảnh động', 'Reset zoom level': 'Đặt lại thu phóng', Translate: 'Di chuyển', 
    'Author:': 'Tác giả:', 'Description:': 'Mô tả:', 'Email:': 'Email:', 'Version:': 'Phiên bản:', 'Website:': 'Trang web:', 'Color Picker': 'Bảng chọn màu', 'Zoom:': 'Thu phóng:', Insert: 'Chèn', 'URL:': 'Đường dẫn:',
    'Auto select': 'Tự chọn lớp', Bold: 'Đậm', Border: 'Viền', 'Border color': 'Màu viền', 'Border size': 'Cỡ viền', Bulge: 'Phồng', Contiguous: 'Chỉ vùng liền kề', Corners: 'Số góc', Delay: 'Độ trễ', 'Fill color': 'Màu nền', Global: 'Toàn ảnh', Icon: 'Biểu tượng', 'Inner radius': 'Bán kính trong', Italic: 'Nghiêng', Kerning: 'Giãn chữ', Leading: 'Giãn dòng', Max: 'Tối đa', Min: 'Tối thiểu', Play: 'Phát', Power: 'Độ mạnh', 'Radial power': 'Độ tỏa', Size: 'Cỡ', 'Source layer': 'Lớp nguồn', Step: 'Bước', Strength: 'Độ mạnh', Strikethrough: 'Gạch ngang', Stroke: 'Viền chữ', 'Stroke size': 'Cỡ viền chữ', Underline: 'Gạch chân', Value: 'Giá trị', Values: 'Giá trị',
    'Enable guides:': 'Bật đường gióng:', 'Enable snap:': 'Bật hít cạnh:', 'Exit confirmation:': 'Hỏi lại khi thoát:', 'Safe search:': 'Tìm kiếm an toàn:', 'Thick guides:': 'Đường gióng đậm:', 'Transparency background:': 'Nền trong suốt:', Units: 'Đơn vị',
    'Toggle Color Channels': 'Bật/tắt kênh màu', 'Toggle Color Picker': 'Bật/tắt bảng chọn màu', 'Toggle Swatches': 'Bật/tắt màu mẫu', 'Toggle Menu': 'Bật/tắt menu', 'Shortcut Key:': 'Phím tắt:', 'Scroll up': 'Cuộn lên', 'Scroll down': 'Cuộn xuống', Up: 'Lên', Down: 'Xuống', Move: 'Di chuyển', Fit: 'Vừa khung', Duotone: 'Hai tông màu', Levels: 'Mức sáng', Noise: 'Nhiễu', Pixelate: 'Vỡ điểm ảnh', 'Blur': 'Làm mờ', Bezier: 'Đường cong', Star: 'Ngôi sao', Heart: 'Trái tim', Triangle: 'Tam giác', 'Right Triangle': 'Tam giác vuông', 'Cylinder': 'Hình trụ', Cog: 'Bánh răng', Callout: 'Bong bóng chữ', Romb: 'Hình thoi', Pentagon: 'Ngũ giác', Hexagon: 'Lục giác', Plus: 'Dấu cộng', 'Clear Layer': 'Xóa nội dung lớp', 'Paste Image': 'Dán ảnh', Theme: 'Giao diện',
  };
  const skipTags = new Set(['SCRIPT', 'STYLE', 'CANVAS', 'TEXTAREA', 'INPUT']);
  const tr = (s) => {
    const k = s.trim();
    if (!k || !Object.prototype.hasOwnProperty.call(VI, k)) return null;
    return s.replace(k, VI[k]);
  };
  function fixText(node) {
    const p = node.parentElement;
    if (!p || skipTags.has(p.tagName)) return;
    if (p.tagName === 'OPTION' && !p.hasAttribute('value')) return;
    const out = tr(node.nodeValue);
    if (out !== null && out !== node.nodeValue) node.nodeValue = out;
  }
  function fixAttrs(n) {
    for (const a of ['title', 'placeholder', 'aria-label', 'alt']) {
      if (n.hasAttribute && n.hasAttribute(a)) {
        const out = tr(n.getAttribute(a));
        if (out !== null) n.setAttribute(a, out);
      }
    }
  }
  function walk(root) {
    if (root.nodeType === 3) { fixText(root); return; }
    if (root.nodeType !== 1 || skipTags.has(root.tagName)) return;
    fixAttrs(root);
    const w = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
    let n = w.nextNode();
    while (n) {
      if (n.nodeType === 3) fixText(n); else fixAttrs(n);
      n = w.nextNode();
    }
  }
  // Các mục không dùng trong iContent: cần tài khoản dịch vụ ngoài, hoặc đã có sẵn trong thanh trên cùng của iContent
  const HIDE_MENU = new Set(['Search Images', 'External', 'Language', 'Report Issues', 'Open Test Template', 'Tìm ảnh', 'Dịch vụ ngoài', 'Ngôn ngữ', 'Báo lỗi', 'Mở mẫu thử']);
  function hideExtras(root) {
    if (root.nodeType !== 1) return;
    root.querySelectorAll('a[role="menuitem"]').forEach((a) => {
      const nm = (a.querySelector('.name') || a).textContent.replace('...', '').trim();
      if (HIDE_MENU.has(nm)) a.parentElement.style.display = 'none';
    });
  }
  function start() {
    walk(document.body);
    hideExtras(document.body);
    const mo = new MutationObserver((muts) => {
      for (const m of muts) {
        if (m.type === 'characterData') fixText(m.target);
        else if (m.type === 'attributes') fixAttrs(m.target);
        else m.addedNodes.forEach((n) => { walk(n); hideExtras(n); });
      }
    });
    mo.observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ['title', 'placeholder'] });
    if (window.AppConfig) window.AppConfig.COLOR = '#ffb224';
    // thêm phông có đủ dấu tiếng Việt lên đầu danh sách
    if (window.AppConfig && Array.isArray(window.AppConfig.FONTS)) {
      for (const f of ['Be Vietnam Pro', 'Segoe UI', 'Segoe UI Black', 'Bahnschrift', 'Tahoma', 'Arial']) {
        const i = window.AppConfig.FONTS.indexOf(f);
        if (i >= 0) window.AppConfig.FONTS.splice(i, 1);
      }
      window.AppConfig.FONTS.unshift('Be Vietnam Pro', 'Segoe UI', 'Segoe UI Black', 'Bahnschrift', 'Arial', 'Tahoma');
    }
  }
  window.__ICONTENT_VI = VI;
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
}());
