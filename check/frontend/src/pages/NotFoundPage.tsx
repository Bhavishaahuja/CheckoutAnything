import { Link } from 'react-router'
import { Card } from '@/components/bits'

export function NotFoundPage() {
  return (
    <Card className="mx-auto flex max-w-md flex-col items-center gap-2 px-4 py-10 text-center">
      <p className="text-sm text-muted-foreground">There's nothing at this address.</p>
      <Link to="/dashboard" className="text-sm font-medium text-primary underline-offset-2 hover:underline">
        Back to orders
      </Link>
    </Card>
  )
}
