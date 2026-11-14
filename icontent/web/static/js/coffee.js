/* Mời tác giả cà phê: iContent miễn phí, ủng hộ hoàn toàn tự nguyện. Thông tin lấy từ /api/about (về sau chỉ sửa 1 chỗ). */
import { api, copyText, el, icon, modalHead, openModal } from './core.js';

let about = null;
async function loadAbout() {
  if (!about) about = await api('GET', '/api/about');
  return about;
}

/** Thẻ cà phê: QR + số tài khoản. Dùng trong hộp thoại và trang Giới thiệu. */
export async function coffeeCard() {
  const a = await loadAbout();
  const d = a.donate;
  return el('div', { class: 'coffee' },
    el('div', { class: 'coffee-text' },
      el('div', { class: 'coffee-title' },
        el('span', { class: 'coffee-cup' }, icon('coffee')),
        el('div', {}, el('h3', { text: 'Mời tác giả một ly cà phê' }), el('p', { class: 'muted small', text: 'iContent hoàn toàn miễn phí' }))),
      a.message.map((m, i) => el('p', { class: i === a.message.length - 1 ? 'coffee-thanks' : '', text: m })),
      el('p', { class: 'dim small coffee-note', text: a.voluntary })),
    el('div', { class: 'coffee-pay' },
      el('div', { class: 'qr' }, el('img', { src: d.qr, alt: `Mã VietQR chuyển khoản ${d.bank} ${d.account}`, width: 200, height: 200 })),
      el('p', { class: 'dim small center-text', text: d.note }),
      el('dl', { class: 'bank' },
        el('div', {}, el('dt', { text: 'Ngân hàng' }), el('dd', { text: d.bank })),
        el('div', {}, el('dt', { text: 'Chủ tài khoản' }), el('dd', { text: d.holder })),
        el('div', {}, el('dt', { text: 'Số tài khoản' }), el('dd', {},
          el('span', { class: 'mono', text: d.account }),
          el('button', { class: 'btn btn-xs', onclick: () => copyText(d.account, 'Đã chép số tài khoản') }, icon('copy'), 'Chép'))))));
}

export async function openCoffee() {
  const card = await coffeeCard();
  const m = openModal([modalHead('coffee', 'Cà phê cho tác giả', () => m), el('div', { class: 'modal-body' }, card)], { cls: 'modal-coffee' });
}

/** Một dòng nhỏ sau khi xong video. Chỉ là đường dẫn, không bật hộp thoại, không làm phiền. */
export const coffeeLine = (text) => el('button', { class: 'coffee-line', onclick: openCoffee }, icon('coffee'), text || 'Thấy hữu ích? Mời tác giả ly cà phê');

export async function viewAbout(main) {
  const card = await coffeeCard();
  main.append(
    el('div', { class: 'page-head' },
      el('div', { class: 'page-head-text' }, el('div', { class: 'eyebrow', text: 'Giới thiệu' }), el('h1', { text: 'iContent Studio' }),
        el('p', { text: 'Công cụ miễn phí giúp người làm nội dung Việt dịch và lồng tiếng video Trung Quốc, chạy ngay trên máy của bạn.' }))),
    el('div', { class: 'panel about-coffee' }, card),
    el('div', { class: 'about-grid' },
      el('div', { class: 'panel' }, el('h3', { text: 'Dữ liệu của bạn ở đâu' }),
        el('p', { class: 'muted', text: 'Video, phụ đề và giọng lồng nằm trên máy của bạn. API key lưu tại keys.json trên máy và chỉ được gửi tới chính nhà cung cấp bạn chọn. Câu thoại chỉ rời máy khi dịch bằng dịch vụ online.' })),
      el('div', { class: 'panel' }, el('h3', { text: 'Lưu ý bản quyền' }),
        el('p', { class: 'muted', text: 'Hãy dùng iContent với video bạn có quyền sử dụng hoặc đã được phép đăng lại, và ghi nguồn khi cần.' })),
      el('div', { class: 'panel' }, el('h3', { text: 'Ghi công' }),
        el('p', { class: 'muted', text: 'Dựa trên yt-dlp, faster-whisper, RapidOCR, VieNeu-TTS, sherpa-onnx, Ollama, Hy-MT của Tencent, FFmpeg và OpenCV. Trình dựng tự do là FreeCut của walterlow (giấy phép MIT). Ảnh AI của Kể chuyện do Google Gemini vẽ. Trình sửa ảnh là miniPaint của ViliusL (giấy phép MIT). Dò khuôn mặt bằng YuNet (giấy phép MIT), pinyin từ dữ liệu Unihan của Unicode. Giao diện dùng font Be Vietnam Pro và JetBrains Mono (giấy phép SIL OFL).' }))));
  return null;
}
