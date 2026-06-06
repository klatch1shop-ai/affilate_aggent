# AgentFlow — Лендінг

B2B SaaS лендінг для AI платформи автоматизації дропшипінгу в Україні.

## Стек

- **React 18** + Vite + TypeScript
- **Tailwind CSS** — utility-first стилізація
- **Framer Motion** — scroll-based анімації
- **Lucide React** — іконки

## Секції

1. Navbar — sticky glassmorphism з мобільним меню
2. Hero — grid background, floating orbs, animated stats
3. Features — 6 карток з glassmorphism і hover glow
4. How It Works — 3 кроки з анімованим reveal
5. Pricing — 3 плани, Pro підсвічений градієнтом
6. Testimonials — 3 відгуки
7. CTA — email форма з анімованим сабмітом
8. Footer — навігація, соцмережі, copyright

## Запуск

```bash
# 1. Перейти в папку
cd landing

# 2. Встановити залежності
npm install

# 3. Запустити dev сервер
npm run dev
```

Відкрий **http://localhost:5173**

## Білд для продакшн

```bash
npm run build
npm run preview
```

Статичні файли будуть у папці `dist/` — готові для деплою на Nginx.

## Деплой на usa1 (Nginx)

```bash
# Збілдити
npm run build

# Скопіювати на сервер
scp -r dist/* tek@100.82.24.112:/var/www/agentflow/

# Nginx конфіг
server {
    listen 80;
    server_name agentflow.ua;
    root /var/www/agentflow;
    index index.html;
    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

## Дизайн токени

| Змінна | Значення |
|--------|---------|
| Фон | `#0F172A` |
| Картка | `#1E293B` |
| Акцент | `#2563EB` |
| Cyan | `#06B6D4` |
| Шрифт | Inter (Google Fonts) |
