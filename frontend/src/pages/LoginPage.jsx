import BrandMark from "../components/BrandMark";
import AuthForm from "../components/AuthForm";
import ThemeToggle from "../components/ThemeToggle";
import { Link } from "react-router-dom";
import { usePageTitle } from "../hooks/usePageTitle";

export default function LoginPage() {
  usePageTitle("Sign in");

  return (
    <div className="auth-page auth-entry">
      <header className="auth-header">
        <Link className="auth-brand" to="/" aria-label="DoAide GST home">
          <BrandMark size={28} />
          <span>DoAide <em>GST</em></span>
        </Link>
        <div className="auth-header-actions">
          <Link to="/">Back to free tools <span aria-hidden="true">↗</span></Link>
          <ThemeToggle />
        </div>
      </header>

      <main className="auth-layout">
        <section className="auth-intro" aria-labelledby="auth-intro-title">
          <p className="auth-eyebrow"><span /> YOUR GST WORKSPACE</p>
          <h2 id="auth-intro-title">Less admin.<br /><span>More clarity.</span></h2>
          <p className="auth-intro-copy">Your invoices, input tax credits, and filing preparation. Together in one simpler workspace.</p>
          <ul className="auth-benefits">
            <li><span className="auth-benefit-icon" aria-hidden="true">01</span><div><strong>Bring your invoices together</strong><p>Upload, organise, and review your records.</p></div></li>
            <li><span className="auth-benefit-icon" aria-hidden="true">02</span><div><strong>Find what needs attention</strong><p>Reconcile GSTR-2B and review ITC mismatches.</p></div></li>
            <li><span className="auth-benefit-icon" aria-hidden="true">03</span><div><strong>Prepare with confidence</strong><p>Keep your return preparation and deadlines in view.</p></div></li>
          </ul>
          <div className="auth-pilot-note">
            <span className="auth-pilot-icon" aria-hidden="true">↗</span>
            <div><strong>New to DoAide GST?</strong><p>Explore the limited 60-day free pilot for SMBs and CA firms. <Link to="/pricing">See availability and limits</Link></p></div>
          </div>
        </section>

        <div className="auth-container">
          <AuthForm />
          <p className="auth-help">Need a quick calculation? <Link to="/">Use the free GST tools</Link></p>
        </div>
      </main>
      <footer className="auth-footer">DoAide GST <span aria-hidden="true">·</span> Built for Indian businesses.</footer>
    </div>
  );
}
