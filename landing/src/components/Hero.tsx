import { motion } from 'framer-motion'
import { ArrowRight, Play } from 'lucide-react'

const STATS = [
  { value: '3', label: 'маркетплейси' },
  { value: '10к+', label: 'товарів' },
  { value: '99.9%', label: 'uptime' },
]

const fadeUp = (delay = 0) => ({
  initial: { opacity: 0, y: 30 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.7, delay, ease: 'easeOut' },
})

export default function Hero() {
  return (
    <section id="hero" className="relative min-h-screen flex items-center justify-center overflow-hidden bg-[#0F172A]">

      {/* Grid dot background */}
      <div
        className="absolute inset-0 opacity-40"
        style={{
          backgroundImage: `
            linear-gradient(rgba(37, 99, 235, 0.12) 1px, transparent 1px),
            linear-gradient(90deg, rgba(37, 99, 235, 0.12) 1px, transparent 1px)
          `,
          backgroundSize: '52px 52px',
        }}
      />

      {/* Radial fade overlay */}
      <div
        className="absolute inset-0"
        style={{
          background: 'radial-gradient(ellipse 80% 60% at 50% 50%, transparent 30%, #0F172A 100%)',
        }}
      />

      {/* Floating orbs */}
      <motion.div
        className="absolute rounded-full blur-3xl"
        style={{ width: 480, height: 480, top: '10%', left: '-5%', background: 'rgba(37, 99, 235, 0.12)' }}
        animate={{ scale: [1, 1.15, 1], opacity: [0.6, 1, 0.6] }}
        transition={{ duration: 6, repeat: Infinity, ease: 'easeInOut' }}
      />
      <motion.div
        className="absolute rounded-full blur-3xl"
        style={{ width: 380, height: 380, bottom: '10%', right: '-5%', background: 'rgba(6, 182, 212, 0.1)' }}
        animate={{ scale: [1, 1.2, 1], opacity: [0.5, 0.9, 0.5] }}
        transition={{ duration: 8, repeat: Infinity, ease: 'easeInOut', delay: 1.5 }}
      />

      {/* Content */}
      <div className="relative max-w-5xl mx-auto px-4 sm:px-6 text-center pt-24 pb-20">

        {/* Badge */}
        <motion.div {...fadeUp(0)} className="inline-flex items-center gap-2 px-4 py-2 rounded-full mb-8"
          style={{
            background: 'rgba(37, 99, 235, 0.1)',
            border: '1px solid rgba(37, 99, 235, 0.3)',
          }}
        >
          <span>🚀</span>
          <span className="text-blue-400 text-sm font-medium">AI дропшипінг платформа #1 в Україні</span>
        </motion.div>

        {/* Headline */}
        <motion.h1
          {...fadeUp(0.1)}
          className="text-4xl sm:text-5xl md:text-6xl lg:text-7xl font-black text-white leading-[1.1] tracking-tight mb-6"
        >
          Керуй дропшипінг{' '}
          <span
            className="inline-block"
            style={{
              background: 'linear-gradient(135deg, #60A5FA, #22D3EE)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
              backgroundClip: 'text',
            }}
          >
            бізнесом голосом
          </span>
          {' '}з телефону
        </motion.h1>

        {/* Subheadline */}
        <motion.p
          {...fadeUp(0.2)}
          className="text-lg sm:text-xl text-slate-400 max-w-2xl mx-auto mb-10 leading-relaxed"
        >
          AI агент автоматизує продажі на Prom.ua, Rozetka та Єпіцентр.{' '}
          <span className="text-slate-300">Замовлення, ціни, залишки</span> — без вашої участі
        </motion.p>

        {/* CTA Buttons */}
        <motion.div
          {...fadeUp(0.3)}
          className="flex flex-col sm:flex-row items-center justify-center gap-4 mb-16"
        >
          <button
            onClick={() => {
              const el = document.querySelector('#cta')
              if (el) el.scrollIntoView({ behavior: 'smooth' })
            }}
            className="group flex items-center gap-2 px-8 py-4 rounded-xl text-white font-semibold text-lg transition-all duration-300 hover:scale-105"
            style={{ background: 'linear-gradient(135deg, #2563EB, #06B6D4)', boxShadow: '0 0 0 0 rgba(37,99,235,0)' }}
            onMouseEnter={(e) => { e.currentTarget.style.boxShadow = '0 8px 40px rgba(37,99,235,0.4)' }}
            onMouseLeave={(e) => { e.currentTarget.style.boxShadow = '0 0 0 0 rgba(37,99,235,0)' }}
          >
            Почати безкоштовно
            <ArrowRight className="w-5 h-5 group-hover:translate-x-1 transition-transform" />
          </button>

          <button className="flex items-center gap-2 px-8 py-4 rounded-xl text-white font-semibold text-lg transition-all duration-300 hover:scale-105"
            style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)' }}
            onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(255,255,255,0.08)' }}
            onMouseLeave={(e) => { e.currentTarget.style.background = 'rgba(255,255,255,0.05)' }}
          >
            <Play className="w-5 h-5 text-cyan-400" />
            Переглянути демо
          </button>
        </motion.div>

        {/* Stats */}
        <motion.div
          {...fadeUp(0.45)}
          className="flex flex-col sm:flex-row items-center justify-center gap-8 sm:gap-16"
        >
          {STATS.map(({ value, label }, i) => (
            <div key={i} className="text-center">
              <div
                className="text-3xl sm:text-4xl font-black mb-1"
                style={{
                  background: 'linear-gradient(135deg, #60A5FA, #22D3EE)',
                  WebkitBackgroundClip: 'text',
                  WebkitTextFillColor: 'transparent',
                  backgroundClip: 'text',
                }}
              >
                {value}
              </div>
              <div className="text-slate-400 text-sm font-medium">{label}</div>
            </div>
          ))}
        </motion.div>

        {/* Trusted by badge */}
        <motion.p {...fadeUp(0.55)} className="mt-12 text-slate-600 text-xs tracking-widest uppercase">
          Довіряють підприємці по всій Україні
        </motion.p>
      </div>
    </section>
  )
}
