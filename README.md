# UniBuddy · Intelligent Campus AI Assistant & Helpdesk

> **One campus. One intelligent assistant.**  
> UniBuddy provides students with instant, verified answers grounded in official university documents and circulars. If a query requires departmental review, UniBuddy seamlessly creates and routes prioritized tickets to faculty desks, tracked in real-time until resolution.

---

## 🚀 Key Features

- **Grounded AI Answers**: Immediate responses with citations (document title, circular number, page reference).
- **Automated Query Escalation**: Unresolved or specialized student questions can be forwarded directly to the right department (Computer Science, Accounts, Examinations, Hostel Office, Library).
- **Faculty Ticket Management**: Department staff can inspect student questions, respond with official remarks, and update ticket progress or mark as resolved.
- **Real-Time Lifecycle Tracking**: Step-by-step progress tracking (`Submitted` → `Assigned` → `In Progress` → `Resolved`).
- **Interactive Role Switching**: Explore views for **Student**, **Faculty**, **Authority**, and **Management**.
- **Campus Announcements & Deadlines**: Curated editorial magazine layout for academic events, exams, and financial dates.
- **Zero-Dependency Quickstart**: Runs out of the box with plain browser support or with Node.js built-in HTTP server.

---

## 💻 Quick Start

### Option 1: Run with Node.js (Recommended)

```bash
# Clone the repository
git clone https://github.com/vishu404code/UniBuddy.git
cd UniBuddy

# Start the local server (zero npm dependencies required!)
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

## 👥 Demo Profiles & Roles

| Role | Access Mode | Highlights |
| :--- | :--- | :--- |
| **Student** | Instant Demo / Email Login | AI assistant chat, ticket submission, query status tracker, campus circulars. |
| **Faculty** | Instant Demo / Email Login | Ticket desk, student query review, response drafting, ticket resolution. |
| **Authority** | Instant Demo | Departmental escalation and oversight portal. |
| **Management** | Instant Demo | Campus-wide operations overview. |

---

## 🛠️ Project Structure

```
UniBuddy/
├── index.html        # Main SPA (UI, reactive state engine, KB, stylesheets)
├── server.js         # Built-in lightweight zero-dependency Node.js HTTP server
├── package.json      # NPM script definitions
├── .gitignore        # Git ignore rules
└── README.md         # Documentation
```

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
