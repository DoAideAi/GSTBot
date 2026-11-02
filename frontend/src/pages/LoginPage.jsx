import BrandMark from "../components/BrandMark";
import AuthForm from "../components/AuthForm";
import { usePageTitle } from "../hooks/usePageTitle";

export default function LoginPage() {
  usePageTitle("Sign in");

  return (
    <div className="auth-page">
      <div className="auth-container">
        <a className="auth-home" href="/" aria-label="DoAide GST home"><BrandMark size={40} /></a>

        <h1 className="auth-title">
          DoAide <span className="auth-title-accent">GST</span>
        </h1>
        <p className="auth-subtitle">GST compliance, simplified.</p>

        <AuthForm />
      </div>
    </div>
  );
}
