import { signIn } from "@/auth";

export default function LoginPage() {
  return (
    <main>
      <div className="card" style={{ maxWidth: 420, margin: "80px auto", textAlign: "center" }}>
        <h1>Cleartelligence Staffing</h1>
        <p className="muted">Sign in with your Cleartelligence Microsoft account.</p>
        <form
          action={async () => {
            "use server";
            await signIn("microsoft-entra-id", { redirectTo: "/" });
          }}
        >
          <button type="submit">Sign in with Microsoft</button>
        </form>
      </div>
    </main>
  );
}
