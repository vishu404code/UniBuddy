# UniBuddy — Campus AI Assistant & Query Management

UniBuddy is an intelligent, single-page web application designed for universities. It connects students, faculty, and administration through verified AI-powered responses and seamless query management.

---

## 🚀 Quick Start

Run locally with standard Node.js (zero external dependencies required):

```bash
npm start
```

Or run directly:

```bash
node server.js
```

Then visit [http://localhost:3000](http://localhost:3000) in your web browser.

---

## 🔑 Demo Accounts

The application uses **email-based role authentication** to identify user workspaces automatically:

| Role | Demo Email | Default Password | Workspace Capabilities |
| :--- | :--- | :--- | :--- |
| **Student** | `student@unibuddy.demo` | `demo123` | AI Chat Assistant, ticket submissions, dashboard, announcements |
| **Faculty** | `faculty@unibuddy.demo` | `demo123` | Ticket management desk, reply composer, ticket resolution |
| **Authority** | `authority@unibuddy.demo` | `demo123` | University oversight, grievance tracking, departmental status |
| **Management** | `management@unibuddy.demo` | `demo123` | Institutional operations, volume metrics, query analytics |

*Note: `UniBuddy@123` is also supported as an alternate prototype password.*

---

## ✨ Features

- **Email-Based Role Authentication**: Users sign in with their university email; UniBuddy detects their registered account and redirects them straight to their portal.
- **AI Campus Assistant**: Instant answers grounded in university guidelines, examination circulars, and departmental directories with clickable source verification.
- **Forward to Faculty**: Questions without instant verified answers can be forwarded to relevant departments with priority levels.
- **Faculty Ticket Desk**: Faculty review, respond to, and resolve assigned student inquiries with interactive timelines.
- **Personalized Onboarding**: First-time users set up their full name, age, and course (`B.Tech CS & AI` / `B.Tech CS & DS`), persisted in `localStorage`.
- **Live Notifications & Announcements**: Dynamic ticket update alerts and campus notices.
