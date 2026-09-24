import NextAuth from "next-auth";
import MicrosoftEntraID from "next-auth/providers/microsoft-entra-id";

const allowedDomains = (process.env.ALLOWED_EMAIL_DOMAINS ?? "cleartelligence.com")
  .split(",")
  .map((d) => d.trim().toLowerCase())
  .filter(Boolean);

function emailAllowed(email?: string | null): boolean {
  if (!email) return false;
  const domain = email.split("@")[1]?.toLowerCase();
  return !!domain && allowedDomains.includes(domain);
}

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [
    MicrosoftEntraID({
      clientId: process.env.AUTH_MICROSOFT_ENTRA_ID_ID,
      clientSecret: process.env.AUTH_MICROSOFT_ENTRA_ID_SECRET,
      // Tenant-specific issuer: only accounts in the Cleartelligence tenant can sign in.
      issuer: `https://login.microsoftonline.com/${process.env.AUTH_MICROSOFT_ENTRA_ID_TENANT_ID}/v2.0`,
    }),
  ],
  session: { strategy: "jwt" },
  pages: { signIn: "/login" },
  callbacks: {
    // Second gate on top of the tenant restriction: the email domain must be allowlisted.
    signIn({ user, profile }) {
      const email = user.email ?? (profile as { email?: string; preferred_username?: string } | undefined)?.email
        ?? (profile as { preferred_username?: string } | undefined)?.preferred_username;
      return emailAllowed(email);
    },
    authorized({ auth }) {
      return !!auth?.user;
    },
    jwt({ token, profile }) {
      if (profile?.email) token.email = profile.email as string;
      return token;
    },
    session({ session, token }) {
      if (token.email) session.user.email = token.email;
      return session;
    },
  },
});
