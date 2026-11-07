# UniBuddy · Intelligent Campus AI Assistant & Helpdesk

> **One campus. One intelligent assistant.**  
> UniBuddy provides students with instant, verified answers grounded in official university documents and circulars. When human intervention is required, UniBuddy seamlessly creates and routes prioritized tickets directly to faculty desks, tracked in real-time until resolution.

---

## 🚀 Key Features

- **Email-Based Role Authentication**: Automatic role detection and secure workspace routing from user email address (no manual role-selection step).
- **Grounded AI Answers**: Immediate responses with citations (document title, circular number, page reference).
- **Automated Query Escalation**: Unresolved or specialized student questions can be forwarded directly to the right department desk.
- **Role-Specific Workspaces**:
  - **Student**: Directly opens the UniBuddy AI Assistant with chat, dashboard, announcements, and personal query tracking.
  - **Faculty**: Direct access to the Student Query Desk with assigned tickets, query details, student context, official reply drafting, and one-click ticket resolution.
  - **Authority**: Escalation queue review, cross-department SLA tracking, and departmental re-routing.
  - **Management**: Institutional operations overview, query deflection rates, resolution turnaround times, and category breakdown.
- **Session Persistence**: Built-in session restoration across page reloads and back-navigation protection for logged-out states.

---

## 👥 Demo Accounts (Prototype Access)

Use any of the registered prototype accounts below with the unified demo password:

**Demo Password:** `UniBuddy@123`

| Role | Email Address | First Screen on Login |
| :--- | :--- | :--- |
| **Student** | `student@unibuddy.demo` | **AI Assistant (Instant Chat)** |
| **Faculty** | `faculty@unibuddy.demo` | **Ticket Management Desk** |
| **Authority** | `authority@unibuddy.demo` | **Escalation & SLA Monitor** |
| **Management** | `management@unibuddy.demo` | **Institutional Operations Overview** |

*Note: On the redesigned login page, you can either enter these credentials manually or click any demo card in the "Explore Demo Accounts" shelf to sign in with one click.*

---

## 💻 Quick Start

### Option 1: Run with Built-in Server

```bash
# Clone the repository
git clone https://github.com/vishu404code/UniBuddy.git
cd UniBuddy

# Start the local server (zero external dependencies required)
npm start
# or: node server.js
```

Open your browser and navigate to:  
👉 **`http://localhost:3000`**

---

### Option 2: Open Directly in Browser

Double-click `index.html` or open it directly in Chrome, Safari, Edge, or Firefox:
```bash
open index.html
```

---

## 🛠️ Project Structure

```
UniBuddy/
├── index.html        # Main SPA (Unified UI, reactive state engine, auth registry, KB)
├── server.js         # Built-in lightweight zero-dependency Node.js HTTP server
├── package.json      # NPM script definitions
├── .gitignore        # Git ignore rules
└── README.md         # Documentation & credentials
```

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
