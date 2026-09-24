// Next.js 16 request proxy (formerly middleware.ts).
// Every route except the login page, auth endpoints and static assets requires a session.
export { auth as proxy } from "@/auth";

export const config = {
  matcher: ["/((?!api/auth|login|_next/static|_next/image|favicon.ico).*)"],
};
