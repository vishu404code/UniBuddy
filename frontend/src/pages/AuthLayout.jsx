export default function AuthLayout({ title, children }) {
  return (
    <div className="auth-page">
      <section className="card">
        <h1>{title}</h1>
        {children}
      </section>
    </div>
  );
}
