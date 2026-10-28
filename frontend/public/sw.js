// LocalGem Chat - Service Worker placeholder
// Previene respuestas 404 cuando el navegador o extensiones buscan /sw.js
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', () => self.clients.claim());
