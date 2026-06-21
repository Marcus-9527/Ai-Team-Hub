import { useEffect, useRef, useState } from 'react';

const PROJECTS = [
  { id: 'code-review', category: 'ENGINEERING', title: 'Code Review', desc: 'Multi-AI peer review with architecture analysis', image: 'https://images.unsplash.com/photo-1555066931-4365d14bab8c?w=1920&q=80' },
  { id: 'data-insights', category: 'ANALYTICS', title: 'Data Insights', desc: 'Real-time data analysis and visualization', image: 'https://images.unsplash.com/photo-1551288049-bebda4e38f71?w=1920&q=80' },
  { id: 'product-strategy', category: 'PRODUCT', title: 'Product Strategy', desc: 'AI-powered market research and roadmapping', image: 'https://images.unsplash.com/photo-1460925895917-afdab827c52f?w=1920&q=80' },
];

export default function ProjectsSection() {
  const [hoveredIndex, setHoveredIndex] = useState(null);
  const [ready, setReady] = useState(false);
  const sectionRef = useRef(null);

  useEffect(() => {
    const el = sectionRef.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      ([entry]) => { if (entry.isIntersecting) { setReady(true); obs.disconnect(); } },
      { threshold: 0.15 }
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  const ease = 'cubic-bezier(0.16, 1, 0.3, 1)';

  return (
    <section style={{ position: 'relative' }} ref={sectionRef}>
      <div className="tl-container" style={{ paddingTop: '120px', paddingBottom: '60px' }}>
        {/* Overline */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '40px', opacity: ready ? 1 : 0, transform: ready ? 'translateY(0)' : 'translateY(16px)', transition: `all 0.8s ${ease} 0.1s` }}>
          <span style={{ display: 'inline-block', width: '40px', height: '2px', background: '#fc1c46' }} />
          <span className="tl-caption" style={{ color: '#fc1c46' }}>What We Do</span>
        </div>

        {/* Title line 1 */}
        <div style={{ overflow: 'hidden', marginBottom: '8px' }}>
          <h2 className="tl-section-title" style={{ maxWidth: '800px', opacity: ready ? 1 : 0, transform: ready ? 'translateY(0)' : 'translateY(100%)', transition: `all 1.4s ${ease} 0.25s` }}>
            AI teammates
          </h2>
        </div>
        {/* Title line 2 */}
        <div style={{ overflow: 'hidden', marginBottom: '8px' }}>
          <h2 className="tl-section-title" style={{ maxWidth: '800px', opacity: ready ? 1 : 0, transform: ready ? 'translateY(0)' : 'translateY(100%)', transition: `all 1.4s ${ease} 0.4s` }}>
            for every role
          </h2>
        </div>
        {/* Title line 3 */}
        <div style={{ overflow: 'hidden' }}>
          <h2 className="tl-section-title" style={{ maxWidth: '800px', opacity: ready ? 1 : 0, transform: ready ? 'translateY(0)' : 'translateY(100%)', transition: `all 1.4s ${ease} 0.55s` }}>
            in your workflow
          </h2>
        </div>
      </div>

      {/* Project cards */}
      <div style={{ position: 'relative' }}>
        {PROJECTS.map((project, index) => (
          <a key={project.id} href="#" onClick={(e) => e.preventDefault()}
            className="tl-project-card"
            onMouseEnter={() => setHoveredIndex(index)}
            onMouseLeave={() => setHoveredIndex(null)}
            style={{ textDecoration: 'none', color: '#fff', cursor: 'pointer' }}>
            <div className="tl-project-card__bg" style={{ backgroundImage: `url(${project.image})`, opacity: hoveredIndex === index ? 1 : 0 }} />
            <div style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', background: hoveredIndex === index ? 'rgba(0,0,0,0.5)' : 'rgba(0,0,0,0.3)', zIndex: 1, transition: 'background 0.6s ease' }} />
            <div className="tl-project-card__content">
              <div className="tl-container" style={{ position: 'relative', zIndex: 2 }}>
                <div className="tl-caption" style={{ color: '#fc1c46', marginBottom: '20px', opacity: hoveredIndex === index ? 0 : 1, transform: hoveredIndex === index ? 'translateY(-10px)' : 'translateY(0)', transition: 'all 0.5s cubic-bezier(0.16, 1, 0.3, 1)' }}>
                  {project.category}
                </div>
                <h3 className="tl-item-title" style={{ transition: 'all 0.5s cubic-bezier(0.16, 1, 0.3, 1)', transform: hoveredIndex === index ? 'scale(1.05)' : 'scale(1)' }}>
                  {project.title}
                </h3>
              </div>
            </div>
            <div className="tl-project-card__bottom">
              <div className="tl-container">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end' }}>
                  <div><div className="tl-body" style={{ color: 'rgba(255,255,255,0.6)', maxWidth: '400px' }}>{project.desc}</div></div>
                  <div className="tl-caption" style={{ color: 'rgba(255,255,255,0.3)' }}>String(0{index + 1})</div>
                </div>
              </div>
            </div>
          </a>
        ))}
      </div>
    </section>
  );
}
