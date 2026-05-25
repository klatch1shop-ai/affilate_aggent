import { motion } from 'framer-motion'
import { Upload, Cpu, Globe } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

interface Step {
  number: string
  Icon: LucideIcon
  title: string
  description: string
  gradient: string
  glow: string
}

const STEPS: Step[] = [
  {
    number: '01',
    Icon: Upload,
    title: 'Підключи постачальника',
    description:
      'Завантаж XML фід або вкажи URL. Система автоматично розпарсить товари, фото та характеристики.',
    gradient: 'linear-gradient(135deg, #1D4ED8, #2563EB)',
    glow: 'rgba(37, 99, 235, 0.35)',
  },
  {
    number: '02',
    Icon: Cpu,
    title: 'AI обробляє дані',
    description:
      'Класифікує категорії з точністю 95%, розраховує ціни з CPA комісіями, валідує і нормалізує опис.',
    gradient: 'linear-gradient(135deg, #2563EB, #06B6D4)',
    glow: 'rgba(6, 182, 212, 0.35)',
  },
  {
    number: '03',
    Icon: Globe,
    title: 'Публікує на всіх маркетплейсах',
    description:
      'Автоматично синхронізує на Prom.ua, Rozetka та Єпіцентр. Підтримує актуальність залишків 24/7.',
    gradient: 'linear-gradient(135deg, #0891B2, #06B6D4)',
    glow: 'rgba(6, 182, 212, 0.35)',
  },
]

export default function HowItWorks() {
  return (
    <section id="how-it-works" className="py-24" style={{ background: 'rgba(15, 23, 42, 0.95)' }}>
      <div className="max-w-6xl mx-auto px-4 sm:px-6">

        {/* Header */}
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.6 }}
          className="text-center mb-16"
        >
          <span className="text-cyan-400 text-xs font-bold uppercase tracking-[0.2em]">Як це працює</span>
          <h2 className="text-3xl sm:text-4xl md:text-5xl font-black text-white mt-3 mb-4 leading-tight">
            Три кроки до{' '}
            <span style={{
              background: 'linear-gradient(135deg, #60A5FA, #22D3EE)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
              backgroundClip: 'text',
            }}>
              автоматизації
            </span>
          </h2>
          <p className="text-slate-400 text-lg max-w-2xl mx-auto">
            Налаштування займає менше 30 хвилин. Далі система працює сама
          </p>
        </motion.div>

        {/* Steps */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 lg:gap-8 relative">

          {/* Connector line — desktop */}
          <div className="hidden lg:block absolute top-[52px] left-[calc(16.67%+32px)] right-[calc(16.67%+32px)] h-px"
            style={{ background: 'linear-gradient(90deg, rgba(37,99,235,0.5), rgba(6,182,212,0.5))' }}
          />

          {STEPS.map(({ number, Icon, title, description, gradient, glow }, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0, y: 40 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.6, delay: i * 0.15 }}
              className="relative flex flex-col items-center lg:items-center text-center p-8 rounded-2xl"
              style={{
                background: 'rgba(30, 41, 59, 0.4)',
                border: '1px solid rgba(255,255,255,0.06)',
                backdropFilter: 'blur(8px)',
              }}
            >
              {/* Step number badge */}
              <span className="absolute top-4 right-4 text-xs font-bold text-slate-600">{number}</span>

              {/* Icon circle */}
              <div
                className="w-16 h-16 rounded-2xl flex items-center justify-center mb-6 flex-shrink-0"
                style={{ background: gradient, boxShadow: `0 8px 32px ${glow}` }}
              >
                <Icon className="w-8 h-8 text-white" />
              </div>

              <h3 className="text-white font-bold text-xl mb-3">{title}</h3>
              <p className="text-slate-400 text-sm leading-relaxed">{description}</p>
            </motion.div>
          ))}
        </div>

        {/* Bottom CTA hint */}
        <motion.div
          initial={{ opacity: 0 }}
          whileInView={{ opacity: 1 }}
          viewport={{ once: true }}
          transition={{ duration: 0.6, delay: 0.5 }}
          className="text-center mt-12"
        >
          <p className="text-slate-500 text-sm">
            Середній час до першого продажу —{' '}
            <span className="text-blue-400 font-semibold">менше 2 годин</span>
          </p>
        </motion.div>
      </div>
    </section>
  )
}
