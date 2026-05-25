import { motion } from 'framer-motion'
import { Star } from 'lucide-react'

interface Testimonial {
  name: string
  role: string
  company: string
  avatar: string
  text: string
  stars: number
}

const TESTIMONIALS: Testimonial[] = [
  {
    name: 'Олексій Коваленко',
    role: 'Власник магазину',
    company: 'Електроніка Плюс',
    avatar: 'ОК',
    text: 'AgentFlow зекономив мені 4 години щодня. Раніше вручну оновлював ціни, тепер система робить це автоматично. Продажі виросли на 40% за перший місяць.',
    stars: 5,
  },
  {
    name: 'Марина Савченко',
    role: 'Дропшипер',
    company: 'HomeStyle UA',
    avatar: 'МС',
    text: 'Голосове управління через Telegram — це просто магія. Їду в машині, кажу «покажи замовлення за сьогодні» — і все готово. Рекомендую всім підприємцям!',
    stars: 5,
  },
  {
    name: 'Дмитро Петренко',
    role: 'CEO',
    company: 'SportMax',
    avatar: 'ДП',
    text: 'Синхронізація на три маркетплейси одночасно — те, чого я шукав роками. AI класифікатор правильно визначає категорії в 95% випадків. Фантастичний продукт!',
    stars: 5,
  },
]

export default function Testimonials() {
  return (
    <section id="about" className="py-24" style={{ background: 'rgba(15,23,42,0.96)' }}>
      <div className="max-w-6xl mx-auto px-4 sm:px-6">

        {/* Header */}
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.6 }}
          className="text-center mb-16"
        >
          <span className="text-cyan-400 text-xs font-bold uppercase tracking-[0.2em]">Відгуки</span>
          <h2 className="text-3xl sm:text-4xl md:text-5xl font-black text-white mt-3 mb-4 leading-tight">
            Що кажуть наші{' '}
            <span style={{
              background: 'linear-gradient(135deg, #60A5FA, #22D3EE)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
              backgroundClip: 'text',
            }}>
              клієнти
            </span>
          </h2>
          <p className="text-slate-400 text-lg max-w-xl mx-auto">
            Підприємці по всій Україні автоматизували бізнес з AgentFlow
          </p>
        </motion.div>

        {/* Cards */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {TESTIMONIALS.map((t, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0, y: 40 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.5, delay: i * 0.13 }}
              whileHover={{ y: -6 }}
              className="p-6 rounded-2xl flex flex-col gap-4 transition-all duration-300"
              style={{
                background: 'rgba(30, 41, 59, 0.5)',
                border: '1px solid rgba(255,255,255,0.06)',
                backdropFilter: 'blur(12px)',
              }}
              onMouseEnter={(e) => { e.currentTarget.style.border = '1px solid rgba(37,99,235,0.25)' }}
              onMouseLeave={(e) => { e.currentTarget.style.border = '1px solid rgba(255,255,255,0.06)' }}
            >
              {/* Stars */}
              <div className="flex gap-1">
                {Array.from({ length: t.stars }).map((_, si) => (
                  <Star key={si} className="w-4 h-4 fill-yellow-400 text-yellow-400" />
                ))}
              </div>

              {/* Quote */}
              <p className="text-slate-300 text-sm leading-relaxed flex-1">
                "{t.text}"
              </p>

              {/* Author */}
              <div className="flex items-center gap-3 pt-2 border-t border-white/5">
                <div
                  className="w-10 h-10 rounded-full flex items-center justify-center text-white text-xs font-bold flex-shrink-0"
                  style={{ background: 'linear-gradient(135deg, #2563EB, #06B6D4)' }}
                >
                  {t.avatar}
                </div>
                <div>
                  <div className="text-white font-semibold text-sm">{t.name}</div>
                  <div className="text-slate-500 text-xs">{t.role} · {t.company}</div>
                </div>
              </div>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  )
}
