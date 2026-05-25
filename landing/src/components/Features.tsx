import { motion } from 'framer-motion'

interface Feature {
  icon: string
  title: string
  description: string
  accent: string
}

const FEATURES: Feature[] = [
  {
    icon: '🎙️',
    title: 'Голосове управління',
    description: "Скажи «оновити ціни» і система виконає за секунди. Підтримка команд через Telegram голосові повідомлення.",
    accent: '#2563EB',
  },
  {
    icon: '🤖',
    title: 'AI Класифікація',
    description: 'Автоматично визначає категорії для 95% товарів. Модель Qwen2.5 7B навчена на українських маркетплейсах.',
    accent: '#06B6D4',
  },
  {
    icon: '📦',
    title: 'Синхронізація залишків',
    description: 'Реальний час з фіду постачальника на всі маркетплейси. Нульові розбіжності в кількості товарів.',
    accent: '#2563EB',
  },
  {
    icon: '💰',
    title: 'Розумні ціни',
    description: 'Автоматично додає CPA комісію маркетплейсу до ціни. Гнучкі правила ціноутворення для кожного каналу.',
    accent: '#06B6D4',
  },
  {
    icon: '📱',
    title: 'Telegram бот',
    description: 'Повне управління бізнесом через месенджер 24/7. Сповіщення, звіти та команди прямо в чаті.',
    accent: '#2563EB',
  },
  {
    icon: '🔄',
    title: 'Авто-замовлення',
    description: 'Від отримання до відправки без участі людини. Автоматичне оформлення у постачальника після продажу.',
    accent: '#06B6D4',
  },
]

const containerVariants = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.08 } },
}

const cardVariants = {
  hidden: { opacity: 0, y: 32 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.5, ease: 'easeOut' } },
}

export default function Features() {
  return (
    <section id="features" className="py-24 bg-[#0F172A]">
      <div className="max-w-6xl mx-auto px-4 sm:px-6">

        {/* Header */}
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.6 }}
          className="text-center mb-16"
        >
          <span className="text-blue-400 text-xs font-bold uppercase tracking-[0.2em]">Можливості</span>
          <h2 className="text-3xl sm:text-4xl md:text-5xl font-black text-white mt-3 mb-4 leading-tight">
            Все що потрібно для{' '}
            <span style={{
              background: 'linear-gradient(135deg, #60A5FA, #22D3EE)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
              backgroundClip: 'text',
            }}>
              автоматизації
            </span>
          </h2>
          <p className="text-slate-400 text-lg max-w-2xl mx-auto leading-relaxed">
            Повний набір інструментів для автоматизації дропшипінг бізнесу на Prom.ua, Rozetka та Єпіцентр
          </p>
        </motion.div>

        {/* Cards */}
        <motion.div
          variants={containerVariants}
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: '-60px' }}
          className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5"
        >
          {FEATURES.map((feature, i) => (
            <motion.div
              key={i}
              variants={cardVariants}
              whileHover={{ scale: 1.03, y: -6 }}
              className="group relative p-6 rounded-2xl cursor-default overflow-hidden transition-all duration-300"
              style={{
                background: 'rgba(30, 41, 59, 0.5)',
                border: '1px solid rgba(255,255,255,0.06)',
                backdropFilter: 'blur(12px)',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.border = `1px solid ${feature.accent}40`
                e.currentTarget.style.boxShadow = `0 8px 32px ${feature.accent}20`
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.border = '1px solid rgba(255,255,255,0.06)'
                e.currentTarget.style.boxShadow = 'none'
              }}
            >
              {/* Top accent line */}
              <div
                className="absolute top-0 left-0 right-0 h-px opacity-0 group-hover:opacity-100 transition-opacity duration-300"
                style={{ background: `linear-gradient(90deg, transparent, ${feature.accent}, transparent)` }}
              />

              {/* Icon */}
              <div
                className="w-12 h-12 rounded-xl flex items-center justify-center text-2xl mb-4 group-hover:scale-110 transition-transform duration-300"
                style={{ background: `${feature.accent}18`, border: `1px solid ${feature.accent}30` }}
              >
                {feature.icon}
              </div>

              <h3 className="text-white font-bold text-lg mb-2">{feature.title}</h3>
              <p className="text-slate-400 text-sm leading-relaxed">{feature.description}</p>
            </motion.div>
          ))}
        </motion.div>
      </div>
    </section>
  )
}
