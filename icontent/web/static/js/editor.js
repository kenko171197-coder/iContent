/* Trang Trình dựng: mở trình dựng tự do (FreeCut, chạy ở cửa sổ riêng), kiểm tra máy có đủ điều kiện, chọn video đã làm để dựng tiếp. */
import { api, busy, el, emptyState, enc, fmtAgo, icon, toast } from './core.js';

/* Hỏi thẳng trình duyệt: máy khách có thể quá cũ hoặc tắt WebGPU, phải nói trước thay vì để mở ra rồi hỏng. */
export async function editorSupport() {
  const miss = [];
  if (typeof window.showDirectoryPicker !== 'function') miss.push('Trình duyệt không cho lưu dự án vào thư mục trên máy');
  if (typeof window.VideoEncoder !== 'function') miss.push('Trình duyệt không có WebCodecs để xuất video');
  let adapter = null;
  try { adapter = navigator.gpu ? await navigator.gpu.requestAdapter() : null; } catch (_) { adapter = null; }
  if (!adapter) miss.push('Không dùng được WebGPU (card đồ họa quá cũ, chưa cập nhật driver, hoặc đang tắt tăng tốc phần cứng)');
  return miss;
}

export async function openEditor(job) {
  const r = await api('POST', '/api/editor/open', job ? { job } : {});
  if (r.already_open) toast('Video này đang mở trong trình dựng. Bấm biểu tượng iContent trên thanh tác vụ để chuyển sang cửa sổ đó.', 'info', { timeout: 6000 });
  else if (job) toast('Đang mở trình dựng. Lần đầu mỗi video, iContent cần dựng một bản không phụ đề nên hơi lâu.', 'info', { timeout: 5000 });
  else toast('Đang mở trình dựng', 'info', { timeout: 2200 });
  return r;
}

/** Mở một câu chuyện của Kể chuyện: mỗi cảnh một clip, lời dẫn, phụ đề, chữ mở đầu và kết thúc sửa được. */
export async function openStoryInEditor(story) {
  const r = await api('POST', '/api/editor/open', { story });
  if (r.already_open) toast('Câu chuyện này đang mở trong trình dựng. Bấm biểu tượng iContent trên thanh tác vụ để chuyển sang cửa sổ đó.', 'info', { timeout: 6000 });
  else toast('Đang mở trình dựng. iContent chuẩn bị từng cảnh (đọc lời dẫn, máy quay chuyển động) nên lần đầu hơi lâu.', 'info', { timeout: 5000 });
  return r;
}

export async function viewEditor(main, alive) {
  main.classList.add('view-pad');
  const [status, list] = await Promise.all([api('GET', '/api/editor/status'), api('GET', '/api/jobs').catch(() => ({ jobs: [] }))]);
  if (!alive()) return null;
  const notice = el('div');
  const openBtn = el('button', { class: 'btn btn-primary', disabled: !status.available, onclick: () => busy(openBtn, () => openEditor()) }, icon('scissors'), 'Mở trình dựng');
  const jobs = (list.jobs || []).filter((j) => j.stages && j.stages.render);
  main.append(...[
    el('div', { class: 'page-head' },
      el('div', { class: 'page-head-text' },
        el('div', { class: 'eyebrow', text: 'Trình dựng tự do' }),
        el('h1', { text: 'Dựng nhiều track như CapCut' }),
        el('p', { text: 'Tách ghép trên timeline, chồng nhiều lớp hình và tiếng, keyframe, chuyển cảnh, hiệu ứng, chỉnh màu, chữ chuyển động. Chạy ngay trên máy này, không tải video lên đâu.' })),
      el('div', { class: 'actions' }, openBtn)),
    notice,
    !status.available ? el('div', { class: 'ed-note ed-warn' }, icon('alert'), el('span', { text: 'Bản cài này chưa có trình dựng. Xem third_party/freecut/build.py để build lại.' })) : null,
    el('div', { class: 'ed-note' }, icon('info'), el('span', { text: 'Lần đầu mở, trình dựng hỏi một thư mục để lưu dự án: tạo một thư mục mới, ví dụ D:\\iContent Editor, rồi bấm Cho phép. Trình duyệt không cho chọn thư mục hệ thống hay AppData. Những lần sau, nếu trình dựng hỏi lại thì bấm Kết nối lại.' })),
    el('h3', { class: 'ed-head', text: 'Dựng tiếp video đã làm' }),
    el('p', { class: 'muted small', text: 'Video mở ra đã xóa sub, đã lồng tiếng, phụ đề tiếng Việt nằm trên track riêng sửa được. Dựng xong bấm Gửi về iContent để kiểm định và đóng gói đăng.' }),
    jobs.length ? el('div', { class: 'ed-jobs' }, jobs.map((j) => {
      const b = el('button', {
        class: 'ed-job', disabled: !status.available, onclick: () => busy(b, () => openEditor(j.id)),
      }, el('img', { src: `/api/jobs/${enc(j.id)}/thumb.jpg`, alt: '', loading: 'lazy' }),
      el('span', { class: 'ed-job-t' }, el('b', { text: j.title_vi || j.title || j.id }), el('span', { class: 'dim small', text: j.created ? fmtAgo(j.created) : '' })), icon('scissors'));
      return b;
    })) : emptyState('Chưa có video nào', 'Làm một video ở trang Tạo video, hoặc mở trình dựng để dựng từ tư liệu của mình.', null),
    el('p', { class: 'dim small ed-credit', text: 'Trình dựng dựa trên FreeCut của walterlow, giấy phép MIT. Danh sách thư viện kèm theo ở icontent/web/editor/THIRD_PARTY_NOTICES.txt.' }),
  ].filter(Boolean));      // append() biến null thành chữ "null" trên trang
  if (status.available) {
    editorSupport().then((miss) => {
      if (!alive() || !miss.length) return;
      notice.replaceChildren(el('div', { class: 'ed-note ed-warn' }, icon('alert'), el('span', {},
        el('b', { text: 'Máy này có thể không chạy được trình dựng. ' }), miss.join('. ') + '.')));
    });
  }
  return null;
}
