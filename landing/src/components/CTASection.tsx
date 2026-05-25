import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { ArrowRight, CheckCircle, Loader2 } from 'lucide-react'

export default function CTASection() {
  const [email, setEmail] = useState('')
  const [loading, setLoading] = useState(false)
  const [submitted, setSubmitted] = useState(false)

  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (!email) return
    setLoading(true)
    // Simulate API call
    setTimeout(() => {
      setLoading(false)
      setSubmitted(true)
    }, 1200)
  }

  return (
    <section id="cta" className="py-28 bg-[#0F172A] relative overflow-hidden">

      {/* Background glows */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background: 'radial-gradient(ellipse 60% 50% at 50% 50%, rgba(37,99,235,0.12) 0%, transparent 70%)',
        }}
      />
      <motion.div
        className="absolute rounded-full blur-3xl pointer-events-none"
        style={{ width: 600, height: 300, top: '50%', left: '50%', transform: 'translate(-50%,-50%)', background: 'rgba(6,182,212,0.06)' }}
        animate={{ scale: [1, 1.1, 1] }}
        transition={{ duration: 7, repeat: Infinity, ease: 'easeInOut' }}
      />

      {/* Grid */}
      <div
        className="absolute inset-0 opacity-20 pointer-events-none"
        style={{
          backgroundImage: `
            linear-gradient(rgba(37, 99, 235, 0.1) 1px, transparent 1px),
            linear-gradient(90deg, rgba(37, 99, 235, 0.1) 1px, transparent 1px)
          `,
          backgroundSize: '52px 52px',
        }}
      />

      <div className="relative max-w-2xl mx-auto px-4 sm:px-6 text-center">
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.65 }}
        >
          <span className="text-blue-400 text-xs font-bold uppercase tracking-[0.2em]">Старт</span>

          <h2 className="text-3xl sm:text-4xl md:text-5xl font-black text-white mt-3 mb-4 leading-tight">
            Готовий автоматизувати{' '}
            <span style={{
              background: 'linear-gradient(135deg, #60A5FA, #22D3EE)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
              backgroundClip: 'text',
            }}>
              бізнес?
            </span>
          </h2>

          <p className="text-slate-400 text-lg mb-10 leading-relaxed">
            Приєднуйся до підприємців, що вже автоматизували дропшипінг.{' '}
            <span className="text-slate-300">14 днів безкоштовно</span> — без кредитної картки.
          </p>

          <AnimatePresence mode="wait">
            {!submitted ? (
              <motion.form
                key="form"
                initial={{ opacity: 1 }}
                exit={{ opacity: 0, scale: 0.95 }}
                onSubmit={handleSubmit}
                className="flex flex-col sm:flex-row gap-3 max-w-md mx-auto"
              >
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="твій@email.com"
                  required
                  aria-label="Email адреса"
                  className="flex-1 px-4 py-3.5 rounded-xl text-white placeholder-slate-500 text-sm outline-none transition-all duration-200"
                  style={{
                    background: 'rgba(30,41,59,0.8)',
                    border: '1px solid rgba(255,255,255,0.1)',
                  }}
                  onFocus={(e) => { e.currentTarget.style.border = '1px solid rgba(37,99,235,0.6)' }}
                  onBlur={(e) => { e.currentTarget.style.border = '1px solid rgba(255,255,255,0.1)' }}
                />
                <button
                  type="submit"
                  disabled={loading}
                  className="flex items-center justify-center gap-2 px-6 py-3.5 rounded-xl text-white font-semibold text-sm transition-all duration-300 hover:scale-105 disabled:opacity-70 disabled:cursor-not-allowed whitespace-nowrap"
                  style={{ background: 'linear-gradient(135deg, #2563EB, #06B6D4)', boxShadow: '0 4px 24px rgba(37,99,235,0.3)' }}
                >
                  {loading ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <>
                      Спробувати
                      <ArrowRight className="w-4 h-4" />
                    </>
                  )}
                </button>
              </motion.form>
            ) : (
              <motion.div
                key="success"
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ duration: 0.4 }}
                className="flex items-center justify-center gap-3"
              >
                <CheckCircle className="w-7 h-7 text-green-400" />
                <span className="text-green-400 text-lg font-semibold">
                  Дякуємо! Ми зв'яжемося з вами найближчим часом.
                </span>
              </motion.div>
            )}
          </AnimatePresence>

          <p className="text-slate-600 text-xs mt-5 leading-relaxed">
            Натискаючи «Спробувати», ви погоджуєтесь з{' '}
            <a href="#" className="text-slate-500 underline hover:text-slate-400 transition-colors">умовами використання</a>
            {' '}та{' '}
            <a href="#" className="text-slate-500 underline hover:text-slate-400 transition-colors">політикою конфіденційності</a>
          </p>
        </motion.div>
      </div>
    </section>
  )
}
