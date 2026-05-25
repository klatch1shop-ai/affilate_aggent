import { Zap } from 'lucide-react'

const NAV_LINKS = [
  { label: 'Можливості', href: '#features' },
  { label: 'Ціни', href: '#pricing' },
  { label: 'Про нас', href: '#about' },
  { label: 'Блог', href: '#' },
]

const LEGAL_LINKS = [
  { label: 'Політика конфіденційності', href: '#' },
  { label: 'Умови використання', href: '#' },
]

const SOCIAL_LINKS = [
  { label: 'Telegram', href: '#', symbol: 'TG' },
  { label: 'Twitter/X', href: '#', symbol: '𝕏' },
  { label: 'LinkedIn', href: '#', symbol: 'in' },
]

function scrollTo(href: string) {
  if (!href.startsWith('#') || href === '#') return
  const el = document.querySelector(href)
  if (el) el.scrollIntoView({ behavior: 'smooth' })
}

export default function Footer() {
  return (
    <footer style={{ background: '#080F1E', borderTop: '1px solid rgba(255,255,255,0.05)' }}>
      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-14">
        <div className="grid grid-cols-1 md:grid-cols-12 gap-10 mb-12">

          {/* Brand col */}
          <div className="md:col-span-5">
            <button
              onClick={() => scrollTo('#hero')}
              className="flex items-center gap-2.5 mb-4 group"
              aria-label="AgentFlow"
            >
              <div
                className="w-8 h-8 rounded-lg flex items-center justify-center group-hover:scale-110 transition-transform"
                style={{ background: 'linear-gradient(135deg, #2563EB, #06B6D4)' }}
              >
                <Zap className="w-4 h-4 text-white" />
              </div>
              <span className="text-white font-bold text-lg tracking-tight">AgentFlow</span>
            </button>
            <p className="text-slate-500 text-sm leading-relaxed max-w-xs">
              AI платформа автоматизації дропшипінгу для підприємців України.
              Prom.ua, Rozetka, Єпіцентр — все в одному місці.
            </p>

            {/* Social */}
            <div className="flex gap-2.5 mt-6">
              {SOCIAL_LINKS.map(({ label, href, symbol }) => (
                <a
                  key={label}
                  href={href}
                  aria-label={label}
                  className="w-9 h-9 rounded-lg flex items-center justify-center text-slate-500 text-xs font-bold transition-all duration-200"
                  style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.07)' }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.borderColor = 'rgba(37,99,235,0.4)'
                    e.currentTarget.style.color = '#60A5FA'
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.borderColor = 'rgba(255,255,255,0.07)'
                    e.currentTarget.style.color = ''
                  }}
                >
                  {symbol}
                </a>
              ))}
            </div>
          </div>

          {/* Nav col */}
          <div className="md:col-span-3 md:col-start-7">
            <h4 className="text-white text-sm font-semibold mb-4">Навігація</h4>
            <ul className="space-y-2.5">
              {NAV_LINKS.map(({ label, href }) => (
                <li key={label}>
                  <button
                    onClick={() => scrollTo(href)}
                    className="text-slate-500 hover:text-white text-sm transition-colors"
                  >
                    {label}
                  </button>
                </li>
              ))}
            </ul>
          </div>

          {/* Contact col */}
          <div className="md:col-span-3 md:col-start-10">
            <h4 className="text-white text-sm font-semibold mb-4">Контакти</h4>
            <ul className="space-y-2.5">
              <li>
                <a href="mailto:hello@agentflow.ua" className="text-slate-500 hover:text-white text-sm transition-colors">
                  hello@agentflow.ua
                </a>
              </li>
              <li>
                <a href="https://t.me/agentflow_bot" className="text-slate-500 hover:text-white text-sm transition-colors">
                  @agentflow_bot
                </a>
              </li>
            </ul>
          </div>
        </div>

        {/* Bottom bar */}
        <div className="flex flex-col sm:flex-row items-center justify-between gap-4 pt-8"
          style={{ borderTop: '1px solid rgba(255,255,255,0.05)' }}
        >
          <p className="text-slate-600 text-xs">
            © 2024 AgentFlow. Всі права захищено. Зроблено в Україні 🇺🇦
          </p>
          <div className="flex gap-5">
            {LEGAL_LINKS.map(({ label, href }) => (
              <a
                key={label}
                href={href}
                className="text-slate-600 hover:text-slate-400 text-xs transition-colors"
              >
                {label}
              </a>
            ))}
          </div>
        </div>
      </div>
    </footer>
  )
}
