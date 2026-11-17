// Service worker mínimo: só arquivos públicos (nunca saldo, sessão ou respostas privadas). Partidas exigem conexão.
self.addEventListener('install', (e) => self.skipWaiting())
self.addEventListener('fetch', () => {})
