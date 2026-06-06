import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Zap, Menu, X } from 'lucide-react'

const NAV_LINKS = [
  { label: 'Можливості', href: '#features' },
  { label: 'Ціни', href: '#pricing' },
  { label: 'Про нас', href: '#about' },
]

function scrollTo(href: string) {
  const el = document.querySelector(href)
  if (el) el.scrollIntoView({ behavior: 'smooth' })
}

export default function Navbar() {
  const [scrolled, setScrolled] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 20)
    window.addEventListener('scroll', onScroll)
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  const handleLink = (href: string) => {
    scrollTo(href)
    setMobileOpen(false)
  }

  return (
    <motion.nav
      initial={{ y: -80, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ duration: 0.6, ease: 'easeOut' }}
      className={`fixed top-0 left-0 right-0 z-50 transition-all duration-300 ${
        scrolled
          ? 'bg-[#0F172A]/80 backdrop-blur-xl border-b border-white/5 shadow-2xl'
          : 'bg-transparent'
      }`}
    >
      <div className="max-w-6xl mx-auto px-4 sm:px-6">
        <div className="flex items-center justify-between h-16">

          {/* Logo */}
          <button
            onClick={() => scrollTo('#hero')}
            className="flex items-center gap-2.5 group"
            aria-label="AgentFlow — на початок"
          >
            <div className="w-8 h-8 rounded-lg flex items-center justify-center group-hover:scale-110 transition-transform"
              style={{ background: 'linear-gradient(135deg, #2563EB, #06B6D4)' }}
            >
              <Zap className="w-4 h-4 text-white" />
            </div>
            <span className="text-white font-bold text-lg tracking-tight">AgentFlow</span>
          </button>

          {/* Desktop nav */}
          <div className="hidden md:flex items-center gap-8">
            {NAV_LINKS.map(({ label, href }) => (
              <button
                key={href}
                onClick={() => handleLink(href)}
                className="text-slate-400 hover:text-white transition-colors text-sm font-medium"
              >
                {label}
              </button>
            ))}
          </div>

          {/* CTA + burger */}
          <div className="flex items-center gap-3">
            <button
              onClick={() => handleLink('#cta')}
              className="hidden md:flex items-center gap-1.5 px-4 py-2 rounded-lg text-white text-sm font-semibold hover:opacity-90 hover:scale-105 transition-all duration-200"
              style={{ background: 'linear-gradient(135deg, #2563EB, #06B6D4)' }}
            >
              Спробувати безкоштовно
            </button>
            <button
              className="md:hidden text-slate-400 hover:text-white transition-colors p-1"
              onClick={() => setMobileOpen((v) => !v)}
              aria-label={mobileOpen ? 'Закрити меню' : 'Відкрити меню'}
            >
              {mobileOpen ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
            </button>
          </div>
        </div>
      </div>

      {/* Mobile menu */}
      <AnimatePresence>
        {mobileOpen && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.25 }}
            className="md:hidden bg-[#0F172A]/95 backdrop-blur-xl border-b border-white/5"
          >
            <div className="px-4 py-5 flex flex-col gap-1">
              {NAV_LINKS.map(({ label, href }) => (
                <button
                  key={href}
                  onClick={() => handleLink(href)}
                  className="text-slate-300 hover:text-white text-left text-sm font-medium py-3 px-2 rounded-lg hover:bg-white/5 transition-all"
                >
                  {label}
                </button>
              ))}
              <button
                onClick={() => handleLink('#cta')}
                className="mt-2 py-3 rounded-xl text-white text-sm font-semibold"
                style={{ background: 'linear-gradient(135deg, #2563EB, #06B6D4)' }}
              >
                Спробувати безкоштовно
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.nav>
  )
}
