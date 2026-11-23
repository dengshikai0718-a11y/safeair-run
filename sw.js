/* SafeAir Run Service Worker
 * 只負責兩件事：讓手機瀏覽器能以 registration.showNotification 顯示通知（Android Chrome 不允許頁面直接 new Notification），
 * 以及點擊通知後把使用者帶回頁面。不快取、不攔截任何請求。
 */
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));
self.addEventListener('notificationclick', (e) => {
  e.notification.close();
  e.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((list) => {
    for (const c of list) if ('focus' in c) return c.focus();
    return self.clients.openWindow('./');
  }));
});
