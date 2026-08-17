import { Link } from 'react-router-dom'

export function NotFoundPage() {
  return (
    <article className="page">
      <header className="page__header">
        <h1>Not found</h1>
        <p className="page__lede">That route does not exist.</p>
      </header>
      <p>
        <Link to="/">Back to the dashboard</Link>
      </p>
    </article>
  )
}
