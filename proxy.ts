// Next.js 16 request proxy (formerly middleware.ts).
// Every route except the login page, auth endpoints and static assets requires a session.
// /api/meeting-log/import and api/dashboard are excluded because the scheduled Granola import authenticates with
// a bearer token (IMPORT_TOKEN) inside the handler, not with a browser session.
export { auth as proxy } from "@/auth";

export const config = {
  matcher: ["/((?!api/auth|api/meeting-log/import|api/dashboard|login|_next/static|_next/image|favicon.ico).*)"],
};
