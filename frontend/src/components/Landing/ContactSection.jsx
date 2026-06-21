import { useEffect, useRef } from 'react';
import { gsap } from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';

gsap.registerPlugin(ScrollTrigger);

export default function ContactSection({ onEnterApp }) {
  const sectionRef = useRef(null);
  const pinRef = useRef(null);
  const bgRef = useRef(null);
  const labelRef = useRef(null);
  const titleRef = useRef(null);
  const descRef = useRef(null);
  const btnRef = useRef(null);
  const footerRef = useRef(null);

  useEffect(() => {
    const ctx = gsap.context(() => {
      ScrollTrigger.create({ trigger: pinRef.current, start: 'top top', end: '+=100%', pin: true, pinSpacing: true });
      gsap.to(bgRef.current, { y: 80, ease: 'none', scrollTrigger: { trigger: pinRef.current, start: 'top bottom', end: 'bottom top', scrub: 0.6 } });
      gsap.fromTo(labelRef.current, { y: -20, opacity: 0, filter: 'blur(8px)' },
        { y: 0, opacity: 1, filter: 'blur(0px)', ease: 'none', scrollTrigger: { trigger: pinRef.current, start: 'top 80%', end: 'top 40%', scrub: 0.5 } });
      gsap.fromTo(titleRef.current, { y: 120, opacity: 0, scale: 0.92, filter: 'blur(8px)' },
        { y: 0, opacity: 1, scale: 1, filter: 'blur(0px)', ease: 'none', scrollTrigger: { trigger: pinRef.current, start: 'top 70%', end: 'center center', scrub: 0.4 } });
      gsap.fromTo(descRef.current, { y: 60, opacity: 0, filter: 'blur(6px)' },
        { y: 0, opacity: 1, filter: 'blur(0px)', ease: 'none', scrollTrigger: { trigger: pinRef.current, start: 'top 60%', end: 'center 20%', scrub: 0.5 } });
      gsap.fromTo(btnRef.current, { y: 40, opacity: 0, scale: 0.85 },
        { y: 0, opacity: 1, scale: 1, ease: 'none', scrollTrigger: { trigger: pinRef.current, start: 'top 50%', end: 'center 10%', scrub: 0.6 } });
      gsap.to(btnRef.current, { boxShadow: '0 0 40px rgba(252,28,70,0.4), 0 0 80px rgba(252,28,70,0.15)', duration: 1.5, yoyo: true, repeat: -1, ease: 'sine.inOut' });
      gsap.fromTo(footerRef.current, { y: 40, opacity: 0 },
        { y: 0, opacity: 1, ease: 'none', scrollTrigger: { trigger: footerRef.current, start: 'top 90%', end: 'top 60%', scrub: 0.5 } });
    }, sectionRef);
    return () => ctx.revert();
  }, []);

  return (
    <div ref={sectionRef}>
      <section ref={pinRef} style={{ position: 'relative', minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden', background: '#000' }}>
        <div ref={bgRef} style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', pointerEvents: 'none' }}>
          <div style={{ width: '600px', height: '600px', borderRadius: '50%', background: 'radial-gradient(circle, rgba(252,28,70,0.06) 0%, transparent 70%)' }} />
        </div>
        <div style={{ position: 'relative', zIndex: 1, textAlign: 'center', padding: '0 2rem', width: '100%' }}>
          <div ref={labelRef} style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: '16px', marginBottom: '48px' }}>
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
              <path d="M4 12h12m0 0l-4-4m4 4l-4 4" stroke="#fc1c46" strokeWidth="1.5" strokeLinecap="square" />
            </svg>
            <span style={{ fontSize: '11px', letterSpacing: '0.2em', textTransform: 'uppercase', color: '#fc1c46', fontWeight: 500 }}>
              Get Started
            </span>
          </div>
          <h2 ref={titleRef} style={{ fontSize: 'clamp(40px, 6vw, 96px)', fontWeight: 700, lineHeight: 1.1, color: '#fff', marginBottom: '32px', letterSpacing: '-0.03em', textAlign: 'center' }}>
            Ready to build<br />your AI team?
          </h2>
          <p ref={descRef} style={{ fontSize: '16px', lineHeight: 1.7, color: 'rgba(255,255,255,0.45)', maxWidth: '480px', margin: '0 auto 48px', fontWeight: 400, textAlign: 'center' }}>
            Create your first AI teammate in minutes. Choose a model, write a prompt, and start collaborating.
          </p>
          <button ref={btnRef} onClick={() => onEnterApp()}
            style={{ background: '#fc1c46', color: '#fff', border: 'none', borderRadius: '0', padding: '22px 56px', fontSize: '13px', fontWeight: 600, cursor: 'pointer', textTransform: 'uppercase', letterSpacing: '0.08em', transition: 'background 0.3s ease', display: 'inline-block' }}
            onMouseEnter={(e) => e.target.style.background = '#e0163a'}
            onMouseLeave={(e) => e.target.style.background = '#fc1c46'}>
            Launch App
          </button>
        </div>
      </section>

      <footer ref={footerRef} style={{ background: '#000', padding: '80px 0 40px', borderTop: '1px solid rgba(255,255,255,0.06)' }}>
        <div style={{ maxWidth: '90rem', margin: '0 auto', padding: '0 3.75rem' }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '40px', marginBottom: '60px' }}>
            <div>
              <h4 style={{ fontSize: '11px', letterSpacing: '0.2em', textTransform: 'uppercase', color: '#4c4c4c', fontWeight: 500, marginBottom: '20px' }}>Navigation</h4>
              <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
                {['Features', 'How It Works', 'Launch App'].map((item) => (
                  <li key={item} style={{ marginBottom: '10px' }}>
                    <a href="#" onClick={(e) => { e.preventDefault(); onEnterApp(); }}
                      style={{ fontSize: '14px', color: '#ccc', textDecoration: 'none' }}>
                      {item}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <h4 style={{ fontSize: '11px', letterSpacing: '0.2em', textTransform: 'uppercase', color: '#4c4c4c', fontWeight: 500, marginBottom: '20px' }}>Connect</h4>
              <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
                {['GitHub', 'Twitter', 'Discord'].map((item) => (
                  <li key={item} style={{ marginBottom: '10px' }}>
                    <a href="#" onClick={(e) => e.preventDefault()} style={{ fontSize: '14px', color: '#ccc', textDecoration: 'none' }}>{item}</a>
                  </li>
                ))}
              </ul>
            </div>
            <div style={{ gridColumn: 'span 2' }}>
              <h4 style={{ fontSize: '11px', letterSpacing: '0.2em', textTransform: 'uppercase', color: '#4c4c4c', fontWeight: 500, marginBottom: '20px' }}>Stay Updated</h4>
              <form onSubmit={(e) => e.preventDefault()} style={{ display: 'flex', alignItems: 'center', maxWidth: '400px' }}>
                <input type="email" placeholder="Email address"
                  style={{ flex: 1, background: 'transparent', border: 'none', borderBottom: '1px solid rgba(255,255,255,0.15)', padding: '12px 0', color: '#fff', fontSize: '14px', outline: 'none', fontFamily: 'inherit' }} />
                <button type="submit" style={{ background: 'none', border: 'none', borderBottom: '1px solid rgba(255,255,255,0.15)', padding: '12px 16px', cursor: 'pointer', color: '#fc1c46' }}>
                  <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                    <path d="M2 8h12m0 0l-4-4m4 4l-4 4" stroke="currentColor" strokeWidth="1.2" strokeLinecap="square" />
                  </svg>
                </button>
              </form>
            </div>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingTop: '40px', borderTop: '1px solid rgba(255,255,255,0.04)' }}>
            <p style={{ fontSize: '12px', color: '#4c4c4c' }}>© 2024–2026 / AI Team Hub. All rights reserved.</p>
            <p style={{ fontSize: '12px', color: '#4c4c4c' }}>Built with ♥ for AI-powered teams</p>
          </div>
        </div>
      </footer>
    </div>
  );
}
