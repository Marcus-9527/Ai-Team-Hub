import { useEffect, useRef } from 'react';
import { gsap } from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { useTranslation } from '../../i18n';

gsap.registerPlugin(ScrollTrigger);

const CAPS = [
  { num: '1', titleKey: 'landing.capabilities.1.title', descKey: 'landing.capabilities.1.desc' },
  { num: '2', titleKey: 'landing.capabilities.2.title', descKey: 'landing.capabilities.2.desc' },
  { num: '3', titleKey: 'landing.capabilities.3.title', descKey: 'landing.capabilities.3.desc' },
  { num: '4', titleKey: 'landing.capabilities.4.title', descKey: 'landing.capabilities.4.desc' },
];

export default function CapabilitiesSection() {
  const t = useTranslation();
  const sectionRef = useRef(null);
  const labelRef = useRef(null);
  const colsRef = useRef([]);
  const numbersRef = useRef([]);
  const titlesRef = useRef([]);
  const descsRef = useRef([]);

  useEffect(() => {
    const ctx = gsap.context(() => {
      gsap.fromTo(labelRef.current, { x: -40, opacity: 0, filter: 'blur(8px)' },
        { x: 0, opacity: 1, filter: 'blur(0px)', ease: 'power3.out', duration: 0.8, scrollTrigger: { trigger: sectionRef.current, start: 'top 85%', toggleActions: 'play none none reverse' } });

      const cols = colsRef.current.filter(Boolean);
      cols.forEach((col, i) => {
        gsap.fromTo(col, { y: 80, opacity: 0, filter: 'blur(12px)' },
          { y: 0, opacity: 1, filter: 'blur(0px)', ease: 'power3.out', duration: 1.0, delay: i * 0.12, scrollTrigger: { trigger: sectionRef.current, start: 'top 75%', toggleActions: 'play none none reverse' } });
      });

      numbersRef.current.filter(Boolean).forEach((num, i) => {
        gsap.fromTo(num, { scale: 0.8, opacity: 0, filter: 'blur(16px)' },
          { scale: 1, opacity: 1, filter: 'blur(0px)', ease: 'back.out(1.7)', duration: 0.9, delay: i * 0.1 + 0.2, scrollTrigger: { trigger: sectionRef.current, start: 'top 70%', toggleActions: 'play none none reverse' } });
      });

      titlesRef.current.filter(Boolean).forEach((title, i) => {
        gsap.fromTo(title, { y: 30, opacity: 0, filter: 'blur(6px)' },
          { y: 0, opacity: 1, filter: 'blur(0px)', ease: 'power2.out', duration: 0.6, delay: i * 0.08 + 0.4, scrollTrigger: { trigger: sectionRef.current, start: 'top 65%', toggleActions: 'play none none reverse' } });
      });

      descsRef.current.filter(Boolean).forEach((desc, i) => {
        gsap.fromTo(desc, { y: 20, opacity: 0 },
          { y: 0, opacity: 1, ease: 'power2.out', duration: 0.5, delay: i * 0.06 + 0.6, scrollTrigger: { trigger: sectionRef.current, start: 'top 60%', toggleActions: 'play none none reverse' } });
      });

      cols.forEach((col, i) => {
        const direction = i % 2 === 0 ? 1 : -1;
        gsap.to(col, { y: direction * 30, ease: 'none', scrollTrigger: { trigger: sectionRef.current, start: 'top bottom', end: 'bottom top', scrub: 0.8 } });
      });
    }, sectionRef);
    return () => ctx.revert();
  }, []);

  return (
    <section ref={sectionRef} style={{ padding: '160px 0 200px', overflow: 'hidden' }}>
      <div style={{ maxWidth: '90rem', margin: '0 auto', padding: '0 3.75rem' }}>
        <div ref={labelRef} style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '96px' }}>
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <path d="M3 8h10m0 0l-3-3m3 3l-3 3" stroke="#fc1c46" strokeWidth="1.5" strokeLinecap="square" />
          </svg>
          <span style={{ fontSize: '11px', letterSpacing: '0.2em', textTransform: 'uppercase', color: '#fc1c46', fontWeight: 500 }}>
            {t('landing.capabilities.overline')}
          </span>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '0' }}>
          {CAPS.map((cap, i) => (
            <div key={cap.num} ref={el => colsRef.current[i] = el}
              style={{ paddingLeft: i === 0 ? 0 : '60px', paddingRight: i === 3 ? 0 : '60px', borderRight: i < 3 ? '1px solid rgba(255,255,255,0.18)' : 'none', paddingBottom: '80px' }}>
              <div ref={el => numbersRef.current[i] = el}
                style={{ fontSize: 'clamp(100px, 12vw, 180px)', fontWeight: 700, lineHeight: 0.85, fontFamily: "'Neue Haas Grotesk', 'Helvetica Neue', 'Helvetica', 'Arial Black', sans-serif", letterSpacing: '-0.05em', color: '#fff', marginBottom: '48px', textTransform: 'uppercase', transform: 'scaleX(0.9)', transformOrigin: 'left center' }}>
                {cap.num}
              </div>
              <h3 ref={el => titlesRef.current[i] = el}
                style={{ fontSize: 'clamp(15px, 1.2vw, 20px)', fontWeight: 600, lineHeight: 1.3, marginBottom: '8px', color: '#fff', letterSpacing: '-0.01em' }}>
                {t(cap.titleKey)}
              </h3>
              <p ref={el => descsRef.current[i] = el}
                style={{ fontSize: '13px', lineHeight: 1.75, color: 'rgba(255,255,255,0.35)', fontWeight: 400 }}>
                {t(cap.descKey)}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
