import Navbar from './components/Navbar'
import Hero from './components/Hero'
import Features from './components/Features'
import HowItWorks from './components/HowItWorks'
import Pricing from './components/Pricing'
import Testimonials from './components/Testimonials'
import CTASection from './components/CTASection'
import Footer from './components/Footer'

export default function App() {
  return (
    <div className="bg-[#0F172A] min-h-screen font-sans overflow-x-hidden">
      <Navbar />
      <main>
        <Hero />
        <Features />
        <HowItWorks />
        <Pricing />
        <Testimonials />
        <CTASection />
      </main>
      <Footer />
    </div>
  )
}
