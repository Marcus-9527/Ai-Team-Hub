import { useEffect, useState, useCallback } from 'react';

export default function HeroSection({ onScrollDown }) {
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setReady(true), 100);
    return () => clearTimeout(t);
  }, []);

  const handleScroll = useCallback(() => {
    const el = document.getElementById('features');
    if (el) el.scrollIntoView({ behavior: 'smooth' });
  }, []);

  const ease = 'cubic-bezier(0.16, 1, 0.3, 1)';

  return (
    <section style={{ position: 'relative', width: '100%', height: '100vh', display: 'flex', flexDirection: 'column', justifyContent: 'center', background: '#000000', overflow: 'hidden' }}>
      <div style={{ position: 'relative', zIndex: 2, width: '100%', maxWidth: '90rem', margin: '0 auto', padding: '0 calc(90rem / 24)' }}>
        {/* Overline */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '40px', opacity: ready ? 1 : 0, transform: ready ? 'translateY(0)' : 'translateY(16px)', transition: `all 0.8s ${ease} 0.1s` }}>
          <span style={{ display: 'inline-block', width: '24px', height: '1px', background: '#fc1c46' }} />
          <span style={{ fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.18em', color: '#fc1c46', fontWeight: 500 }}>
            AI Team Hub
          </span>
        </div>

        {/* Title line 1 */}
        <div style={{ overflow: 'hidden', marginBottom: '8px' }}>
          <span style={{ display: 'block', fontSize: 'clamp(56px, 7vw, 140px)', fontWeight: 700, lineHeight: 0.95, letterSpacing: '-0.02em', opacity: ready ? 1 : 0, transform: ready ? 'translateY(0)' : 'translateY(100%)', transition: `all 1.4s ${ease} 0.25s` }}>
            Build
          </span>
        </div>

        {/* Title line 2 */}
        <div style={{ overflow: 'hidden', marginBottom: '8px' }}>
          <span style={{ display: 'block', fontSize: 'clamp(56px, 7vw, 140px)', fontWeight: 700, lineHeight: 0.95, letterSpacing: '-0.02em', opacity: ready ? 1 : 0, transform: ready ? 'translateY(0)' : 'translateY(100%)', transition: `all 1.4s ${ease} 0.4s` }}>
            Your AI
          </span>
        </div>

        {/* Title line 3 */}
        <div style={{ overflow: 'hidden', marginBottom: '0' }}>
          <span style={{ display: 'block', fontSize: 'clamp(56px, 7vw, 140px)', fontWeight: 700, lineHeight: 0.95, letterSpacing: '-0.02em', opacity: ready ? 1 : 0, transform: ready ? 'translateY(0)' : 'translateY(100%)', transition: `all 1.4s ${ease} 0.55s` }}>
            Team
          </span>
        </div>

        {/* Subtitle */}
        <p style={{ marginTop: '48px', maxWidth: '380px', fontSize: '14px', lineHeight: 1.7, color: '#999', opacity: ready ? 1 : 0, transform: ready ? 'translateY(0)' : 'translateY(24px)', transition: `all 1.2s ${ease} 1.0s` }}>
          Create AI teammates with custom personalities, assign them to channels, and collaborate in real time.
        </p>

        {/* CTA */}
        <div style={{ marginTop: '36px', display: 'flex', alignItems: 'center', gap: '28px', opacity: ready ? 1 : 0, transform: ready ? 'translateY(0)' : 'translateY(16px)', transition: `all 1.2s ${ease} 1.3s` }}>
          <button onClick={handleScroll}
            style={{ background: '#fc1c46', color: '#000', border: 'none', padding: '13px 30px', fontSize: '11px', fontWeight: 600, cursor: 'pointer', textTransform: 'uppercase', letterSpacing: '0.1em', transition: 'background 0.3s ease' }}
            onMouseEnter={(e) => { e.currentTarget.style.background = '#e0163a'; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = '#fc1c46'; }}>
            Get Started
          </button>
          <button onClick={() => window.open('/preview/', '_blank')}
            style={{ fontSize: '11px', fontWeight: 500, color: '#fff', textDecoration: 'none', textTransform: 'uppercase', letterSpacing: '0.08em', transition: 'opacity 0.3s ease', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
            onMouseEnter={(e) => { e.currentTarget.style.opacity = '0.6'; }}
            onMouseLeave={(e) => { e.currentTarget.style.opacity = '1'; }}>
            Learn More →
          </button>
        </div>
      </div>
    </section>
  );
}
