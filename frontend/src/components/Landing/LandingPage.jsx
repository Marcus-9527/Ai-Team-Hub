import HeroSection from './HeroSection';
import ProjectsSection from './ProjectsSection';
import AboutSection from './AboutSection';
import CapabilitiesSection from './CapabilitiesSection';
import ContactSection from './ContactSection';
import Navbar from './Navbar';

export default function LandingPage({ onEnterApp }) {
  const handleScrollDown = () => {
    const el = document.getElementById('features');
    if (el) el.scrollIntoView({ behavior: 'smooth' });
  };

  return (
    <div style={{ background: '#000000', color: '#ffffff', minHeight: '100vh' }}>
      <Navbar onEnterApp={onEnterApp} />

      <main>
        <HeroSection onScrollDown={handleScrollDown} />

        <div id="features">
          <ProjectsSection />
        </div>

        <div id="about">
          <AboutSection />
        </div>

        <div id="how">
          <CapabilitiesSection />
        </div>

        <ContactSection onEnterApp={onEnterApp} />
      </main>
    </div>
  );
}
