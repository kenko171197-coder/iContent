/* Trang Giới thiệu của Studio566. */
import { el } from './core.js';

export async function viewAbout(main) {
  main.append(
    el('div', { class: 'page-head' },
      el('div', { class: 'page-head-text' }, el('div', { class: 'eyebrow', text: 'Giới thiệu' }), el('h1', { text: 'Studio566' }),
        el('p', { text: 'Công cụ miễn phí giúp người làm nội dung Việt dịch và lồng tiếng video Trung Quốc, chạy ngay trên máy của bạn.' }))),
    el('div', { class: 'about-grid' },
      el('div', { class: 'panel' }, el('h3', { text: 'Dữ liệu của bạn ở đâu' }),
        el('p', { class: 'muted', text: 'Video, phụ đề và giọng lồng nằm trên máy của bạn. API key lưu tại keys.json trên máy và chỉ được gửi tới chính nhà cung cấp bạn chọn. Câu thoại chỉ rời máy khi dịch bằng dịch vụ online.' })),
      el('div', { class: 'panel' }, el('h3', { text: 'Lưu ý bản quyền' }),
        el('p', { class: 'muted', text: 'Hãy dùng Studio566 với video bạn có quyền sử dụng hoặc đã được phép đăng lại, và ghi nguồn khi cần.' })),
      el('div', { class: 'panel' }, el('h3', { text: 'Ghi công' }),
        el('p', { class: 'muted', text: 'Dựa trên yt-dlp, faster-whisper, RapidOCR, VieNeu-TTS, sherpa-onnx, Ollama, Hy-MT của Tencent, FFmpeg và OpenCV. Trình dựng tự do là FreeCut của walterlow (giấy phép MIT). Ảnh AI của Kể chuyện do Google Gemini vẽ. Trình sửa ảnh là miniPaint của ViliusL (giấy phép MIT). Dò khuôn mặt bằng YuNet (giấy phép MIT), pinyin từ dữ liệu Unihan của Unicode. Giao diện dùng font Be Vietnam Pro và JetBrains Mono (giấy phép SIL OFL).' }))));
  return null;
}
