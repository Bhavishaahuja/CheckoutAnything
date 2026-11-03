import { Link } from 'react-router'
import { listOrders } from '../api'
import { StatusChip } from '../components/StatusChip'
import { formatMoney, formatTime, summarizeItems } from '../lib/format'
import { useAsync } from '../lib/useAsync'

// stable loader identity so useAsync fetches once
const loadOrders = () => listOrders()

// Merchant view. Placeholder table for the scaffold: the AG Grid version replaces it.
export function DashboardPage() {
  const orders = useAsync(loadOrders)

  return (
    <section>
      <div className="page__head">
        <div>
          <h1 className="page__title">Agent orders</h1>
          <p className="page__lede">
            Payments are held until the order matches what the shopper asked for.
          </p>
        </div>
      </div>

      <div className="card">
        {orders.status === 'loading' && <p className="state">Loading orders...</p>}
        {orders.status === 'error' && (
          <p className="state state--error">Couldn't load orders: {orders.error.message}</p>
        )}
        {orders.status === 'ready' && orders.data.length === 0 && (
          <p className="state">No agent orders yet.</p>
        )}
        {orders.status === 'ready' && orders.data.length > 0 && (
          <table className="table">
            <thead>
              <tr>
                <th>Time</th>
                <th>Order</th>
                <th>Item</th>
                <th className="num">Total</th>
                <th>Status</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {orders.data.map((order) => (
                <tr key={order.id}>
                  <td className="muted">{formatTime(order.created_at)}</td>
                  <td className="mono">#{order.id}</td>
                  <td>{summarizeItems(order.items)}</td>
                  <td className="num">{formatMoney(order.total, order.currency)}</td>
                  <td>
                    <StatusChip status={order.status} />
                  </td>
                  <td className="num">
                    {order.status === 'authorized' && (
                      <Link to={'/confirm/' + order.id} className="text-link">
                        Open confirm page
                      </Link>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  )
}
