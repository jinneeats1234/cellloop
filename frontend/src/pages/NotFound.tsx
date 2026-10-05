import { Link } from "react-router";
import { Icon } from "../components/ui";

export default function NotFoundPage() {
  return (
    <div className="mx-auto max-w-md py-20 text-center">
      <div className="eyebrow">404</div>
      <h1 className="mt-2 text-[22px] font-semibold tracking-[-0.015em]">Page not found</h1>
      <p className="muted mt-2 text-[13.5px]">This page doesn't exist, or your role doesn't have access to it.</p>
      <Link to="/" className="btn mt-6">
        <Icon name="back" size={14} />
        Back to start
      </Link>
    </div>
  );
}
