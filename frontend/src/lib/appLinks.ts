// Where the two apps live, for the shared header's links. Vite bakes these in at build time.
//   VITE_CONNECT_URL  the Checkout Anything app (this one): Connect and Orders
//   VITE_CHECK_URL    the Check app: the Check dashboard and its Disputes page
// The defaults are the local dev ports from the README.

function clean(url: string | undefined, fallback: string): string {
  return (url || fallback).replace(/\/+$/, "")
}

export const CONNECT_URL = clean(import.meta.env.VITE_CONNECT_URL, "http://localhost:5173")
export const CHECK_URL = clean(import.meta.env.VITE_CHECK_URL, "http://localhost:5175")
