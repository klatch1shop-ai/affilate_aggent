import { motion } from 'framer-motion'
import { Check } from 'lucide-react'

interface Plan {
  name: string
  price: number
  description: string
  features: string[]
  popular?: boolean
  cta: string
}

const PLANS: Plan[] = [
  {
    name: 'Starter',
    price: 49,
    description: 'Ідеально для старту',
    features: [
      'До 1 000 товарів',
      '1 маркетплейс',
      'Telegram бот',
      'XML фід імпорт',
      'Email підтримка',
    ],
    cta: 'Почати безкоштовно',
  },
  {
    name: 'Pro',
    price: 99,
    description: 'Для активного бізнесу',
    features: [
      'До 10 000 товарів',
      '3 маркетплейси',
      'Голосове управління',
      'AI класифікація',
      'Автоматичне ціноутворення',
      'Пріоритетна підтримка',
    ],
    popular: true,
    cta: 'Спробувати Pro',
  },
  {
    name: 'Enterprise',
    price: 199,
    description: 'Без обмежень',
    features: [
      'Необмежена кількість товарів',
      'Всі маркетплейси',
      'Всі функції Pro',
      'API доступ',
      'Персональний менеджер',
      'SLA 99.9%',
    ],
    cta: "Зв'язатися з нами",
  },
]

export default function Pricing() {
  return (
    <section id="pricing" className="py-24 bg-[#0F172A]">
      <div className="max-w-6xl mx-auto px-4 sm:px-6">

        {/* Header */}
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.6 }}
          className="text-center mb-16"
        >
          <span className="text-blue-400 text-xs font-bold uppercase tracking-[0.2em]">Ціни</span>
          <h2 className="text-3xl sm:text-4xl md:text-5xl font-black text-white mt-3 mb-4 leading-tight">
            Прозорі тарифи{' '}
            <span style={{
              background: 'linear-gradient(135deg, #60A5FA, #22D3EE)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
              backgroundClip: 'text',
            }}>
              без сюрпризів
            </span>
          </h2>
          <p className="text-slate-400 text-lg max-w-2xl mx-auto">
            14 днів безкоштовно для будь-якого тарифу · Скасування в будь-який момент
          </p>
        </motion.div>

        {/* Cards */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 lg:gap-8 items-start">
          {PLANS.map((plan, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0, y: 40 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.5, delay: i * 0.1 }}
              whileHover={{ scale: 1.02, y: -4 }}
              className="relative p-8 rounded-2xl flex flex-col"
              style={
                plan.popular
                  ? {
                      background: 'linear-gradient(135deg, rgba(37,99,235,0.15), rgba(6,182,212,0.1))',
                      border: '2px solid rgba(37,99,235,0.5)',
                      boxShadow: '0 0 60px rgba(37,99,235,0.15)',
                    }
                  : {
                      background: 'rgba(30, 41, 59, 0.5)',
                      border: '1px solid rgba(255,255,255,0.06)',
                      backdropFilter: 'blur(12px)',
                    }
              }
            >
              {/* Popular badge */}
              {plan.popular && (
                <div className="absolute -top-4 left-1/2 -translate-x-1/2">
                  <span
                    className="px-4 py-1.5 rounded-full text-white text-xs font-bold tracking-wide whitespace-nowrap"
                    style={{ background: 'linear-gradient(135deg, #2563EB, #06B6D4)' }}
                  >
                    ⭐ POPULAR
                  </span>
                </div>
              )}

              {/* Plan info */}
              <div className="mb-6">
                <h3 className="text-white font-bold text-xl mb-1">{plan.name}</h3>
                <p className="text-slate-400 text-sm mb-5">{plan.description}</p>
                <div className="flex items-end gap-1.5">
                  <span className="text-5xl font-black text-white">${plan.price}</span>
                  <span className="text-slate-400 mb-1.5 text-sm">/міс</span>
                </div>
              </div>

              {/* Features */}
              <ul className="space-y-3 mb-8 flex-1">
                {plan.features.map((feat, fi) => (
                  <li key={fi} className="flex items-center gap-3">
                    <div
                      className="w-5 h-5 rounded-full flex items-center justify-center flex-shrink-0"
                      style={{ background: 'rgba(37,99,235,0.2)' }}
                    >
                      <Check className="w-3 h-3 text-blue-400" />
                    </div>
                    <span className="text-slate-300 text-sm">{feat}</span>
                  </li>
                ))}
              </ul>

              {/* CTA */}
              <button
                className="w-full py-3.5 rounded-xl font-semibold text-sm transition-all duration-300 hover:scale-105"
                style={
                  plan.popular
                    ? {
                        background: 'linear-gradient(135deg, #2563EB, #06B6D4)',
                        color: 'white',
                        boxShadow: '0 4px 24px rgba(37,99,235,0.3)',
                      }
                    : {
                        background: 'rgba(255,255,255,0.05)',
                        border: '1px solid rgba(255,255,255,0.1)',
                        color: 'white',
                      }
                }
                onMouseEnter={(e) => {
                  if (!plan.popular) e.currentTarget.style.background = 'rgba(255,255,255,0.09)'
                }}
                onMouseLeave={(e) => {
                  if (!plan.popular) e.currentTarget.style.background = 'rgba(255,255,255,0.05)'
                }}
              >
                {plan.cta}
              </button>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  )
}
