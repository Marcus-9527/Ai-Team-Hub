import { useEffect, useRef, useState } from 'react';
import { gsap } from 'gsap';

export default function Navbar({ onEnterApp }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [blendModeNormal, setBlendModeNormal] = useState(false);
  const overlayRef = useRef(null);
  const contentRef = useRef(null);
  const btnRef = useRef(null);
  const tlRef = useRef(null);
  const itemsRef = useRef([]);
  const underlineRefs = useRef([]);

  const getBtnCenter = () => {
    if (!btnRef.current) return { x: window.innerWidth - 40, y: 40 };
    const rect = btnRef.current.getBoundingClientRect();
    return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
  };

  const getMaxRadius = () => {
    const { x, y } = getBtnCenter();
    const corners = [[0, 0], [window.innerWidth, 0], [0, window.innerHeight], [window.innerWidth, window.innerHeight]];
    return Math.max(...corners.map(([cx, cy]) => Math.sqrt((cx - x) ** 2 + (cy - y) ** 2))) * 1.2;
  };

  useEffect(() => {
    if (!overlayRef.current) return;
    if (menuOpen) {
      setBlendModeNormal(true);
      const { x, y } = getBtnCenter();
      const maxR = getMaxRadius();
      const tl = gsap.timeline({ defaults: { ease: 'power3.inOut' } });
      tlRef.current = tl;
      tl.fromTo(overlayRef.current,
        { clipPath: `circle(0px at ${x}px ${y}px)` },
        { clipPath: `circle(${maxR}px at ${x}px ${y}px)`, duration: 0.8, ease: 'power2.inOut' }, 0);
      tl.fromTo(contentRef.current, { opacity: 0 }, { opacity: 1, duration: 0.3 }, 0.5);
      tl.fromTo(itemsRef.current.filter(Boolean),
        { y: 50, opacity: 0, filter: 'blur(10px)' },
        { y: 0, opacity: 1, filter: 'blur(0px)', duration: 0.5, stagger: 0.1, ease: 'power3.out' }, 0.6);
      tl.fromTo('.menu-cta', { scale: 0.8, opacity: 0 }, { scale: 1, opacity: 1, duration: 0.4, ease: 'back.out(1.7)' }, 0.8);
      tl.fromTo('.menu-footer', { y: 15, opacity: 0 }, { y: 0, opacity: 1, duration: 0.35 }, 0.9);
    } else if (tlRef.current) {
      const { x, y } = getBtnCenter();
      const tl = gsap.timeline({ defaults: { ease: 'power3.inOut' } });
      tlRef.current = tl;
      tl.to('.menu-footer', { y: 15, opacity: 0, duration: 0.15 }, 0);
      tl.to('.menu-cta', { scale: 0.8, opacity: 0, duration: 0.15 }, 0.05);
      tl.to(itemsRef.current.filter(Boolean),
        { y: -25, opacity: 0, filter: 'blur(6px)', duration: 0.25, stagger: { each: 0.05, from: 'end' } }, 0.1);
      tl.to(contentRef.current, { opacity: 0, duration: 0.15 }, 0.15);
      tl.to(overlayRef.current,
        { clipPath: `circle(0px at ${x}px ${y}px)`, duration: 0.5, ease: 'power2.inOut',
          onComplete: () => { tlRef.current = null; setBlendModeNormal(false); } }, 0.25);
    }
  }, [menuOpen]);

  const handleNavClick = (href) => {
    setMenuOpen(false);
    setTimeout(() => { const el = document.querySelector(href); if (el) el.scrollIntoView({ behavior: 'smooth' }); }, 700);
  };

  return (
    <>
      <header style={{
        position: 'fixed', top: 0, left: 0, width: '100%', zIndex: 100,
        padding: '30px 40px', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        mixBlendMode: blendModeNormal ? 'normal' : 'difference',
        transition: 'mix-blend-mode 0.3s ease',
      }}>
        <a href="#" onClick={(e) => { e.preventDefault(); window.scrollTo({ top: 0, behavior: 'smooth' }); }}
          style={{ display: 'flex', alignItems: 'center', gap: '10px', textDecoration: 'none', color: blendModeNormal ? '#000' : '#fff', transition: 'color 0.3s ease' }}>
          <div style={{ width: '32px', height: '32px', background: '#fc1c46', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '14px', fontWeight: 700, color: '#000', letterSpacing: '-0.02em' }}>TL</div>
          <span style={{ fontSize: '14px', fontWeight: 500, letterSpacing: '0.02em' }}>AI Team Hub</span>
        </a>

        <button ref={btnRef} onClick={() => setMenuOpen(!menuOpen)}
          style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '8px', display: 'flex', flexDirection: 'column', gap: '5px', alignItems: 'flex-end', zIndex: 101, position: 'relative' }}
          aria-label="menu">
          <span style={{ display: 'block', width: '24px', height: '1.5px', background: blendModeNormal ? '#000' : '#fff', transform: menuOpen ? 'rotate(45deg) translate(3px, 3px)' : 'none', transition: 'transform 0.4s cubic-bezier(0.16, 1, 0.3, 1), background 0.4s ease' }} />
          <span style={{ display: 'block', width: '18px', height: '1.5px', background: blendModeNormal ? '#000' : '#fff', opacity: menuOpen ? 0 : 1, transition: 'opacity 0.3s ease, background 0.4s ease' }} />
          <span style={{ display: 'block', width: '24px', height: '1.5px', background: blendModeNormal ? '#000' : '#fff', transform: menuOpen ? 'rotate(-45deg) translate(3px, -3px)' : 'none', transition: 'transform 0.4s cubic-bezier(0.16, 1, 0.3, 1), background 0.4s ease' }} />
        </button>
      </header>

      <div ref={overlayRef} style={{
        position: 'fixed', top: 0, left: 0, width: '100%', height: '100%', background: '#fff', zIndex: 99,
        clipPath: 'circle(0px at 100% 0%)', display: 'flex', alignItems: 'center', justifyContent: 'center',
        overflow: 'hidden', pointerEvents: menuOpen ? 'auto' : 'none',
      }}>
        <div ref={contentRef} style={{ textAlign: 'center', opacity: 0, position: 'relative', zIndex: 1 }}>
          <nav>
            {['Features', 'How It Works', 'About'].map((label, i) => (
              <div key={label} ref={el => itemsRef.current[i] = el} style={{ marginBottom: '24px' }}>
                <a href={`#${label.toLowerCase().replace(' ', '')}`}
                  onClick={(e) => { e.preventDefault(); handleNavClick(label === 'Features' ? '#features' : label === 'How It Works' ? '#how' : '#about'); }}
                  style={{ fontSize: 'clamp(48px, 7vw, 96px)', fontWeight: 700, color: '#000', textDecoration: 'none', lineHeight: 1.05, letterSpacing: '-0.03em', display: 'inline-block', position: 'relative', paddingBottom: '8px', cursor: 'pointer' }}
                  onMouseEnter={(e) => {
                    const u = underlineRefs.current[i]; if (u) gsap.to(u, { scaleX: 1, duration: 0.5, ease: 'power3.inOut' });
                    gsap.to(e.currentTarget, { x: 12, duration: 0.4, ease: 'power3.out' });
                  }}
                  onMouseLeave={(e) => {
                    const u = underlineRefs.current[i]; if (u) gsap.to(u, { scaleX: 0, duration: 0.35, ease: 'power2.in' });
                    gsap.to(e.currentTarget, { x: 0, duration: 0.35, ease: 'power3.out' });
                  }}>
                  {label}
                  <span ref={el => underlineRefs.current[i] = el} style={{ position: 'absolute', bottom: 0, left: 0, width: '100%', height: '3px', background: '#000', transform: 'scaleX(0)', transformOrigin: 'left center', pointerEvents: 'none' }} />
                </a>
              </div>
            ))}
          </nav>
          <div className="menu-cta" style={{ marginTop: '56px' }}>
            <button onClick={() => { setMenuOpen(false); onEnterApp(); }}
              style={{ background: '#fc1c46', color: '#fff', border: 'none', padding: '20px 52px', fontSize: '13px', fontWeight: 600, cursor: 'pointer', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
              Launch App
            </button>
          </div>
        </div>
        <div className="menu-footer" style={{ position: 'absolute', bottom: '40px', left: '40px', right: '40px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ fontSize: '11px', letterSpacing: '0.15em', textTransform: 'uppercase', color: '#999' }}>AI-Powered Team Collaboration</span>
          <div style={{ display: 'flex', gap: '24px' }}>
            {['GitHub', 'Twitter', 'Discord'].map((s) => (
              <a key={s} href="#" onClick={(e) => e.preventDefault()}
                style={{ fontSize: '11px', letterSpacing: '0.15em', textTransform: 'uppercase', color: '#999', textDecoration: 'none', transition: 'color 0.3s ease' }}
                onMouseEnter={(e) => e.target.style.color = '#fc1c46'}
                onMouseLeave={(e) => e.target.style.color = '#999'}>
                {s}
              </a>
            ))}
          </div>
        </div>
      </div>
    </>
  );
}
