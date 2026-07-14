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

      <button className="pd-back" onClick={() => onBack ? onBack() : (window.location.hash = '#/')}>
        ← Back
      </button>

      <div className="pd-progress" ref={progressRef} />
      <nav className="pd-dots" ref={dotsRef} />

      <div className="pd" ref={deckRef}>
        <div className="pd-deck" id="pd-deck">
          {/* 1 Cover */}
          <section className="pd-slide pd-cover pd-active" data-slide="0">
            <div className="pd-cover-line gsap-anim"><span className="pd-display">构建你的</span></div>
            <div className="pd-cover-line gsap-anim pd-d1"><span className="pd-display"><span className="pd-red">AI Team</span></span></div>
            <p className="pd-cover-sub gsap-anim pd-d2">Create custom teammates, add them to channels, collaborate in real time.</p>
            <div className="pd-cover-actions gsap-anim pd-d3">
              <button className="pd-cover-btn" onClick={() => goToSlide(1)}>Start Exploring →</button>
            </div>
            <div className="pd-hint" ref={hintRef}>
              <span>Scroll</span>
              <svg viewBox="0 0 14 20" fill="none"><rect x="1" y="1" width="12" height="18" rx="6" stroke="#444" strokeWidth="1"/><circle cx="7" cy="6" r="2" fill="#444"><animate attributeName="cy" values="5;11;5" dur="2s" repeatCount="indefinite"/></circle></svg>
            </div>
            <span className="pd-snum">01 / 10</span>
          </section>

          {/* 2 TOC */}
          <section className="pd-slide" data-slide="1">
            <div className="pd-tag gsap-anim"><span className="pd-tag-t">Contents</span></div>
            <h2 className="pd-display gsap-anim pd-d1" style={{fontSize:'clamp(36px,5vw,72px)',marginBottom:'40px'}}>Overview</h2>
            <ul className="pd-toc-list">
              <li className="pd-toc-item gsap-anim pd-d2" onClick={() => goToSlide(2)}><span className="pd-toc-num">01</span><div><div className="pd-toc-title">What is AI Team Hub</div><div className="pd-toc-desc">AI Team Collaboration Platform</div></div></li>
              <li className="pd-toc-item gsap-anim pd-d3" onClick={() => goToSlide(3)}><span className="pd-toc-num">02</span><div><div className="pd-toc-title">The Problem</div><div className="pd-toc-desc">The limits of a single general-purpose assistant</div></div></li>
              <li className="pd-toc-item gsap-anim pd-d4" onClick={() => goToSlide(4)}><span className="pd-toc-num">03</span><div><div className="pd-toc-title">How It Works</div><div className="pd-toc-desc">Three steps to build your team</div></div></li>
              <li className="pd-toc-item gsap-anim pd-d5" onClick={() => goToSlide(5)}><span className="pd-toc-num">04</span><div><div className="pd-toc-title">Capabilities</div><div className="pd-toc-desc">Customization, channels, multi-model</div></div></li>
              <li className="pd-toc-item gsap-anim pd-d6" onClick={() => goToSlide(8)}><span className="pd-toc-num">05</span><div><div className="pd-toc-title">Use Cases</div><div className="pd-toc-desc">Six industry examples</div></div></li>
              <li className="pd-toc-item gsap-anim pd-d7" onClick={() => goToSlide(9)}><span className="pd-toc-num">06</span><div><div className="pd-toc-title">Get Started</div><div className="pd-toc-desc">Create your first teammate in minutes</div></div></li>
            </ul>
            <span className="pd-snum">02 / 10</span>
          </section>

          {/* 3 What is it */}
          <section className="pd-slide" data-slide="2">
            <div className="pd-tag gsap-anim"><span className="pd-tag-t">What is AI Team Hub</span></div>
            <h2 className="pd-display pd-stitle gsap-anim pd-d1" style={{marginBottom:'24px'}}>AI Team Collaboration Platform</h2>
            <p className="pd-sbody gsap-anim pd-d2">AI Team Hub is a collaboration workspace where you create custom teammates, assign them roles, and bring them together in channels for real-time teamwork.</p>
            <div className="pd-stats">
              <div className="pd-stat gsap-anim pd-d3"><div className="pd-stat-big">∞</div><div className="pd-stat-lbl">Models</div><div className="pd-stat-sub">Any LLM supported</div></div>
              <div className="pd-stat gsap-anim pd-d4"><div className="pd-stat-big">01</div><div className="pd-stat-lbl">Platform</div><div className="pd-stat-sub">Unified collaboration hub</div></div>
              <div className="pd-stat gsap-anim pd-d5"><div className="pd-stat-big">24/7</div><div className="pd-stat-lbl">Available</div><div className="pd-stat-sub">Runs 24/7</div></div>
            </div>
            <span className="pd-snum">03 / 10</span>
          </section>

          {/* 4 Pain points */}
          <section className="pd-slide" data-slide="3">
            <div className="pd-tag gsap-anim"><span className="pd-tag-t">The Problem</span></div>
            <h2 className="pd-display gsap-anim pd-d1" style={{fontSize:'clamp(36px,6vw,80px)',marginBottom:'12px'}}>Most AI tools give you</h2>
            <h2 className="pd-display gsap-anim pd-d2 pd-red" style={{fontSize:'clamp(36px,6vw,80px)'}}>one chat window</h2>
            <div className="pd-two gsap-anim pd-d3">
              <div className="pd-card">
                <div className="pd-card-lbl">Today</div>
                <div className="pd-card-title">General assistant<br/>lacks depth</div>
                <ul className="pd-card-items">
                  <li>One general assistant can't handle complex tasks</li>
                  <li>No collaboration between tools</li>
                  <li>No persistent context or memory</li>
                  <li>Can't pick the best model for each task</li>
                </ul>
              </div>
              <div className="pd-card">
                <div className="pd-card-lbl">What you need</div>
                <div className="pd-card-title">Specialist team<br/>working together</div>
                <ul className="pd-card-items">
                  <li className="plus">Multiple specialist AI roles working together</li>
                  <li className="plus">Code review, data analysis, product strategy</li>
                  <li className="plus">Real-time collaboration and discussion</li>
                  <li className="plus">Best model selected for each task</li>
                </ul>
              </div>
            </div>
            <span className="pd-snum">04 / 10</span>
          </section>

          {/* 5 Solution */}
          <section className="pd-slide" data-slide="4">
            <div className="pd-tag gsap-anim"><span className="pd-tag-t">How It Works</span></div>
            <h2 className="pd-display gsap-anim pd-d1" style={{fontSize:'clamp(36px,6vw,80px)',marginBottom:'12px'}}>Build in 3 steps</h2>
            <h2 className="pd-display gsap-anim pd-d2 pd-red" style={{fontSize:'clamp(36px,6vw,80px)'}}>Your AI Team</h2>
            <div className="pd-three gsap-anim pd-d3">
              <div className="pd-step">
                <div className="pd-step-num">01</div>
                <div className="pd-step-title">Create</div>
                <div className="pd-step-desc">Create teammates with custom personalities and roles. Each one is a unique professional persona.</div>
              </div>
              <div className="pd-step">
                <div className="pd-step-num">02</div>
                <div className="pd-step-title">Assign</div>
                <div className="pd-step-desc">Assign multiple teammates to the same channel, where they collaborate in a shared workspace.</div>
              </div>
              <div className="pd-step">
                <div className="pd-step-num">03</div>
                <div className="pd-step-title">Collaborate</div>
                <div className="pd-step-desc">Watch teammates discuss, debate, and solve problems in real time. Like having a full-time team ready for anything.</div>
              </div>
            </div>
            <span className="pd-snum">05 / 10</span>
          </section>

          {/* 6 Capability 01 */}
          <section className="pd-slide" data-slide="5">
            <div className="pd-tag gsap-anim"><span className="pd-tag-t">Capabilities 01</span></div>
            <div className="pd-cap">
              <div style={{position:'relative'}} className="gsap-anim">
                <div className="pd-cap-nbg">01</div>
                <h3 className="pd-cap-title">Custom Teammates</h3>
                <p className="pd-cap-sub">Custom AI Teammates</p>
                <p className="pd-cap-text">Set unique personalities and behavior styles for each teammate. From senior engineers to creative strategists, every role is tailored to your needs.</p>
                <ul className="pd-cap-list">
                  <li>Custom personality and behavior style</li>
                  <li>Define expertise and skill range</li>
                  <li>Custom system prompts for precise behavior control</li>
                  <li>Set avatar and name for each teammate</li>
                </ul>
              </div>
              <div className="pd-cap-panel gsap-anim pd-d2">
                <div className="pd-panel-lbl">Teammate Example</div>
                <div className="pd-panel-av">A</div>
                <div className="pd-panel-row"><span className="pd-panel-rl">Name</span><span className="pd-panel-rv">Alice</span></div>
                <div className="pd-panel-row"><span className="pd-panel-rl">Role</span><span className="pd-panel-rv">Senior Engineer</span></div>
                <div className="pd-panel-row"><span className="pd-panel-rl">Model</span><span className="pd-panel-rv">GPT-4</span></div>
                <div className="pd-panel-row"><span className="pd-panel-rl">Expertise</span><span className="pd-panel-rv">Code Review</span></div>
                <div className="pd-panel-row"><span className="pd-panel-rl">Status</span><span className="pd-panel-rv" style={{color:'#fc1c46'}}>● Active</span></div>
              </div>
            </div>
            <span className="pd-snum">06 / 10</span>
          </section>

          {/* 7 Capability 02 */}
          <section className="pd-slide" data-slide="6">
            <div className="pd-tag gsap-anim"><span className="pd-tag-t">Capabilities 02</span></div>
            <div className="pd-cap">
              <div style={{position:'relative'}} className="gsap-anim">
                <div className="pd-cap-nbg">02</div>
                <h3 className="pd-cap-title">Channel-Based Collaboration</h3>
                <p className="pd-cap-sub">Channel-Based Collaboration</p>
                <p className="pd-cap-text">Organize multiple teammates into channels. Each channel is an independent workspace where your team collaborates in real time.</p>
                <ul className="pd-cap-list">
                  <li>Create multiple channels, organized by project or team</li>
                  <li>Add multiple teammates to the same channel</li>
                  <li>Real-time multi-AI conversation and collaboration</li>
                  <li>Channel-level context management</li>
                </ul>
              </div>
              <div className="pd-cap-panel gsap-anim pd-d2">
                <div className="pd-panel-lbl">Active Channels</div>
                <div className="pd-ch-item"><div className="pd-ch-dot"/><span className="pd-ch-name"># code-review</span><span className="pd-ch-members">3 members</span></div>
                <div className="pd-ch-item"><div className="pd-ch-dot"/><span className="pd-ch-name"># data-analysis</span><span className="pd-ch-members">2 members</span></div>
                <div className="pd-ch-item"><div className="pd-ch-dot"/><span className="pd-ch-name"># product-strategy</span><span className="pd-ch-members">4 members</span></div>
                <div className="pd-ch-item"><div className="pd-ch-dot"/><span className="pd-ch-name"># security-audit</span><span className="pd-ch-members">2 members</span></div>
                <div style={{marginTop:'20px',paddingTop:'14px',borderTop:'1px solid rgba(255,255,255,0.05)'}}>
                  <div className="pd-panel-lbl" style={{marginBottom:'10px'}}>Real-Time Conversation</div>
                  <div style={{fontSize:'12px',color:'#666',lineHeight:1.8}}>
                    <span style={{color:'#fc1c46'}}>Alice:</span> Found a memory leak in the auth module...<br/>
                    <span style={{color:'#fc1c46'}}>Bob:</span> Checking the session handler.<br/>
                    <span style={{color:'#fc1c46'}}>Charlie:</span> It's on line 42, missing cleanup callback.
                  </div>
                </div>
              </div>
            </div>
            <span className="pd-snum">07 / 10</span>
          </section>

          {/* 8 Capability 03 */}
          <section className="pd-slide" data-slide="7">
            <div className="pd-tag gsap-anim"><span className="pd-tag-t">Capabilities 03</span></div>
            <div className="pd-cap">
              <div style={{position:'relative'}} className="gsap-anim">
                <div className="pd-cap-nbg">03</div>
                <h3 className="pd-cap-title">Multi-Model Support</h3>
                <p className="pd-cap-sub">Multi-Model Support</p>
                <p className="pd-cap-text">Choose the best LLM for each teammate — GPT-4, Claude, Gemini, or any OpenAI-compatible API. The right model for the right role.</p>
                <ul className="pd-cap-list">
                  <li>GPT-4 — Most powerful reasoning</li>
                  <li>Claude — Long-text understanding and document processing</li>
                  <li>Gemini — Multimodal and creative tasks</li>
                  <li>Custom — Any OpenAI-compatible API</li>
                </ul>
              </div>
              <div className="pd-cap-panel gsap-anim pd-d2">
                <div className="pd-panel-lbl">Supported Models</div>
                <div className="pd-model-grid">
                  <div className="pd-model"><div className="pd-model-name">GPT-4</div><div className="pd-model-prov">OpenAI</div></div>
                  <div className="pd-model"><div className="pd-model-name">Claude</div><div className="pd-model-prov">Anthropic</div></div>
                  <div className="pd-model"><div className="pd-model-name">Gemini</div><div className="pd-model-prov">Google</div></div>
                  <div className="pd-model"><div className="pd-model-name">Custom</div><div className="pd-model-prov">Any API</div></div>
                </div>
              </div>
            </div>
            <span className="pd-snum">08 / 10</span>
          </section>

          {/* 9 Use cases */}
          <section className="pd-slide" data-slide="8">
            <div className="pd-tag gsap-anim"><span className="pd-tag-t">Use Cases</span></div>
            <h2 className="pd-display gsap-anim pd-d1" style={{fontSize:'clamp(36px,6vw,80px)',marginBottom:'12px'}}>Your Team</h2>
            <h2 className="pd-display gsap-anim pd-d2 pd-red" style={{fontSize:'clamp(36px,6vw,80px)'}}>for every role</h2>
            <div className="pd-cases gsap-anim pd-d3">
              <div className="pd-case"><div className="pd-case-cat">Engineering</div><div className="pd-case-title">Code Review</div><div className="pd-case-desc">Multi-AI peer review, architecture analysis, and code quality checks</div></div>
              <div className="pd-case"><div className="pd-case-cat">Analytics</div><div className="pd-case-title">Data Insights</div><div className="pd-case-desc">Real-time data analysis and visualization, fast business trend insights</div></div>
              <div className="pd-case"><div className="pd-case-cat">Product</div><div className="pd-case-title">Product Strategy</div><div className="pd-case-desc">AI-driven market research and product planning</div></div>
              <div className="pd-case"><div className="pd-case-cat">Security</div><div className="pd-case-title">Security Audit</div><div className="pd-case-desc">Automated vulnerability scanning and security report generation</div></div>
              <div className="pd-case"><div className="pd-case-cat">Design</div><div className="pd-case-title">UX Design</div><div className="pd-case-desc">AI-assisted interface design and prototype iteration</div></div>
              <div className="pd-case"><div className="pd-case-cat">Docs</div><div className="pd-case-title">Technical Docs</div><div className="pd-case-desc">Auto-generated technical documentation and API references</div></div>
            </div>
            <span className="pd-snum">09 / 10</span>
          </section>

          {/* 10 CTA */}
          <section className="pd-slide pd-cta" data-slide="9">
            <div className="pd-tag gsap-anim" style={{justifyContent:'center'}}><span className="pd-tag-t">开始使用</span></div>
            <h2 className="pd-display pd-cta-title gsap-anim pd-d1">准备好构建<br/>你的 <span className="pd-red">AI 团队</span>了吗？</h2>
            <p className="pd-cta-sub gsap-anim pd-d2">Create your first teammate in minutes. Choose a model, write a personality prompt, and start collaborating.</p>
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
