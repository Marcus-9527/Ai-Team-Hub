import { useEffect, useRef, useCallback } from 'react';

const SLIDE_COUNT = 10;

export default function PitchDeck({ onBack }) {
  const curRef = useRef(0);
  const lockRef = useRef(false);
  const deckRef = useRef(null);
  const progressRef = useRef(null);
  const dotsRef = useRef(null);
  const hintRef = useRef(null);
  const gsapRef = useRef(null);

  const update = useCallback((cur) => {
    const progress = progressRef.current;
    const dots = dotsRef.current;
    const hint = hintRef.current;
    if (progress) progress.style.width = `${(cur / (SLIDE_COUNT - 1)) * 100}%`;
    if (dots) dots.querySelectorAll('.dot').forEach((d, i) => d.classList.toggle('active', i === cur));
    if (hint) hint.classList.toggle('hide', cur > 0);
  }, []);

  const goTo = useCallback((i) => {
    if (i < 0 || i >= SLIDE_COUNT || lockRef.current || i === curRef.current) return;
    lockRef.current = true;

    const deck = deckRef.current;
    if (!deck) return;

    const slides = deck.querySelectorAll('.slide');
    const prevEl = slides[curRef.current];
    const nextEl = slides[i];

    // Ensure GSAP is loaded
    const gsap = gsapRef.current;
    if (!gsap) { lockRef.current = false; return; }

    if (window._tl) window._tl.kill();

    const tl = gsap.timeline({ onComplete: () => { lockRef.current = false; } });

    const prevAnimEls = prevEl.querySelectorAll('.gsap-anim');
    if (prevAnimEls.length) {
      tl.to(prevAnimEls, { y: -18, opacity: 0, duration: 0.2, stagger: 0.03, ease: 'power2.in' }, 0);
    } else {
      tl.to(prevEl, { opacity: 0, duration: 0.15, ease: 'power2.in' }, 0);
    }

    tl.call(() => {
      prevEl.classList.remove('active');
      curRef.current = i;
      nextEl.classList.add('active');
      update(i);
      if (prevAnimEls.length) {
        gsap.set(prevAnimEls, { opacity: '', y: '', transform: '', filter: '' });
      }
    }, [], 0.12);

    const animEls = nextEl.querySelectorAll('.gsap-anim');
    if (animEls.length) {
      tl.fromTo(animEls,
        { opacity: 0, y: 25, filter: 'blur(4px)' },
        { opacity: 1, y: 0, filter: 'blur(0px)', duration: 0.5, stagger: 0.07, ease: 'power3.out' },
        0.18
      );
    } else {
      tl.fromTo(nextEl,
        { opacity: 0, y: 20 },
        { opacity: 1, y: 0, duration: 0.4, ease: 'power2.out' },
        0.18
      );
    }

    const numEl = nextEl.querySelector('.slide-num');
    if (numEl) {
      tl.fromTo(numEl, { opacity: 0 }, { opacity: 1, duration: 0.3, ease: 'none' }, 0.65);
    }

    window._tl = tl;
  }, [update]);

  const next = useCallback(() => goTo(curRef.current + 1), [goTo]);
  const prev = useCallback(() => goTo(curRef.current - 1), [goTo]);

  // Load GSAP and init
  useEffect(() => {
    // Load GSAP from CDN if not present
    if (window.gsap) {
      gsapRef.current = window.gsap;
    } else {
      const script = document.createElement('script');
      script.src = 'https://cdn.jsdelivr.net/npm/gsap@3.12/dist/gsap.min.js';
      script.onload = () => { gsapRef.current = window.gsap; };
      document.head.appendChild(script);
    }
  }, []);

  // Initial entrance animation after GSAP loads
  useEffect(() => {
    const check = setInterval(() => {
      if (window.gsap) {
        clearInterval(check);
        gsapRef.current = window.gsap;
        const deck = deckRef.current;
        if (!deck) return;
        const initEls = deck.querySelectorAll('.slide.active .gsap-anim');
        const hint = deck.querySelector('.slide.active .hint');
        const numEl = deck.querySelector('.slide.active .slide-num');

        gsap.fromTo(initEls,
          { y: 50, opacity: 0, filter: 'blur(6px)' },
          { y: 0, opacity: 1, filter: 'blur(0px)', duration: 0.7, stagger: 0.12, ease: 'power3.out', delay: 0.2 }
        );
        if (hint) gsap.fromTo(hint, { opacity: 0 }, { opacity: 1, duration: 0.4, delay: 1.2 });
        if (numEl) gsap.fromTo(numEl, { opacity: 0 }, { opacity: 1, duration: 0.3, delay: 1.3 });
      }
    }, 100);
    return () => clearInterval(check);
  }, []);

  // Keyboard / wheel / touch events
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'ArrowDown' || e.key === 'PageDown' || e.key === ' ') { e.preventDefault(); next(); }
      else if (e.key === 'ArrowUp' || e.key === 'PageUp') { e.preventDefault(); prev(); }
      else if (e.key === 'Home') { e.preventDefault(); goTo(0); }
      else if (e.key === 'End') { e.preventDefault(); goTo(SLIDE_COUNT - 1); }
    };

    let wheelLock = false;
    const onWheel = (e) => {
      e.preventDefault();
      if (wheelLock) return;
      wheelLock = true;
      if (e.deltaY > 20) next();
      else if (e.deltaY < -20) prev();
      setTimeout(() => { wheelLock = false; }, 700);
    };

    let touchY = 0;
    const onTouchStart = (e) => { touchY = e.touches[0].clientY; };
    const onTouchEnd = (e) => {
      const dy = touchY - e.changedTouches[0].clientY;
      if (Math.abs(dy) > 50) { dy > 0 ? next() : prev(); }
    };

    document.addEventListener('keydown', onKey);
    document.addEventListener('wheel', onWheel, { passive: false });
    document.addEventListener('touchstart', onTouchStart, { passive: true });
    document.addEventListener('touchend', onTouchEnd, { passive: true });

    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('wheel', onWheel);
      document.removeEventListener('touchstart', onTouchStart);
      document.removeEventListener('touchend', onTouchEnd);
    };
  }, [next, prev, goTo]);

  const goToSlide = useCallback((i) => goTo(i), [goTo]);

  // Create dots
  useEffect(() => {
    const dotsContainer = dotsRef.current;
    if (!dotsContainer) return;
    dotsContainer.innerHTML = '';
    for (let i = 0; i < SLIDE_COUNT; i++) {
      const d = document.createElement('button');
      d.className = 'dot' + (i === 0 ? ' active' : '');
      d.onclick = () => goTo(i);
      dotsContainer.appendChild(d);
    }
  }, [goTo]);

  useEffect(() => {
    update(0);
  }, [update]);

  // Set body style
  useEffect(() => {
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = ''; };
  }, []);

  return (
    <>
      <style>{`
        .pd * { margin: 0; padding: 0; box-sizing: border-box; }
        .pd { height: 100vh; width: 100vw; overflow: hidden; background: #000; color: #fff; font-family: 'Source Serif 4', 'Georgia', serif; font-weight: 300; line-height: 1.75; -webkit-font-smoothing: antialiased; position: fixed; inset: 0; z-index: 9999; }
        .pd ::selection { background: #fc1c46; color: #000; }

        .pd-deck { position: fixed; inset: 0; overflow: hidden; }
        .pd-slide {
          position: absolute; inset: 0;
          display: flex; flex-direction: column; justify-content: center;
          padding: clamp(48px, 7vw, 100px) clamp(32px, 6vw, 100px);
          opacity: 0; transform: translateY(30px);
          transition: opacity 0.5s cubic-bezier(0.16,1,0.3,1), transform 0.5s cubic-bezier(0.16,1,0.3,1);
          pointer-events: none; visibility: hidden;
        }
        .pd-slide.pd-active { opacity: 1; transform: translateY(0); pointer-events: auto; visible: visible; visibility: visible; }

        .pd-display { font-family: 'Playfair Display', 'Georgia', serif; font-weight: 700; line-height: 0.92; letter-spacing: -0.02em; }
        .pd-snum { position: absolute; bottom: 28px; right: 40px; font-family: 'Inter', sans-serif; font-size: 10px; font-weight: 400; letter-spacing: 0.18em; color: #444; z-index: 2; }
        .pd-tag { display: inline-flex; align-items: center; gap: 12px; margin-bottom: 40px; }
        .pd-tag::before { content: ''; display: inline-block; width: 32px; height: 1px; background: #fc1c46; }
        .pd-tag-t { font-family: 'Inter', sans-serif; font-size: 10px; font-weight: 500; letter-spacing: 0.22em; text-transform: uppercase; color: #fc1c46; }

        .pd-cover { text-align: center; align-items: center; }
        .pd-cover .pd-display { font-size: clamp(56px, 12vw, 160px); }
        .pd-cover-line { overflow: hidden; margin-bottom: 4px; }
        .pd-cover-line span { display: block; }
        .pd-red { color: #fc1c46; }
        .pd-cover-sub { margin-top: 40px; font-size: clamp(14px, 1.1vw, 17px); color: #666; max-width: 440px; margin-left: auto; margin-right: auto; }
        .pd-cover-actions { margin-top: 48px; }
        .pd-cover-btn { display: inline-flex; align-items: center; gap: 10px; padding: 13px 32px; background: #fc1c46; color: #000; font-family: 'Inter', sans-serif; font-size: 11px; font-weight: 600; letter-spacing: 0.12em; text-transform: uppercase; text-decoration: none; border: none; cursor: pointer; transition: all 0.35s cubic-bezier(0.16,1,0.3,1); }
        .pd-cover-btn:hover { background: #fff; }

        .pd-toc-list { list-style: none; max-width: 600px; }
        .pd-toc-item { display: flex; align-items: baseline; gap: 20px; padding: 18px 0; border-bottom: 1px solid rgba(255,255,255,0.05); cursor: pointer; transition: all 0.35s cubic-bezier(0.16,1,0.3,1); }
        .pd-toc-item:hover { padding-left: 12px; }
        .pd-toc-num { font-family: 'Playfair Display', serif; font-size: 22px; font-weight: 700; color: #fc1c46; min-width: 44px; }
        .pd-toc-title { font-family: 'Playfair Display', serif; font-size: clamp(18px, 2.2vw, 28px); font-weight: 600; color: #fff; }
        .pd-toc-desc { font-size: 12px; color: #444; margin-top: 2px; }

        .pd-stitle { font-size: clamp(40px, 7vw, 100px); margin-bottom: 12px; }
        .pd-sbody { font-size: clamp(15px, 1.3vw, 20px); color: #d0d0d0; max-width: 600px; line-height: 1.8; }

        .pd-stats { display: flex; gap: 64px; margin-top: 64px; }
        .pd-stat { text-align: left; }
        .pd-stat-big { font-family: 'Playfair Display', serif; font-size: clamp(36px, 4.5vw, 64px); font-weight: 700; color: #fc1c46; line-height: 1; }
        .pd-stat-lbl { font-family: 'Inter', sans-serif; font-size: 11px; font-weight: 500; letter-spacing: 0.15em; text-transform: uppercase; color: #666; margin-top: 6px; }
        .pd-stat-sub { font-size: 12px; color: #444; margin-top: 2px; }

        .pd-two { display: grid; grid-template-columns: 1fr 1fr; gap: 1px; background: rgba(255,255,255,0.05); margin-top: 56px; }
        .pd-card { background: #080808; padding: 56px 44px; }
        .pd-card-lbl { font-family: 'Inter', sans-serif; font-size: 10px; font-weight: 500; letter-spacing: 0.2em; text-transform: uppercase; color: #fc1c46; margin-bottom: 20px; }
        .pd-card-title { font-family: 'Playfair Display', serif; font-size: clamp(22px, 2.5vw, 36px); font-weight: 600; margin-bottom: 20px; line-height: 1.15; }
        .pd-card-items { list-style: none; margin-top: 20px; }
        .pd-card-items li { font-size: 13px; color: #666; padding: 7px 0; border-bottom: 1px solid rgba(255,255,255,0.05); }
        .pd-card-items li::before { content: '—  '; color: #444; }
        .pd-card-items li.plus::before { content: '+  '; color: #fc1c46; }

        .pd-three { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1px; background: rgba(255,255,255,0.05); margin-top: 56px; }
        .pd-step { background: #080808; padding: 48px 36px; transition: background 0.35s ease; }
        .pd-step:hover { background: #101010; }
        .pd-step-num { font-family: 'Playfair Display', serif; font-size: 56px; font-weight: 700; color: #fc1c46; opacity: 0.35; line-height: 1; margin-bottom: 28px; }
        .pd-step-title { font-family: 'Playfair Display', serif; font-size: 24px; font-weight: 600; margin-bottom: 12px; }
        .pd-step-desc { font-size: 13px; color: #666; line-height: 1.8; }

        .pd-cap { display: grid; grid-template-columns: 1fr 1fr; gap: 64px; align-items: center; margin-top: 56px; }
        .pd-cap-nbg { font-family: 'Playfair Display', serif; font-size: 100px; font-weight: 700; color: #fc1c46; opacity: 0.1; line-height: 1; position: absolute; top: -16px; left: -8px; }
        .pd-cap-title { font-family: 'Playfair Display', serif; font-size: clamp(28px, 3.5vw, 48px); font-weight: 700; margin-bottom: 6px; line-height: 1.05; }
        .pd-cap-sub { font-size: 13px; color: #fc1c46; margin-bottom: 20px; font-style: italic; }
        .pd-cap-text { font-size: 14px; color: #666; line-height: 1.8; margin-bottom: 28px; }
        .pd-cap-list { list-style: none; }
        .pd-cap-list li { font-size: 13px; color: #a0a0a0; padding: 10px 0; border-bottom: 1px solid rgba(255,255,255,0.05); display: flex; gap: 10px; }
        .pd-cap-list li::before { content: ''; display: inline-block; width: 5px; height: 5px; background: #fc1c46; border-radius: 50%; flex-shrink: 0; margin-top: 7px; }
        .pd-cap-panel { background: #080808; border: 1px solid rgba(255,255,255,0.05); padding: 36px; position: relative; overflow: hidden; }
        .pd-cap-panel::before { content: ''; position: absolute; top: 0; left: 0; width: 100%; height: 2px; background: linear-gradient(90deg, #fc1c46, transparent); }
        .pd-panel-lbl { font-family: 'Inter', sans-serif; font-size: 9px; font-weight: 500; letter-spacing: 0.22em; text-transform: uppercase; color: #444; margin-bottom: 20px; }
        .pd-panel-av { width: 40px; height: 40px; background: rgba(252,28,70,0.12); border: 1px solid rgba(252,28,70,0.18); display: flex; align-items: center; justify-content: center; font-family: 'Playfair Display', serif; font-size: 16px; font-weight: 700; color: #fc1c46; margin-bottom: 14px; }
        .pd-panel-row { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid rgba(255,255,255,0.05); font-size: 12px; }
        .pd-panel-rl { color: #444; font-family: 'Inter', sans-serif; font-size: 10px; letter-spacing: 0.1em; text-transform: uppercase; }
        .pd-panel-rv { color: #d0d0d0; }
        .pd-ch-item { display: flex; align-items: center; gap: 12px; padding: 12px 0; border-bottom: 1px solid rgba(255,255,255,0.05); transition: all 0.3s ease; }
        .pd-ch-item:hover { padding-left: 6px; }
        .pd-ch-dot { width: 6px; height: 6px; background: #fc1c46; border-radius: 50%; flex-shrink: 0; }
        .pd-ch-name { font-family: 'Inter', sans-serif; font-size: 13px; font-weight: 500; color: #fff; flex: 1; }
        .pd-ch-members { font-size: 11px; color: #444; }
        .pd-model-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
        .pd-model { background: #101010; border: 1px solid rgba(255,255,255,0.05); padding: 16px; transition: all 0.3s ease; }
        .pd-model:hover { border-color: rgba(252,28,70,0.18); }
        .pd-model-name { font-family: 'Playfair Display', serif; font-size: 16px; font-weight: 600; color: #fff; }
        .pd-model-prov { font-size: 10px; color: #fc1c46; font-family: 'Inter', sans-serif; letter-spacing: 0.1em; text-transform: uppercase; margin-top: 2px; }

        .pd-cases { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1px; background: rgba(255,255,255,0.05); margin-top: 56px; }
        .pd-case { background: #080808; padding: 36px 28px; transition: background 0.35s ease; }
        .pd-case:hover { background: #101010; }
        .pd-case-cat { font-family: 'Inter', sans-serif; font-size: 9px; font-weight: 500; letter-spacing: 0.22em; text-transform: uppercase; color: #fc1c46; margin-bottom: 14px; }
        .pd-case-title { font-family: 'Playfair Display', serif; font-size: 22px; font-weight: 600; margin-bottom: 10px; }
        .pd-case-desc { font-size: 12px; color: #666; line-height: 1.7; }

        .pd-cta { text-align: center; align-items: center; }
        .pd-cta-title { font-size: clamp(44px, 9vw, 120px); margin-bottom: 28px; }
        .pd-cta-sub { font-size: clamp(14px, 1.1vw, 17px); color: #666; max-width: 440px; margin: 0 auto 40px; line-height: 1.8; }
        .pd-cta-btn { display: inline-flex; align-items: center; gap: 10px; padding: 16px 40px; background: #fc1c46; color: #000; font-family: 'Inter', sans-serif; font-size: 12px; font-weight: 600; letter-spacing: 0.12em; text-transform: uppercase; text-decoration: none; border: none; cursor: pointer; transition: all 0.35s cubic-bezier(0.16,1,0.3,1); }
        .pd-cta-btn:hover { background: #fff; }
        .pd-cta-footer { position: absolute; bottom: 32px; left: 0; width: 100%; display: flex; justify-content: space-between; padding: 0 40px; font-family: 'Inter', sans-serif; font-size: 10px; color: #444; letter-spacing: 0.05em; }

        .pd-progress { position: fixed; top: 0; left: 0; height: 2px; background: #fc1c46; z-index: 200; transition: width 0.35s ease; }
        .pd-dots { position: fixed; right: 20px; top: 50%; transform: translateY(-50%); z-index: 200; display: flex; flex-direction: column; gap: 10px; }
        .pd-dot { width: 7px; height: 7px; border-radius: 50%; background: #444; cursor: pointer; transition: all 0.3s ease; border: none; padding: 0; }
        .pd-dot:hover { background: #a0a0a0; }
        .pd-dot.pd-active { background: #fc1c46; transform: scale(1.4); }

        .pd-hint { position: absolute; bottom: 28px; left: 50%; transform: translateX(-50%); display: flex; flex-direction: column; align-items: center; gap: 6px; animation: pdBob 2s infinite; transition: opacity 0.3s ease; }
        .pd-hint.hide { opacity: 0; }
        .pd-hint span { font-family: 'Inter', sans-serif; font-size: 9px; letter-spacing: 0.22em; text-transform: uppercase; color: #444; }
        .pd-hint svg { width: 14px; height: 20px; }
        @keyframes pdBob { 0%,100%{transform:translateX(-50%) translateY(0)} 50%{transform:translateX(-50%) translateY(6px)} }

        .pd-back { position: fixed; top: 24px; left: 24px; z-index: 300; font-family: 'Inter', sans-serif; font-size: 11px; font-weight: 500; letter-spacing: 0.12em; text-transform: uppercase; color: #444; background: none; border: none; cursor: pointer; transition: color 0.3s; display: flex; align-items: center; gap: 8px; padding: 8px 12px; }
        .pd-back:hover { color: #fc1c46; }

        @media (max-width: 768px) {
          .pd-slide { padding: 64px 20px; }
          .pd-two, .pd-three, .pd-cap, .pd-cases { grid-template-columns: 1fr; }
          .pd-stats { flex-direction: column; gap: 32px; }
          .pd-snum { bottom: 14px; right: 20px; }
          .pd-cta-footer { flex-direction: column; gap: 6px; padding: 0 20px; }
          .pd-dots { display: none; }
        }
      `}</style>

      <button className="pd-back" onClick={() => onBack ? onBack() : (window.location.hash = '#/landing')}>
        ← 返回
      </button>

      <div className="pd-progress" ref={progressRef} />
      <nav className="pd-dots" ref={dotsRef} />

      <div className="pd" ref={deckRef}>
        <div className="pd-deck" id="pd-deck">
          {/* 1 Cover */}
          <section className="pd-slide pd-cover pd-active" data-slide="0">
            <div className="pd-cover-line gsap-anim"><span className="pd-display">构建你的</span></div>
            <div className="pd-cover-line gsap-anim pd-d1"><span className="pd-display"><span className="pd-red">AI 队友</span></span></div>
            <p className="pd-cover-sub gsap-anim pd-d2">创建自定义 AI 队友，分配到频道，实时协作。</p>
            <div className="pd-cover-actions gsap-anim pd-d3">
              <button className="pd-cover-btn" onClick={() => goToSlide(1)}>开始探索 →</button>
            </div>
            <div className="pd-hint" ref={hintRef}>
              <span>滚动</span>
              <svg viewBox="0 0 14 20" fill="none"><rect x="1" y="1" width="12" height="18" rx="6" stroke="#444" strokeWidth="1"/><circle cx="7" cy="6" r="2" fill="#444"><animate attributeName="cy" values="5;11;5" dur="2s" repeatCount="indefinite"/></circle></svg>
            </div>
            <span className="pd-snum">01 / 10</span>
          </section>

          {/* 2 TOC */}
          <section className="pd-slide" data-slide="1">
            <div className="pd-tag gsap-anim"><span className="pd-tag-t">目录</span></div>
            <h2 className="pd-display gsap-anim pd-d1" style={{fontSize:'clamp(36px,5vw,72px)',marginBottom:'40px'}}>概览</h2>
            <ul className="pd-toc-list">
              <li className="pd-toc-item gsap-anim pd-d2" onClick={() => goToSlide(2)}><span className="pd-toc-num">01</span><div><div className="pd-toc-title">AI Team Hub 是什么</div><div className="pd-toc-desc">协作式 AI 团队平台</div></div></li>
              <li className="pd-toc-item gsap-anim pd-d3" onClick={() => goToSlide(3)}><span className="pd-toc-num">02</span><div><div className="pd-toc-title">当前痛点</div><div className="pd-toc-desc">单一通用助手的局限性</div></div></li>
              <li className="pd-toc-item gsap-anim pd-d4" onClick={() => goToSlide(4)}><span className="pd-toc-num">03</span><div><div className="pd-toc-title">解决思路</div><div className="pd-toc-desc">三步构建 AI 梦之队</div></div></li>
              <li className="pd-toc-item gsap-anim pd-d5" onClick={() => goToSlide(5)}><span className="pd-toc-num">04</span><div><div className="pd-toc-title">核心能力</div><div className="pd-toc-desc">自定义、频道、多模型</div></div></li>
              <li className="pd-toc-item gsap-anim pd-d6" onClick={() => goToSlide(8)}><span className="pd-toc-num">05</span><div><div className="pd-toc-title">应用场景</div><div className="pd-toc-desc">六大行业案例</div></div></li>
              <li className="pd-toc-item gsap-anim pd-d7" onClick={() => goToSlide(9)}><span className="pd-toc-num">06</span><div><div className="pd-toc-title">开始使用</div><div className="pd-toc-desc">几分钟内创建第一个队友</div></div></li>
            </ul>
            <span className="pd-snum">02 / 10</span>
          </section>

          {/* 3 What is it */}
          <section className="pd-slide" data-slide="2">
            <div className="pd-tag gsap-anim"><span className="pd-tag-t">AI Team Hub 是什么</span></div>
            <h2 className="pd-display pd-stitle gsap-anim pd-d1" style={{marginBottom:'24px'}}>协作式 AI 团队平台</h2>
            <p className="pd-sbody gsap-anim pd-d2">AI Team Hub 是一个协作式 AI 团队平台。你可以创建具有独特人格和专长的 AI 队友，将他们分配到不同的频道，让他们在实时对话中协作、讨论、解决问题。</p>
            <div className="pd-stats">
              <div className="pd-stat gsap-anim pd-d3"><div className="pd-stat-big">∞</div><div className="pd-stat-lbl">模型</div><div className="pd-stat-sub">支持任意 LLM</div></div>
              <div className="pd-stat gsap-anim pd-d4"><div className="pd-stat-big">01</div><div className="pd-stat-lbl">平台</div><div className="pd-stat-sub">统一协作入口</div></div>
              <div className="pd-stat gsap-anim pd-d5"><div className="pd-stat-big">24/7</div><div className="pd-stat-lbl">可用</div><div className="pd-stat-sub">全天候运行</div></div>
            </div>
            <span className="pd-snum">03 / 10</span>
          </section>

          {/* 4 Pain points */}
          <section className="pd-slide" data-slide="3">
            <div className="pd-tag gsap-anim"><span className="pd-tag-t">当前痛点</span></div>
            <h2 className="pd-display gsap-anim pd-d1" style={{fontSize:'clamp(36px,6vw,80px)',marginBottom:'12px'}}>大多数 AI 工具只给你</h2>
            <h2 className="pd-display gsap-anim pd-d2 pd-red" style={{fontSize:'clamp(36px,6vw,80px)'}}>一个聊天窗口</h2>
            <div className="pd-two gsap-anim pd-d3">
              <div className="pd-card">
                <div className="pd-card-lbl">现状</div>
                <div className="pd-card-title">通用助手<br/>缺乏专业深度</div>
                <ul className="pd-card-items">
                  <li>单一通用助手，无法处理复杂任务</li>
                  <li>不同工具之间无法协作</li>
                  <li>缺乏持续的上下文记忆</li>
                  <li>无法针对不同任务选择最优模型</li>
                </ul>
              </div>
              <div className="pd-card">
                <div className="pd-card-lbl">需求</div>
                <div className="pd-card-title">专业团队<br/>协同工作</div>
                <ul className="pd-card-items">
                  <li className="plus">多个专业 AI 角色协同工作</li>
                  <li className="plus">代码审查、数据分析、产品策略</li>
                  <li className="plus">实时协作与讨论</li>
                  <li className="plus">针对不同任务选择最优模型</li>
                </ul>
              </div>
            </div>
            <span className="pd-snum">04 / 10</span>
          </section>

          {/* 5 Solution */}
          <section className="pd-slide" data-slide="4">
            <div className="pd-tag gsap-anim"><span className="pd-tag-t">解决思路</span></div>
            <h2 className="pd-display gsap-anim pd-d1" style={{fontSize:'clamp(36px,6vw,80px)',marginBottom:'12px'}}>三步构建</h2>
            <h2 className="pd-display gsap-anim pd-d2 pd-red" style={{fontSize:'clamp(36px,6vw,80px)'}}>AI 梦之队</h2>
            <div className="pd-three gsap-anim pd-d3">
              <div className="pd-step">
                <div className="pd-step-num">01</div>
                <div className="pd-step-title">创建</div>
                <div className="pd-step-desc">创建 AI 队友，自定义人格、专长和系统提示词。每个队友都是独一无二的专业角色。</div>
              </div>
              <div className="pd-step">
                <div className="pd-step-num">02</div>
                <div className="pd-step-title">分配</div>
                <div className="pd-step-desc">将多个队友分配到同一频道，让他们在同一个工作空间内协作。</div>
              </div>
              <div className="pd-step">
                <div className="pd-step-num">03</div>
                <div className="pd-step-title">协作</div>
                <div className="pd-step-desc">观看 AI 队友实时讨论、辩论、解决问题。就像拥有一支全天候的梦之队。</div>
              </div>
            </div>
            <span className="pd-snum">05 / 10</span>
          </section>

          {/* 6 Capability 01 */}
          <section className="pd-slide" data-slide="5">
            <div className="pd-tag gsap-anim"><span className="pd-tag-t">核心能力 01</span></div>
            <div className="pd-cap">
              <div style={{position:'relative'}} className="gsap-anim">
                <div className="pd-cap-nbg">01</div>
                <h3 className="pd-cap-title">自定义 AI 队友</h3>
                <p className="pd-cap-sub">Custom AI Teammates</p>
                <p className="pd-cap-text">为每个 AI 队友设置独特性格和行为风格。定义专业领域，从高级软件工程师到创意策略师，每个角色都精确适配你的需求。</p>
                <ul className="pd-cap-list">
                  <li>自定义人格与行为风格</li>
                  <li>定义专业领域和技能范围</li>
                  <li>自定义系统提示词，精确控制 AI 行为</li>
                  <li>为每个队友设置头像和名称</li>
                </ul>
              </div>
              <div className="pd-cap-panel gsap-anim pd-d2">
                <div className="pd-panel-lbl">队友示例</div>
                <div className="pd-panel-av">A</div>
                <div className="pd-panel-row"><span className="pd-panel-rl">名称</span><span className="pd-panel-rv">Alice</span></div>
                <div className="pd-panel-row"><span className="pd-panel-rl">角色</span><span className="pd-panel-rv">高级工程师</span></div>
                <div className="pd-panel-row"><span className="pd-panel-rl">模型</span><span className="pd-panel-rv">GPT-4</span></div>
                <div className="pd-panel-row"><span className="pd-panel-rl">专长</span><span className="pd-panel-rv">代码审查</span></div>
                <div className="pd-panel-row"><span className="pd-panel-rl">状态</span><span className="pd-panel-rv" style={{color:'#fc1c46'}}>● 活跃</span></div>
              </div>
            </div>
            <span className="pd-snum">06 / 10</span>
          </section>

          {/* 7 Capability 02 */}
          <section className="pd-slide" data-slide="6">
            <div className="pd-tag gsap-anim"><span className="pd-tag-t">核心能力 02</span></div>
            <div className="pd-cap">
              <div style={{position:'relative'}} className="gsap-anim">
                <div className="pd-cap-nbg">02</div>
                <h3 className="pd-cap-title">基于频道的协作</h3>
                <p className="pd-cap-sub">Channel-Based Collaboration</p>
                <p className="pd-cap-text">将多个 AI 队友组织到频道中。每个频道是一个独立的工作空间，队友们在其中实时协作、讨论、解决问题。</p>
                <ul className="pd-cap-list">
                  <li>创建多个频道，按项目或团队组织</li>
                  <li>将多个队友加入同一频道</li>
                  <li>实时多 AI 对话与协作</li>
                  <li>频道级别的上下文管理</li>
                </ul>
              </div>
              <div className="pd-cap-panel gsap-anim pd-d2">
                <div className="pd-panel-lbl">活跃频道</div>
                <div className="pd-ch-item"><div className="pd-ch-dot"/><span className="pd-ch-name"># 代码审查</span><span className="pd-ch-members">3 名成员</span></div>
                <div className="pd-ch-item"><div className="pd-ch-dot"/><span className="pd-ch-name"># 数据分析</span><span className="pd-ch-members">2 名成员</span></div>
                <div className="pd-ch-item"><div className="pd-ch-dot"/><span className="pd-ch-name"># 产品策略</span><span className="pd-ch-members">4 名成员</span></div>
                <div className="pd-ch-item"><div className="pd-ch-dot"/><span className="pd-ch-name"># 安全审计</span><span className="pd-ch-members">2 名成员</span></div>
                <div style={{marginTop:'20px',paddingTop:'14px',borderTop:'1px solid rgba(255,255,255,0.05)'}}>
                  <div className="pd-panel-lbl" style={{marginBottom:'10px'}}>实时对话</div>
                  <div style={{fontSize:'12px',color:'#666',lineHeight:1.8}}>
                    <span style={{color:'#fc1c46'}}>Alice:</span> 发现认证模块有内存泄漏...<br/>
                    <span style={{color:'#fc1c46'}}>Bob:</span> 正在检查会话处理器。<br/>
                    <span style={{color:'#fc1c46'}}>Charlie:</span> 问题在第42行，缺少清理回调。
                  </div>
                </div>
              </div>
            </div>
            <span className="pd-snum">07 / 10</span>
          </section>

          {/* 8 Capability 03 */}
          <section className="pd-slide" data-slide="7">
            <div className="pd-tag gsap-anim"><span className="pd-tag-t">核心能力 03</span></div>
            <div className="pd-cap">
              <div style={{position:'relative'}} className="gsap-anim">
                <div className="pd-cap-nbg">03</div>
                <h3 className="pd-cap-title">多模型支持</h3>
                <p className="pd-cap-sub">Multi-Model Support</p>
                <p className="pd-cap-text">为每个队友选择最适合的 LLM — GPT-4、Claude、Gemini，或任何 OpenAI 兼容接口。不同的角色，不同的模型。</p>
                <ul className="pd-cap-list">
                  <li>GPT-4 — 最强大的推理能力</li>
                  <li>Claude — 长文本理解与文档处理</li>
                  <li>Gemini — 多模态与创意任务</li>
                  <li>自定义 — 支持任意 OpenAI 兼容 API</li>
                </ul>
              </div>
              <div className="pd-cap-panel gsap-anim pd-d2">
                <div className="pd-panel-lbl">支持的模型</div>
                <div className="pd-model-grid">
                  <div className="pd-model"><div className="pd-model-name">GPT-4</div><div className="pd-model-prov">OpenAI</div></div>
                  <div className="pd-model"><div className="pd-model-name">Claude</div><div className="pd-model-prov">Anthropic</div></div>
                  <div className="pd-model"><div className="pd-model-name">Gemini</div><div className="pd-model-prov">Google</div></div>
                  <div className="pd-model"><div className="pd-model-name">自定义</div><div className="pd-model-prov">任意 API</div></div>
                </div>
              </div>
            </div>
            <span className="pd-snum">08 / 10</span>
          </section>

          {/* 9 Use cases */}
          <section className="pd-slide" data-slide="8">
            <div className="pd-tag gsap-anim"><span className="pd-tag-t">应用场景</span></div>
            <h2 className="pd-display gsap-anim pd-d1" style={{fontSize:'clamp(36px,6vw,80px)',marginBottom:'12px'}}>AI 队友</h2>
            <h2 className="pd-display gsap-anim pd-d2 pd-red" style={{fontSize:'clamp(36px,6vw,80px)'}}>适用于每个角色</h2>
            <div className="pd-cases gsap-anim pd-d3">
              <div className="pd-case"><div className="pd-case-cat">工程</div><div className="pd-case-title">代码审查</div><div className="pd-case-desc">多 AI 同行评审，架构分析与代码质量检查</div></div>
              <div className="pd-case"><div className="pd-case-cat">分析</div><div className="pd-case-title">数据洞察</div><div className="pd-case-desc">实时数据分析与可视化，快速洞察业务趋势</div></div>
              <div className="pd-case"><div className="pd-case-cat">产品</div><div className="pd-case-title">产品策略</div><div className="pd-case-desc">AI 驱动的市场研究与产品规划</div></div>
              <div className="pd-case"><div className="pd-case-cat">安全</div><div className="pd-case-title">安全审计</div><div className="pd-case-desc">自动化漏洞扫描与安全报告生成</div></div>
              <div className="pd-case"><div className="pd-case-cat">设计</div><div className="pd-case-title">UX 设计</div><div className="pd-case-desc">AI 辅助界面设计与原型迭代</div></div>
              <div className="pd-case"><div className="pd-case-cat">文档</div><div className="pd-case-title">技术文档</div><div className="pd-case-desc">自动生成技术文档与 API 参考</div></div>
            </div>
            <span className="pd-snum">09 / 10</span>
          </section>

          {/* 10 CTA */}
          <section className="pd-slide pd-cta" data-slide="9">
            <div className="pd-tag gsap-anim" style={{justifyContent:'center'}}><span className="pd-tag-t">开始使用</span></div>
            <h2 className="pd-display pd-cta-title gsap-anim pd-d1">准备好构建<br/>你的 <span className="pd-red">AI 团队</span>了吗？</h2>
            <p className="pd-cta-sub gsap-anim pd-d2">几分钟内创建你的第一个 AI 队友。选择模型，编写提示词，开始协作。</p>
            <button className="pd-cta-btn gsap-anim pd-d3" onClick={() => onBack ? onBack() : (window.location.hash = '#/app')}>立即开始 →</button>
            <div className="pd-cta-footer">
              <span>© 2024–2026 AI Team Hub. 保留所有权利。</span>
            </div>
            <span className="pd-snum">10 / 10</span>
          </section>
        </div>
      </div>
    </>
  );
}
