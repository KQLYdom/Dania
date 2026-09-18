self.addEventListener("push", event => {
    const data = event.data ? event.data.json() : {};
    event.waitUntil(self.registration.showNotification(data.title || "Home Manager", {
        body: data.body || "You have a new update.",
        data: {url: data.url || "/"},
    }));
});

self.addEventListener("notificationclick", event => {
    event.notification.close();
    event.waitUntil(clients.openWindow(event.notification.data.url));
});
