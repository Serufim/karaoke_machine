// ============================================================================
// Конфигурация воронки и уведомлений (можно вставить свой TG-канал или Webhook)
// ============================================================================
const LANDING_CONFIG = {
  // Ссылка на твой Telegram-канал или чат бета-тестеров (поменяй в любой момент)
  telegramChannelUrl: 'https://github.com/Serufim/karaoke_machine/discussions',
  // Опциональный Webhook (например, Formspree / Web3Forms / Telegram Bot API)
  leadWebhookUrl: '',
};

// ============================================================================
// 1. Интерактивный симулятор караоке по слогам
// ============================================================================
const DEMO_LINES = [
  {
    syllables: ['Го-', 'род ', 'спит ', 'в нео-', 'но-', 'вых ', 'ог-', 'нях,'],
    next: 'Мы взлетаем выше облаков сейчас!',
  },
  {
    syllables: ['Мы ', 'взле-', 'та-', 'ем ', 'вы-', 'ше ', 'об-', 'ла-', 'ков!'],
    next: 'И никто не остановит этот бит...',
  },
  {
    syllables: ['И ', 'ник-', 'то ', 'не ос-', 'та-', 'но-', 'вит ', 'этот ', 'бит!'],
    next: 'Пой со мной, пока горит рассвет!',
  },
  {
    syllables: ['Пой ', 'со ', 'мной, ', 'по-', 'ка ', 'го-', 'рит ', 'рас-', 'свет!'],
    next: 'Город спит в неоновых огнях,',
  },
];

let currentLineIndex = 0;
let currentSyllableIndex = 0;
let currentStyle = 'gold'; // 'gold' | 'cyber' | 'pink'
let simSeconds = 14.2;

function renderKaraokeStage() {
  const activeContainer = document.getElementById('karaoke-active-line');
  const nextContainer = document.getElementById('karaoke-next-line');
  if (!activeContainer || !nextContainer) return;

  const lineObj = DEMO_LINES[currentLineIndex];
  nextContainer.textContent = lineObj.next;

  let activeColorClass = 'text-amber-300 glow-gold';
  if (currentStyle === 'cyber') activeColorClass = 'text-sky-300 glow-cyber';
  if (currentStyle === 'pink') activeColorClass = 'text-pink-400 glow-pink';

  activeContainer.innerHTML = lineObj.syllables
    .map((syl, idx) => {
      if (idx <= currentSyllableIndex) {
        return `<span class="${activeColorClass} inline-block transform scale-105 transition-all duration-150">${syl}</span>`;
      }
      return `<span class="text-slate-500 transition-all duration-150">${syl}</span>`;
    })
    .join('');
}

function stepKaraokeSimulation() {
  const lineObj = DEMO_LINES[currentLineIndex];
  currentSyllableIndex++;

  if (currentSyllableIndex >= lineObj.syllables.length) {
    currentSyllableIndex = 0;
    currentLineIndex = (currentLineIndex + 1) % DEMO_LINES.length;
    if (currentLineIndex === 1) {
      triggerEmojiBurst();
    }
  }

  simSeconds += 0.35;
  if (simSeconds > 45) simSeconds = 12.0;
  const tcEl = document.getElementById('sim-timecode');
  if (tcEl) {
    tcEl.textContent = `00:${simSeconds.toFixed(2).padStart(5, '0')} / 03:12.00`;
  }

  renderKaraokeStage();
}

function setHighlightStyle(style) {
  currentStyle = style;
  const styles = ['gold', 'cyber', 'pink'];
  styles.forEach((s) => {
    const btn = document.getElementById(`btn-style-${s}`);
    if (!btn) return;
    if (s === style) {
      btn.className = 'px-2.5 py-1 rounded bg-sky-500/25 text-sky-200 border border-sky-400 font-semibold';
    } else {
      btn.className = 'px-2.5 py-1 rounded bg-slate-800 text-slate-300 border border-slate-700 font-medium';
    }
  });
  renderKaraokeStage();
}

function setVocalMode(mode) {
  const btnMinus = document.getElementById('btn-voc-minus');
  const btnGuide = document.getElementById('btn-voc-guide');
  const badge = document.getElementById('vocal-status-badge');

  if (mode === 'minus') {
    btnMinus.className = 'px-2.5 py-1 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 font-medium';
    btnGuide.className = 'px-2.5 py-1 rounded bg-slate-800 text-slate-300 border border-slate-700 font-medium';
    badge.textContent = '🎵 ИГРАЕТ ЧИСТЫЙ ИНСТРУМЕНТАЛ (ВОКАЛ 0% • DEMUCS 4X)';
  } else {
    btnGuide.className = 'px-2.5 py-1 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 font-medium';
    btnMinus.className = 'px-2.5 py-1 rounded bg-slate-800 text-slate-300 border border-slate-700 font-medium';
    badge.textContent = '🎤 РЕЖИМ ПОДПЕВКИ НА ПРИПЕВЕ (ВОКАЛ 30% + ИНСТРУМЕНТАЛ)';
  }
}

function triggerEmojiBurst() {
  const layer = document.getElementById('emoji-layer');
  if (!layer) return;

  const emojis = ['🔥', '🎉', '🚀', '✨', '🎸', '💎', '⚡'];
  for (let i = 0; i < 10; i++) {
    const span = document.createElement('span');
    span.className = 'emoji-particle absolute text-2xl sm:text-3xl';
    span.textContent = emojis[Math.floor(Math.random() * emojis.length)];
    span.style.left = `${15 + Math.random() * 70}%`;
    span.style.bottom = `${15 + Math.random() * 35}%`;
    layer.appendChild(span);
    setTimeout(() => span.remove(), 1600);
  }
}

// ============================================================================
// 2. Интерактивный калькулятор совместимости железа
// ============================================================================
function updateGpuEstimate() {
  const sel = document.getElementById('gpu-selector');
  const timeEl = document.getElementById('hw-time');
  const presetEl = document.getElementById('hw-preset');
  const statusEl = document.getElementById('hw-status');

  if (!sel) return;
  const val = sel.value;

  if (val === 'rtx_high') {
    timeEl.textContent = '~35–50 секунд';
    timeEl.className = 'mt-1 text-xl font-black text-emerald-400';
    presetEl.textContent = 'Whisper Large-v3 Turbo + Demucs FT';
    statusEl.textContent = '✅ Максимальная скорость (CUDA)';
  } else if (val === 'rtx_mid') {
    timeEl.textContent = '~1.5 минуты';
    timeEl.className = 'mt-1 text-xl font-black text-sky-400';
    presetEl.textContent = 'Whisper Large-v3 Turbo (FP16) + HTDemucs';
    statusEl.textContent = '✅ Полная поддержка (CUDA)';
  } else if (val === 'mac_silicon') {
    timeEl.textContent = '~45–60 секунд';
    timeEl.className = 'mt-1 text-xl font-black text-emerald-400';
    presetEl.textContent = 'Whisper Large-v3 Turbo + Demucs FT';
    statusEl.textContent = '✅ Нативное ускорение Apple Metal';
  } else {
    timeEl.textContent = '~3.5–4 минуты';
    timeEl.className = 'mt-1 text-xl font-black text-amber-400';
    presetEl.textContent = 'Whisper Small + HTDemucs (CPU 4 потока)';
    statusEl.textContent = '⚡ Работает без видеокарты (Режим CPU)';
  }
}

// ============================================================================
// 3. Воронка предзаказов (Waitlist / Fake Door Analytics)
// ============================================================================
let selectedPlan = 'Early Bird Indie (690 ₽ / $7)';

function trackClick(eventName) {
  try {
    const stats = JSON.parse(localStorage.getItem('karaoke_funnel_stats') || '{}');
    stats[eventName] = (stats[eventName] || 0) + 1;
    localStorage.setItem('karaoke_funnel_stats', JSON.stringify(stats));
  } catch (_) {}
}

function openWaitlistModal(planTitle) {
  selectedPlan = planTitle;
  trackClick(`open_modal_${planTitle}`);
  const label = document.getElementById('selected-plan-label');
  if (label) label.textContent = planTitle;

  document.getElementById('waitlist-form').classList.remove('hidden');
  document.getElementById('waitlist-success').classList.add('hidden');

  const modal = document.getElementById('waitlist-modal');
  modal.classList.remove('hidden');
  modal.classList.add('flex');
}

function closeWaitlistModal() {
  const modal = document.getElementById('waitlist-modal');
  modal.classList.add('hidden');
  modal.classList.remove('flex');
}

async function submitWaitlistForm(e) {
  e.preventDefault();
  const contact = document.getElementById('lead-contact').value.trim();
  const os = document.getElementById('lead-os').value;
  const usecase = document.getElementById('lead-usecase').value;

  const payload = {
    plan: selectedPlan,
    contact,
    os,
    usecase,
    timestamp: new Date().toISOString(),
  };

  trackClick('lead_submitted');

  // Отправка на Webhook, если указан в конфиге
  if (LANDING_CONFIG.leadWebhookUrl) {
    try {
      await fetch(LANDING_CONFIG.leadWebhookUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
    } catch (_) {}
  }

  document.getElementById('waitlist-form').classList.add('hidden');
  document.getElementById('waitlist-success').classList.remove('hidden');
}

// Инициализация при старте
document.addEventListener('DOMContentLoaded', () => {
  renderKaraokeStage();
  setInterval(stepKaraokeSimulation, 420);
});
