/* Kiểm tra trước khi đăng: chấm điểm và chỉ đúng câu có vấn đề. Mọi phép kiểm chạy ngay trên dữ liệu đã có. */
import { getPath } from './core.js';

const CJK = /[一-鿿]/;
const SEV = { error: 10, warn: 3, info: 0 };

/** -> {score, issues:[{id, sev, title, hint, lines:[index]}], passed:[title]} */
export function runChecks(job, segs, opts) {
  const eff = (opts && opts.eff) || job.effective || {};
  const issues = [];
  const passed = [];
  const check = (id, sev, title, okTitle, hint, lines, extra) => {
    if (lines.length) issues.push({ id, sev, title: title(lines.length), hint, lines, weight: extra });
    else passed.push(okTitle);
  };
  const cuts = (opts && opts.cuts) || [];
  const cutWhole = (s) => cuts.some(([a, b]) => s.start >= a - 0.01 && s.end <= b + 0.01);
  const cutPart = (s) => !cutWhole(s) && cuts.some(([a, b]) => s.start < b - 0.05 && s.end > a + 0.05);
  // câu nằm trọn trong đoạn đã cắt không xuất hiện trong video nên không cần kiểm tra
  const idx = (fn) => segs.map((s, i) => (!cutWhole(s) && fn(s, i) ? i : -1)).filter((i) => i >= 0);
  const hasTrans = segs.some((s) => (s.trans || '').trim());
  const ttsOn = getPath(eff, 'tts.enabled') !== false;

  check('missing', 'error', (n) => `${n} câu chưa có bản dịch`, 'Mọi câu đều có bản dịch', 'Điền bản dịch, hoặc bấm Dịch lại',
    idx((s) => !(s.trans || '').trim()));
  // tiếng Nhật được dùng chữ Hán: chỉ coi là sót tiếng Trung khi câu không có chữ kana nào
  const lang = getPath(eff, 'translate.target_lang') || 'vi';
  const leftover = (t) => CJK.test(t) && !(lang === 'ja' && /[぀-ヿ]/.test(t));
  check('cjk', 'error', (n) => `${n} câu còn sót chữ Hán trong bản dịch`, 'Bản dịch không còn sót chữ Hán', 'Thường là tên riêng chưa được dịch',
    idx((s) => leftover(s.trans || '')));
  if (ttsOn && hasTrans) {
    check('undubbed', 'error', (n) => `${n} câu chưa được lồng tiếng`, 'Mọi câu đều đã được lồng tiếng', 'Bấm Cập nhật video để lồng bù',
      idx((s) => (s.trans || '').trim() && s.dub_start == null));
    check('rush', 'error', (n) => `${n} câu đọc rất nhanh (trên 1,5 lần)`, 'Không có câu nào đọc quá nhanh', 'Rút gọn bản dịch để giọng đọc tự nhiên hơn',
      idx((s) => Number(s.speed) > 1.5));
    check('fast', 'warn', (n) => `${n} câu đọc hơi nhanh (trên 1,3 lần)`, 'Tốc độ đọc tự nhiên ở mọi câu', 'Nên rút gọn một chút',
      idx((s) => Number(s.speed) > 1.3 && Number(s.speed) <= 1.5));
    const total = (job.meta && job.meta.duration) || 0;
    const last = segs.filter((s) => s.dub_end != null).pop();
    if (last && total && last.dub_end > total + 0.3) {
      issues.push({ id: 'overflow', sev: 'warn', title: `Giọng lồng dài hơn video ${(last.dub_end - total).toFixed(1).replace('.', ',')} giây`, hint: 'Phần cuối sẽ bị cắt. Rút gọn câu cuối.', lines: [segs.indexOf(last)] });
    }
  }
  if (cuts.length) {
    check('cutpart', 'info', (n) => `${n} câu bị đoạn cắt cắt ngang`, 'Không có câu nào bị cắt ngang', 'Người xem sẽ nghe mất một phần câu. Nới đoạn cắt cho trọn câu nếu thấy khó nghe', idx((s) => cutPart(s)));
  }
  check('long', 'warn', (n) => `${n} câu quá dài cho phụ đề`, 'Phụ đề vừa khung hình', 'Trên 90 ký tự thường phải xuống dòng nhiều lần, nên tách câu',
    idx((s) => (s.trans || '').length > 90));
  check('short', 'info', (n) => `${n} câu hiện rất nhanh (dưới 0,5 giây)`, 'Không có câu nào lướt quá nhanh', 'Người xem có thể không kịp đọc',
    idx((s) => s.end - s.start < 0.5 && (s.trans || '').trim()));
  check('repeat', 'info', (n) => `${n} câu trùng với câu liền trước`, 'Không có câu lặp liền nhau', 'Có thể là lỗi nhận dạng',
    idx((s, i) => i > 0 && (s.trans || '').trim() && s.trans.trim() === (segs[i - 1].trans || '').trim()));

  if (opts.dirty) issues.push({ id: 'unsaved', sev: 'warn', title: `${opts.dirty} câu đã sửa nhưng chưa lưu`, hint: 'Bấm Lưu hoặc Cập nhật video', lines: [] });
  if (job.stale && !opts.dirty) issues.push({ id: 'stale', sev: 'warn', title: 'Video đã xuất chưa có các thay đổi mới nhất', hint: 'Bấm Cập nhật video', lines: [] });
  else if (!job.stale && !opts.dirty && job.files && job.files.final) passed.push('Video đã xuất là bản mới nhất');
  if (!(job.files && job.files.final)) issues.push({ id: 'norender', sev: 'error', title: 'Chưa có video thành phẩm', hint: 'Bấm Cập nhật video', lines: [] });

  const hs = job.hardsub && job.hardsub.box;
  const hsMode = getPath(eff, 'edit.blur_hardsub');
  if (hs && (hsMode === false || hsMode === 'false')) {
    issues.push({ id: 'hardsub', sev: 'warn', title: 'Video có sub tiếng Trung nhưng đang để nguyên', hint: 'Vào tab Hình ảnh, chọn Tự dò và xử lý', lines: [] });
  } else if (hs) passed.push('Sub tiếng Trung đã được xử lý');

  const pub = job.context && job.context.publish;
  if (!pub || !pub.title) issues.push({ id: 'publish', sev: 'info', title: 'Chưa có tiêu đề và hashtag do AI gợi ý', hint: 'Kết nối AI rồi dịch lại để có bộ đăng bài', lines: [] });
  else passed.push('Đã có tiêu đề và hashtag');
  if (!(job.files && job.files.cover)) issues.push({ id: 'cover', sev: 'info', title: 'Chưa có ảnh bìa', hint: 'Tạo ở tab Đăng bài', lines: [] });
  else passed.push('Đã có ảnh bìa');

  const order = { error: 0, warn: 1, info: 2 };
  issues.sort((a, b) => order[a.sev] - order[b.sev]);
  let score = 100;
  for (const it of issues) score -= SEV[it.sev] + (it.sev !== 'info' ? Math.min(it.lines.length, 5) : 0);
  return { score: Math.max(0, score), issues, passed };
}
