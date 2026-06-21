import { useEffect, useRef } from 'react';
import { gsap } from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';

gsap.registerPlugin(ScrollTrigger);

function SplitText({ text, className, style, stagger = 0.03, delay = 0 }) {
  const ref = useRef(null);
  useEffect(() => {
    if (!ref.current) return;
    const el = ref.current;
    const words = text.split(' ').map((word, i) => {
      const span = document.createElement('span');
      span.textContent = word + (i < text.split(' ').length - 1 ? '\u00A0' : '');
      span.style.display = 'inline-block';
      span.style.opacity = '0';
      span.style.transform = 'translateY(20px)';
      span.style.filter = 'blur(4px)';
      el.appendChild(span);
      return span;
    });
    const tl = gsap.timeline({ scrollTrigger: { trigger: el, start: 'top 80%', toggleActions: 'play none none reverse' } });
    tl.to(words, { opacity: 1, y: 0, filter: 'blur(0px)', ease: 'power3.out', duration: 0.5, stagger });
    return () => { tl.kill(); el.innerHTML = ''; };
  }, [text, stagger]);
  return <span ref={ref} className={className} style={style} />;
}

export default function AboutSection() {
  const sectionRef = useRef(null);
  const labelRef = useRef(null);
  const linkRef = useRef(null);

  useEffect(() => {
    const ctx = gsap.context(() => {
      gsap.fromTo(labelRef.current, { x: -30, opacity: 0, filter: 'blur(6px)' },
        { x: 0, opacity: 1, filter: 'blur(0px)', ease: 'power3.out', duration: 0.7, scrollTrigger: { trigger: sectionRef.current, start: 'top 85%', toggleActions: 'play none none reverse' } });
      gsap.fromTo(linkRef.current, { y: 20, opacity: 0 },
        { y: 0, opacity: 1, ease: 'power2.out', duration: 0.5, delay: 0.8, scrollTrigger: { trigger: sectionRef.current, start: 'top 70%', toggleActions: 'play none none reverse' } });
    }, sectionRef);
    return () => ctx.revert();
  }, []);

  return (
    <section ref={sectionRef} style={{ padding: '160px 0' }}>
      <div style={{ maxWidth: '90rem', margin: '0 auto', padding: '0 3.75rem' }}>
        <div ref={labelRef} style={{ display: 'flex', alignItems: 'center', gap: '16px', marginBottom: '60px' }}>
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
            <path d="M4 12h12m0 0l-4-4m4 4l-4 4" stroke="#fc1c46" strokeWidth="1.5" strokeLinecap="square" />
          </svg>
          <span style={{ fontSize: '11px', letterSpacing: '0.2em', textTransform: 'uppercase', color: '#fc1c46', fontWeight: 500 }}>
            About AI Team Hub
          </span>
        </div>

        <div style={{ maxWidth: '62rem', marginBottom: '80px' }}>
          <p style={{ fontSize: 'clamp(28px, 3.5vw, 52px)', fontWeight: 300, lineHeight: 1.35, color: '#fff' }}>
            <SplitText
              text="AI Team Hub is a collaborative platform where you create custom AI teammates, assign them specialized roles, and bring them together in channels — like assembling your dream team, but every member is powered by AI."
              stagger={0.04}
            />
          </p>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '80px', marginBottom: '80px' }}>
          <div>
            <h4 style={{ fontSize: '11px', letterSpacing: '0.2em', textTransform: 'uppercase', color: '#fc1c46', fontWeight: 500, marginBottom: '20px' }}>
              The Problem
            </h4>
            <p style={{ fontSize: '15px', lineHeight: 1.8, color: 'rgba(255,255,255,0.5)', fontWeight: 400 }}>
              <SplitText
                text="Most AI tools give you a single chat window with a generic assistant. Real work requires specialists — a code reviewer, a data analyst, a product strategist — all working together."
                stagger={0.025}
                delay={0.3}
              />
            </p>
          </div>
          <div>
            <h4 style={{ fontSize: '11px', letterSpacing: '0.2em', textTransform: 'uppercase', color: '#fc1c46', fontWeight: 500, marginBottom: '20px' }}>
              Our Approach
            </h4>
            <p style={{ fontSize: '15px', lineHeight: 1.8, color: 'rgba(255,255,255,0.5)', fontWeight: 400 }}>
              <SplitText
                text="Create teammates with custom personalities, system prompts, and model providers. Add them to channels. Watch them collaborate, debate, and solve problems together in real time."
                stagger={0.025}
                delay={0.5}
              />
            </p>
          </div>
        </div>

        <div ref={linkRef}>
          <a href="#" onClick={(e) => e.preventDefault()}
            style={{ color: '#fc1c46', fontSize: '15px', textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: '8px' }}>
            See how it works
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M3 8h10m0 0l-3-3m3 3l-3 3" stroke="#fc1c46" strokeWidth="1.5" strokeLinecap="square" />
            </svg>
          </a>
        </div>
      </div>
    </section>
  );
}
