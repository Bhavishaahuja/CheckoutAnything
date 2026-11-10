import { Link } from 'react-router'

export function NotFoundPage() {
  return (
    <div className="card state">
      <p>There's nothing at this address.</p>
      <Link to="/dashboard" className="text-link">
        Back to orders
      </Link>
    </div>
  )
}
